#!/usr/bin/env python3

import sys
import tarfile
import argparse
import statistics
from collections import defaultdict

from pathlib import Path


# ---- colour helpers ---------------------------------------------------------
RESET   = "\033[0m"
BOLD    = "\033[1m"

CYAN    = "\033[36m"   # headers
MAGENTA = "\033[35m"   # fuzzer names
GREEN   = "\033[32m"   # fastest fuzzer for a benchmark
YELLOW  = "\033[33m"   # everyone else
# -----------------------------------------------------------------------]]]]]]

DBG = False

def parse_args() -> argparse.Namespace:
    global DBG
    p = argparse.ArgumentParser(
        description="Create a FuzzBench experiment skeleton next to this script"
    )
    p.add_argument("--exp-dir",      required=True,
                   help="Experiment directory (needs to contain 'data' subfolder)")
    p.add_argument("--debug", action='store_true')
    ret = p.parse_args()
    if ret.debug:
        DBG = True
    return ret


def get_speed_from_fuzzer_stats(stats: str) -> float:
    for line in stats.splitlines():
        if line.strip().startswith('execs_per_sec'):
            return float((line.split(':')[1]).strip())

def get_trial_speed(trial: Path) -> float:
    corpus_dir = trial / "corpus"

    # sort archives from latest to first
    def archive_no(p):
        return int(p.name.replace('.tar.gz', '').replace('corpus-archive-', ''))
    tar_archives = filter(lambda x: x.name.startswith('corpus-archive-') and x.name.endswith('.tar.gz'), corpus_dir.iterdir())
    ordered = sorted(tar_archives, key=lambda x: archive_no(x), reverse=True)

    for t in ordered:
        with tarfile.open(t, 'r:gz') as tf:
            # if DBG: print(f'looking through {t}')
            for f in tf.getmembers():
                if f.name.endswith('fuzzer_stats'):
                    if DBG: print(f'Found fuzzer_stats in {t}')
                    stats = tf.extractfile(f).read().decode()
                    return get_speed_from_fuzzer_stats(stats)

def get_exp_speeds(dir: Path) -> list[float]:
    ret = []
    for x in dir.iterdir():
        sp = get_trial_speed(x)
        if sp != None:
            ret.append(sp)
    return ret

def main() -> None:
    args = parse_args()

    exp_dir = Path(args.exp_dir).expanduser().resolve()
    exp_name = exp_dir.name
    data_dir = exp_dir / 'data'
    exp_dir_base = data_dir / exp_name / 'experiment-folders'

    if not (exp_dir_base).is_dir():
        sys.exit(f"Error: {data_dir} does not look like a FuzzBench data folder")


    results = defaultdict(dict)

    exp_dirs = filter(lambda x: x.is_dir(), exp_dir_base.iterdir())
    for x in exp_dirs:
        fuzzer = x.name.split('-')[-1]
        benchmark = x.name.replace('-'+fuzzer, '')
        trial_speeds = get_exp_speeds(x)
        if len(trial_speeds) == 0:
            print(f"{x.name} doesn't have any data yet, skipping...")
            continue
        mean = statistics.mean(trial_speeds)
        stdev = statistics.stdev(trial_speeds)if len(trial_speeds) > 1 else -1
        results[benchmark][fuzzer] = (trial_speeds, mean, stdev)


    if DBG: print()

    for benchmark, fuzzers_dict in results.items():
        print(f"{BOLD}{CYAN}{benchmark}{RESET}")
        fuzzers = sorted(fuzzers_dict, key=lambda f: fuzzers_dict[f][1], reverse=True) # index 1 -> mean
        fastest = fuzzers[0]
        for fuzzer in fuzzers:
            speeds, mean, stdev = fuzzers_dict[fuzzer]
            colour = GREEN if fuzzer == fastest else YELLOW
            stdev_str = ''
            trials = 'trial'
            trials_up = 'Trial'
            if stdev != -1:
                stdev_str = f", σ {stdev:.2f}"
                trials = 'trials'
                trials_up = 'Trials'

            print(
                f"  {MAGENTA}{fuzzer}{RESET}: "
                f"{colour}{mean:.2f}{RESET} exec/s "
                f"({len(speeds)} {trials}{stdev_str}). "
                f"{trials_up} → {speeds}"
            )

if __name__ == "__main__":
    main()
