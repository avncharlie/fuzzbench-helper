#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import tarfile
import argparse
import statistics
from collections import defaultdict
from pathlib import Path

# ── plotting ──────────────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")          # so the script works on head-less servers
import matplotlib.pyplot as plt
import numpy as np
# ───────────────────────────────────────────────────────────────────────────

# ---- colour helpers -------------------------------------------------------
RESET   = "\033[0m"
BOLD    = "\033[1m"
CYAN    = "\033[36m"   # headers
MAGENTA = "\033[35m"   # fuzzer names
GREEN   = "\033[32m"   # fastest fuzzer for a benchmark
YELLOW  = "\033[33m"   # everyone else
# --------------------------------------------------------------------------

DBG = False


def parse_args() -> argparse.Namespace:
    global DBG
    p = argparse.ArgumentParser(
        description="Summarise a FuzzBench experiment *and* emit a throughput chart."
    )
    p.add_argument("--exp-dir", required=True,
                   help="Experiment directory (needs to contain 'data' subfolder)")
    p.add_argument("--debug", action="store_true",
                   help="Verbose run-time prints for troubleshooting")
    return p.parse_args()


# ---- helpers to pull exec/sec numbers out of tar archives -----------------
def get_speed_from_fuzzer_stats(stats: str) -> float:
    for line in stats.splitlines():
        if line.strip().startswith("execs_per_sec"):
            return float(line.split(":")[1].strip())


def get_trial_speed(trial: Path) -> float | None:
    corpus_dir = trial / "corpus"

    # newest‒to‒oldest order for the corpus-archive-<N>.tar.gz files
    def archive_no(p: Path) -> int:
        return int(p.name.replace(".tar.gz", "").replace("corpus-archive-", ""))

    tar_archives = filter(
        lambda x: x.name.startswith("corpus-archive-") and x.name.endswith(".tar.gz"),
        corpus_dir.iterdir()
    )
    ordered = sorted(tar_archives, key=archive_no, reverse=True)

    for t in ordered:
        with tarfile.open(t, "r:gz") as tf:
            for f in tf.getmembers():
                if f.name.endswith("fuzzer_stats"):
                    if DBG:
                        print(f"Found fuzzer_stats in {t}")
                    stats = tf.extractfile(f).read().decode()
                    return get_speed_from_fuzzer_stats(stats)
    return None


def get_exp_speeds(dir_: Path) -> list[float]:
    speeds = [s for s in (get_trial_speed(p) for p in dir_.iterdir()) if s is not None]
    return speeds


# ---- chart helper ---------------------------------------------------------
def emit_chart(results: dict[str, dict[str, tuple[list[float], float, float]]],
               out_path: Path,
               show: bool = False) -> None:
    """Create a grouped bar-chart and save it as PNG."""
    benchmarks = sorted(results.keys())
    fuzzers = sorted({f for v in results.values() for f in v.keys()})

    means = np.full((len(benchmarks), len(fuzzers)), np.nan)
    stds  = np.full_like(means, np.nan)

    for bi, bench in enumerate(benchmarks):
        for fi, fuzzer in enumerate(fuzzers):
            if fuzzer in results[bench]:
                _, mean, std = results[bench][fuzzer]
                means[bi, fi] = mean
                stds [bi, fi] = std

    x = np.arange(len(benchmarks))
    width = 0.8 / len(fuzzers)        # keep total group width <= 0.8
    offsets = (np.arange(len(fuzzers)) - (len(fuzzers) - 1)/2) * width

    fig, ax = plt.subplots(figsize=(max(10, len(benchmarks) * 1.8), 6))
    for fi, fuzzer in enumerate(fuzzers):
        bars = ax.bar(
            x + offsets[fi],
            means[:, fi],
            width,
            label=fuzzer.replace('_', ' '),
            yerr=stds[:, fi],
            capsize=4,
        )
        ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=8)

    ax.set_ylabel("Executions per second")
    ax.set_title("Throughput (mean ± σ)")
    ax.set_xticks(x)
    ax.set_xticklabels(benchmarks, rotation=30, ha="right")
    ax.legend(title="Fuzzer")
    fig.tight_layout()
    plt.savefig(out_path, dpi=150)
    if show:
        plt.show()
    plt.close(fig)


# ---- main -----------------------------------------------------------------
def main() -> None:
    global DBG
    args = parse_args()
    DBG = args.debug

    exp_dir  = Path(args.exp_dir).expanduser().resolve()
    exp_name = exp_dir.name
    data_dir = exp_dir / "data"
    base_dir = data_dir / exp_name / "experiment-folders"

    if not base_dir.is_dir():
        sys.exit(f"Error: {data_dir} does not look like a FuzzBench data folder")

    results: dict[str, dict[str, tuple[list[float], float, float]]] = defaultdict(dict)

    for x in filter(Path.is_dir, base_dir.iterdir()):
        fuzzer     = x.name.split("-")[-1]
        benchmark  = x.name[: -(len(fuzzer) + 1)]
        trial_vals = get_exp_speeds(x)

        if not trial_vals:
            print(f"{x.name} has no data yet, skipping…")
            continue

        mean  = statistics.mean(trial_vals)
        stdev = statistics.stdev(trial_vals) if len(trial_vals) > 1 else 0.0
        results[benchmark][fuzzer] = (trial_vals, mean, stdev)

    # ---- nicely formatted text summary -----------------------------------
    for benchmark, fuzzers_dict in results.items():
        print(f"{BOLD}{CYAN}{benchmark}{RESET}")
        fuzzers = sorted(fuzzers_dict, key=lambda f: fuzzers_dict[f][1], reverse=True)
        fastest = fuzzers[0]

        for fuzzer in fuzzers:
            speeds, mean, stdev = fuzzers_dict[fuzzer]
            colour     = GREEN if fuzzer == fastest else YELLOW
            stdev_part = f", σ {stdev:.2f}" if stdev else ""
            plural     = "trial" if len(speeds) == 1 else "trials"

            print(
                f"  {MAGENTA}{fuzzer}{RESET}: "
                f"{colour}{mean:.2f}{RESET} exec/s "
                f"({len(speeds)} {plural}{stdev_part}). "
                f"Trials → {speeds}"
            )

    # ---- bar chart -------------------------------------------------------
    if results:
        png_path = exp_dir / "throughput.png"
        emit_chart(results, png_path, show=False)
        print(f"\nChart saved to {png_path}")

if __name__ == "__main__":
    main()
