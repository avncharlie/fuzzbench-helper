#!/usr/bin/env python3
import argparse
import csv
import gzip
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Dict, List, Tuple, Optional
from collections import Counter, defaultdict
import statistics

# -------------------- IO helpers --------------------

def decompress_gzip(src: Path, out_dir: Path) -> Path:
    """Decompress a .gzip/.gz file into out_dir and return the decompressed CSV path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.name[:-len(src.suffix)] if src.suffix else (src.name + ".csv")
    dst = out_dir / stem
    with gzip.open(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    return dst

def resolve_csv_path(maybe_gz: Path, out_dir: Path) -> Path:
    """Return a CSV path; gunzip into out_dir if needed (unique per input!)."""
    if maybe_gz.suffix.lower() in {".gz", ".gzip"}:
        return decompress_gzip(maybe_gz, out_dir)
    return maybe_gz

def read_csv_rows(csv_path: Path):
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return rows, reader.fieldnames or []

def write_csv_rows(rows: List[dict], fieldnames: List[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

# -------------------- Core logic for data.csv fix --------------------

def group_by_trial(rows: List[dict]) -> Dict[int, List[dict]]:
    by_tid: Dict[int, List[dict]] = {}
    for r in rows:
        try:
            tid = int(r["trial_id"])
        except Exception:
            raise SystemExit("CSV is missing a valid 'trial_id' column.")
        by_tid.setdefault(tid, []).append(r)
    return by_tid

def max_time_for_trial(trial_rows: List[dict]) -> int:
    mt = -1
    for r in trial_rows:
        try:
            t = int(r["time"])
        except Exception:
            raise SystemExit("CSV is missing a valid 'time' column.")
        if t > mt:
            mt = t
    return mt

def _mode(values: List[str]) -> str:
    values = [v for v in values if v]
    return Counter(values).most_common(1)[0][0] if values else ""

def fuzzer_bench_for_trial(trial_rows: List[dict]) -> Tuple[str, str]:
    fuzzer = _mode([r.get("fuzzer", "") for r in trial_rows])
    bench  = _mode([r.get("benchmark", "") for r in trial_rows])
    return fuzzer, bench

def union_headers(a: List[str], b: List[str]) -> List[str]:
    seen, merged = set(), []
    for name in (a or []):
        if name not in seen:
            merged.append(name); seen.add(name)
    for name in (b or []):
        if name not in seen:
            merged.append(name); seen.add(name)
    return merged

def list_unfinished_trials(un_rows: List[dict], trial_time: int) -> List[Tuple[int, str, str, int]]:
    un_by_tid = group_by_trial(un_rows)
    unfinished = []
    for tid, trows in un_by_tid.items():
        mt = max_time_for_trial(trows)
        if mt < trial_time:
            f, b = fuzzer_bench_for_trial(trows)
            unfinished.append((tid, f, b, mt))
    return sorted(unfinished, key=lambda x: x[0])

def find_unique_finished_candidate_by_fb(
    sub_by_tid: Dict[int, List[dict]],
    trial_time: int,
    target_fb: Tuple[str, str],
    allow_incomplete: bool
) -> Tuple[int, List[dict]]:
    candidates: List[Tuple[int, List[dict], int]] = []
    for tid, trows in sub_by_tid.items():
        fb = fuzzer_bench_for_trial(trows)
        if fb == target_fb:
            mt = max_time_for_trial(trows)
            if allow_incomplete or mt >= trial_time:
                candidates.append((tid, trows, mt))

    if not candidates:
        raise SystemExit(
            f"No {'suitable' if allow_incomplete else 'finished'} substitute found for "
            f"fuzzer={target_fb[0]}, benchmark={target_fb[1]}"
        )
    if allow_incomplete:
        candidates.sort(key=lambda x: x[2], reverse=True)
        best_tid, best_rows, best_time = candidates[0]
        ties = [tid for tid, _, mt in candidates if mt == best_time and tid != best_tid]
        if ties:
            raise SystemExit(
                f"Multiple substitute candidates with the same best time ({best_time}) for "
                f"fuzzer={target_fb[0]}, benchmark={target_fb[1]}; ambiguous which to use."
            )
        return best_tid, best_rows

    if len(candidates) > 1:
        raise SystemExit(
            f"Multiple finished substitutes found for fuzzer={target_fb[0]}, benchmark={target_fb[1]}; "
            "ambiguous which to use."
        )
    tid, rows, _ = candidates[0]
    return tid, rows

def substitute_trials(
    unfinished_rows: List[dict],
    substitute_rows: List[dict],
    trial_time: int,
    verbose: bool,
    allow_incomplete: bool,
) -> Tuple[List[dict], List[int], List[Tuple[int, str, str, int]]]:
    """
    Substitute ONLY by (fuzzer, benchmark). Exact trial_id matches are ignored.
    Returns (new_rows, substituted_dest_tids, plan) where plan entries are
    (dest_tid, fuzzer, benchmark, src_tid).
    """
    un_by_tid = group_by_trial(unfinished_rows)
    sub_by_tid = group_by_trial(substitute_rows)

    unfinished_meta = list_unfinished_trials(unfinished_rows, trial_time)
    if verbose:
        print("Unfinished trials detected (tid, fuzzer, benchmark, max_time):")
        for tid, f, b, mt in unfinished_meta:
            print(f"  {tid}, {f}, {b}, {mt}")

    unfinished_tids = [tid for tid, _, _, _ in unfinished_meta]
    mapping: Dict[int, Tuple[int, List[dict]]] = {}
    plan: List[Tuple[int, str, str, int]] = []

    for dest_tid, f, b, _ in unfinished_meta:
        sub_tid, sub_rows = find_unique_finished_candidate_by_fb(
            sub_by_tid, trial_time, (f, b), allow_incomplete
        )
        mapping[dest_tid] = (sub_tid, sub_rows)
        plan.append((dest_tid, f, b, sub_tid))
        if verbose:
            mt = max_time_for_trial(sub_rows)
            print(f"  -> using substitute by (fuzzer,bench) ({f}, {b}): sub_tid={sub_tid}, mt={mt}")

    # Build output: keep all non-unfinished; replace unfinished with mapped rows (rewrite trial_id)
    new_rows: List[dict] = []
    unfinished_tid_set = set(unfinished_tids)
    for r in unfinished_rows:
        tid = int(r["trial_id"])
        if tid not in unfinished_tid_set:
            new_rows.append(r)

    for dest_tid, (src_tid, src_rows) in mapping.items():
        for r in src_rows:
            nr = dict(r)
            nr["trial_id"] = str(dest_tid)  # always rewrite to destination id
            new_rows.append(nr)

    return new_rows, unfinished_tids, plan

# -------------------- Throughput CSV helpers --------------------

SpeedTrialMap = Dict[int, Tuple[float, Optional[float]]]
SpeedResults = Dict[Tuple[str, str], SpeedTrialMap]  # key=(benchmark,fuzzer)

def read_speeds_csv(csv_path: Path) -> SpeedResults:
    """
    Parse throughput CSV. Requires 'trials' with 'tid:val' pairs (new format).
    Optionally parses 'trial_times' (tid:seconds).
    """
    res: SpeedResults = defaultdict(dict)
    with csv_path.open(newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        fields = rdr.fieldnames or []
        has_times = "trial_times" in fields
        for row in rdr:
            bench = row["benchmark"]
            fuzz = row["fuzzer"]
            key = (bench, fuzz)
            trials_str = (row.get("trials") or "").strip()
            if not trials_str:
                continue
            if ":" not in trials_str:
                raise SystemExit(
                    f"{csv_path}: 'trials' for ({bench},{fuzz}) lacks trial IDs. "
                    "Regenerate speeds CSV with trial_id mapping (new format)."
                )
            # parse speeds
            for item in trials_str.split():
                tid_s, val_s = item.split(":", 1)
                res[key][int(tid_s)] = (float(val_s), None)
            # parse times if present
            if has_times:
                times_str = (row.get("trial_times") or "").strip()
                if times_str:
                    for item in times_str.split():
                        tid_s, t_s = item.split(":", 1)
                        tid = int(tid_s)
                        if tid in res[key]:
                            spd, _ = res[key][tid]
                            res[key][tid] = (spd, float(t_s))
                        else:
                            res[key][tid] = (float("nan"), float(t_s))
    return res

def write_speeds_csv(res: SpeedResults, out_path: Path) -> None:
    """
    Write a throughput CSV with recalculated mean/stdev from the trial_map.
    """
    # gather keys
    benches = sorted({k[0] for k in res.keys()})
    # build fuzzer order within each bench for stable output
    by_bench: Dict[str, List[str]] = defaultdict(list)
    for (b, f) in res.keys():
        by_bench[b].append(f)
    for b in by_bench:
        by_bench[b] = sorted(set(by_bench[b]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["benchmark", "fuzzer", "mean", "stdev", "num_trials", "trials", "trial_times"])
        for bench in benches:
            for fuzz in by_bench[bench]:
                tmap = res.get((bench, fuzz), {})
                vals = [v for (v, _t) in tmap.values() if not _is_nan(v)]
                mean = statistics.mean(vals) if vals else float("nan")
                stdev = statistics.stdev(vals) if len(vals) > 1 else 0.0
                trials_field = " ".join(f"{tid}:{v:.2f}" for tid, (v, _t) in sorted(tmap.items()))
                times_field = " ".join(f"{tid}:{int(t)}" for tid, (_v, t) in sorted(tmap.items()) if t is not None)
                w.writerow([bench, fuzz, _fmt_num(mean), f"{stdev:.2f}", len(tmap), trials_field, times_field])

def _is_nan(x: float) -> bool:
    return x != x  # NaN check

def _fmt_num(x: float) -> str:
    return "nan" if _is_nan(x) else f"{x:.2f}"

def apply_substitution_plan_to_speeds(
    speeds_unfinished: SpeedResults,
    speeds_substitute: SpeedResults,
    plan: List[Tuple[int, str, str, int]],
    verbose: bool,
) -> SpeedResults:
    """
    For each (dest_tid, fuzzer, bench, src_tid) in plan:
      speeds_unfinished[(bench,fuzzer)][dest_tid] = speeds_substitute[(bench,fuzzer)][src_tid]
    Recomputing mean/stdev happens in write_speeds_csv.
    """
    for dest_tid, fuzzer, bench, src_tid in plan:
        key = (bench, fuzzer)
        if key not in speeds_substitute:
            raise SystemExit(f"Substitute speeds CSV missing ({bench}, {fuzzer}) needed for trial {dest_tid}")
        if src_tid not in speeds_substitute[key]:
            raise SystemExit(
                f"Substitute speeds CSV missing src trial_id={src_tid} for ({bench}, {fuzzer})"
            )
        src_val = speeds_substitute[key][src_tid]
        # ensure dest map exists
        if key not in speeds_unfinished:
            speeds_unfinished[key] = {}
        speeds_unfinished[key][dest_tid] = src_val
        if verbose:
            spd, rt = src_val
            rt_s = f", time={int(rt)}s" if rt is not None else ""
            print(f"  [throughput] ({bench},{fuzzer}) dest_tid={dest_tid} <- src_tid={src_tid} speed={spd:.2f}{rt_s}")
    return speeds_unfinished

# -------------------- CLI --------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Fix an experiment CSV by substituting trials from another experiment."
    )
    p.add_argument("--unfinished-exp", required=True, help="Path to CSV or .gz/.gzip with unfinished trials")
    p.add_argument("--substitute-exp", required=True, help="Path to CSV or .gz/.gzip with substitute trials")
    p.add_argument("--output-data-csv", required=True, help="Path to write the fixed experiment data CSV")
    p.add_argument("--trial-time", type=int, required=True, help="Trial time threshold (e.g., 86400)")

    # Optional throughput CSV merging
    p.add_argument("--unfinished-throughput-csv", help="Throughput CSV (unfinished exp) with trial_id:speed format")
    p.add_argument("--substitute-throughput-csv", help="Throughput CSV (substitute exp) with trial_id:speed format")
    p.add_argument("--output-throughput-csv", help="Path to write merged throughput CSV")

    # Verbosity: default ON, but allow --quiet to disable
    vb = p.add_mutually_exclusive_group()
    vb.add_argument("--verbose", dest="verbose", action="store_true",
                    help="Print debug info about substitutions (default).")
    vb.add_argument("--quiet", dest="verbose", action="store_false",
                    help="Silence debug info")
    p.set_defaults(verbose=True)

    p.add_argument("--allow-incomplete-substitute", action="store_true",
                   help="Allow using the best available candidate even if < trial-time")

    args = p.parse_args(argv)

    unfinished = Path(args.unfinished_exp)
    substitute = Path(args.substitute_exp)
    out_data = Path(args.output_data_csv)

    if not unfinished.exists():
        raise SystemExit(f"File not found: {unfinished}")
    if not substitute.exists():
        raise SystemExit(f"File not found: {substitute}")

    # If any throughput flag is given, require all three
    use_speeds = any([args.unfinished_throughput_csv, args.substitute_throughput_csv, args.output_throughput_csv])
    if use_speeds and not (args.unfinished_throughput_csv and args.substitute_throughput_csv and args.output_throughput_csv):
        raise SystemExit("If using throughput CSVs, you must provide --unfinished-speeds-csv, "
                         "--substitute-speeds-csv, and --output-throughput-csv.")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # Separate subdirs to avoid filename collisions like data.csv.gz -> data.csv
        un_csv  = resolve_csv_path(unfinished,  tmpdir / "unfinished")
        sub_csv = resolve_csv_path(substitute,  tmpdir / "substitute")

        # Guard against accidental collisions
        try:
            if un_csv.resolve() == sub_csv.resolve():
                raise SystemExit("Internal error: both CSV paths resolved to the same file; check gzip extraction.")
        except FileNotFoundError:
            pass

        un_rows, un_hdr = read_csv_rows(un_csv)
        sub_rows, sub_hdr = read_csv_rows(sub_csv)

        fixed_rows, swapped_tids, plan = substitute_trials(
            un_rows, sub_rows, args.trial_time, args.verbose, args.allow_incomplete_substitute
        )
        hdr = union_headers(un_hdr, sub_hdr)
        for req in ("trial_id", "time", "fuzzer", "benchmark"):
            if req not in hdr:
                hdr.append(req)

        write_csv_rows(fixed_rows, hdr, out_data)

        if swapped_tids:
            print("Substituted trials:", ", ".join(str(t) for t in sorted(swapped_tids)))
        else:
            print("No unfinished trials detected; wrote a copy to output.")

        # If requested, also patch throughput CSV
        if use_speeds:
            unfinished_speeds_path = Path(args.unfinished_throughput_csv)
            substitute_speeds_path = Path(args.substitute_throughput_csv)
            out_speeds_path = Path(args.output_throughput_csv)

            if not unfinished_speeds_path.exists():
                raise SystemExit(f"File not found: {unfinished_speeds_path}")
            if not substitute_speeds_path.exists():
                raise SystemExit(f"File not found: {substitute_speeds_path}")

            speeds_unfinished = read_speeds_csv(unfinished_speeds_path)
            speeds_substitute = read_speeds_csv(substitute_speeds_path)

            merged = apply_substitution_plan_to_speeds(
                speeds_unfinished, speeds_substitute, plan, args.verbose
            )
            write_speeds_csv(merged, out_speeds_path)
            print(f"Throughput CSV written to {out_speeds_path}")

if __name__ == "__main__":
    main()
