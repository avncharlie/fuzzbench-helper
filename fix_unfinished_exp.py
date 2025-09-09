#!/usr/bin/env python3
import argparse
import csv
import gzip
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Dict, List, Tuple
from collections import Counter

# -------------------- IO helpers --------------------

def decompress_gzip(src: Path, out_dir: Path) -> Path:
    """Decompress a .gzip/.gz file into out_dir and return the decompressed CSV path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Keep the base CSV filename (e.g., data.csv from data.csv.gz)
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

# -------------------- Core logic --------------------

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
) -> Tuple[List[dict], List[int]]:
    """
    Substitute ONLY by (fuzzer, benchmark). Exact trial_id matches are ignored.
    For each unfinished trial in the unfinished dataset:
      - Find a unique candidate in substitute with the same (fuzzer, benchmark)
        that (by default) finished (max time >= trial_time), or the best available
        if --allow-incomplete-substitute is set.
      - Replace ALL rows for that unfinished trial_id with ALL rows from the
        chosen substitute trial, rewriting 'trial_id' to the destination id.
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

    for dest_tid, f, b, _ in unfinished_meta:
        # STRICTLY match by (fuzzer, benchmark) — no exact-id fallback
        sub_tid, sub_rows = find_unique_finished_candidate_by_fb(
            sub_by_tid, trial_time, (f, b), allow_incomplete
        )
        mapping[dest_tid] = (sub_tid, sub_rows)
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

    return new_rows, unfinished_tids


# -------------------- CLI --------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Fix an experiment CSV by substituting trials from another experiment."
    )
    p.add_argument("--unfinished-exp", required=True, help="Path to CSV or .gz/.gzip with unfinished trials")
    p.add_argument("--substitute-exp", required=True, help="Path to CSV or .gz/.gzip with substitute trials")
    p.add_argument("--output", required=True, help="Path to write the fixed CSV (plain .csv)")
    p.add_argument("--trial-time", type=int, required=True, help="Trial time threshold (e.g., 86400)")

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
    output = Path(args.output)

    if not unfinished.exists():
        raise SystemExit(f"File not found: {unfinished}")
    if not substitute.exists():
        raise SystemExit(f"File not found: {substitute}")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # IMPORTANT: separate subdirs to avoid filename collisions like data.csv.gz -> data.csv
        un_csv  = resolve_csv_path(unfinished,  tmpdir / "unfinished")
        sub_csv = resolve_csv_path(substitute,  tmpdir / "substitute")

        # Guard against accidental collisions
        try:
            if un_csv.resolve() == sub_csv.resolve():
                raise SystemExit("Internal error: both CSV paths resolved to the same file; "
                                 "check gzip extraction logic.")
        except FileNotFoundError:
            pass  # On some systems resolve() can fail if path doesn't exist yet

        un_rows, un_hdr = read_csv_rows(un_csv)
        sub_rows, sub_hdr = read_csv_rows(sub_csv)

        fixed_rows, swapped_tids = substitute_trials(
            un_rows, sub_rows, args.trial_time, args.verbose, args.allow_incomplete_substitute
        )
        hdr = union_headers(un_hdr, sub_hdr)
        for req in ("trial_id", "time", "fuzzer", "benchmark"):
            if req not in hdr:
                hdr.append(req)

        write_csv_rows(fixed_rows, hdr, output)

    if swapped_tids:
        print("Substituted trials:", ", ".join(str(t) for t in sorted(swapped_tids)))
    else:
        print("No unfinished trials detected; wrote a copy to output.")

if __name__ == "__main__":
    main()
