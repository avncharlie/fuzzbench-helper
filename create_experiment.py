#!/usr/bin/env python3
"""
create_experiment.py
--------------------
Scaffold a FuzzBench experiment directory.

Usage example:
  ./create_experiment.py \
        --exp-name my_test \
        --trials 5 \
        --trial-time 86400 \
        --benchmarks libpng-1.2.56 zlib_zlib_uncompress_fuzzer \
        --fuzzers afl aflfast \
        --fuzzbench-dir ~/dev/fuzzbench
"""

import re
import sys
import textwrap
import argparse
import subprocess

from pathlib import Path

# --------------------------------------------------------------------------- CLI
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create a FuzzBench experiment skeleton next to this script"
    )
    p.add_argument("--exp-name",      required=True,
                   help="Directory name of the experiment to create")
    p.add_argument("--trials",        required=True, type=int,
                   help="Number of trials")
    p.add_argument("--trial-time",    required=True, type=int,
                   help="max_total_time in seconds")
    p.add_argument("--benchmarks",    required=True, nargs="+",
                   help="Space‑separated list of benchmark targets")
    p.add_argument("--fuzzers",       required=True, nargs="+",
                   help="Space‑separated list of fuzzers")
    p.add_argument("--concurrent-builds", type=int, metavar="N",
                   help="Passes --concurrent-builds N to run_experiment.py")
    p.add_argument("--runners-cpus",      type=int, metavar="N",
                   help="Passes --runners-cpus N to run_experiment.py")
    p.add_argument("--fuzzbench-dir", required=True,
                   help="Path to the root of the FuzzBench source tree")
    return p.parse_args()


# --------------------------------------------------------------------- utilities
def get_global_ipv4() -> list[str]:
    """Return a list of global‑scope IPv4 addresses on this host."""
    out = subprocess.run(
        ["ip", "-4", "addr", "show", "scope", "global"],
        capture_output=True, text=True, check=False
    ).stdout
    return re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)


# -------------------------------------------------------------------------- main
def main() -> None:
    args = parse_args()

    # Resolve important paths
    script_dir      = Path(__file__).resolve().parent
    fuzzbench_dir   = Path(args.fuzzbench_dir).expanduser().resolve()
    exp_dir         = script_dir / args.exp_name
    data_dir        = exp_dir / "data"
    report_dir      = exp_dir / "report"
    webroot_dir     = report_dir / args.exp_name
    webroot_dir_exp = report_dir / "experimental" / args.exp_name
    config_path     = exp_dir / "config.yaml"

    # Sanity check – make sure run_experiment.py exists where the user pointed us
    if not (fuzzbench_dir / "experiment" / "run_experiment.py").is_file():
        sys.exit(f"Error: {fuzzbench_dir} does not look like a FuzzBench checkout")

    # ------------------------------------------------------------------ skeleton
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(exist_ok=True)

    # --------------------------- config.yaml -------------------------------
    config_yaml = textwrap.dedent(f"""\
        # Auto‑generated config for {args.exp_name}
        trials: {args.trials}
        max_total_time: {args.trial_time}
        docker_registry: gcr.io/fuzzbench
        experiment_filestore: {data_dir}
        report_filestore: {report_dir}
        local_experiment: true
        """)
    config_path.write_text(config_yaml)

    # --------------------------- run.sh ------------------------------------
    cmd_parts = [
        "PYTHONPATH=. python3 experiment/run_experiment.py",
        f"--experiment-config {config_path.resolve()}",
        f"--experiment-name {args.exp_name}",
        "--benchmarks " + " ".join(args.benchmarks),
        "--fuzzers "    + " ".join(args.fuzzers),
    ]
    if args.concurrent_builds is not None:
        cmd_parts.append(f"--concurrent-builds {args.concurrent_builds}")
    if args.runners_cpus is not None:
        cmd_parts.append(f"--runners-cpus {args.runners_cpus}")

    cmd_block = " \\\n            ".join(cmd_parts)
    run_sh = textwrap.dedent(f"""\
        #!/bin/bash
        cd "{fuzzbench_dir}"
        {cmd_block}
        """)
    run_path = exp_dir / "run.sh"
    run_path.write_text(run_sh)
    run_path.chmod(0o755)

    # --------------------------- view-report.sh -----------------------------
    ips = ", ".join([f"http://{x}:8000" for x in get_global_ipv4() + ["localhost"]])
    view_sh = textwrap.dedent(f"""\
        #!/bin/bash
        WEBROOT_PRIMARY="{webroot_dir}"
        WEBROOT_ALT="{webroot_dir_exp}"

        if [[ -d "$WEBROOT_PRIMARY" ]]; then
            echo "Serving report from $WEBROOT_PRIMARY at one of: {ips}"
            cd "$WEBROOT_PRIMARY"
        elif [[ -d "$WEBROOT_ALT" ]]; then
            echo "Serving report from $WEBROOT_ALT at one of: {ips}"
            cd "$WEBROOT_ALT"
        else
            echo "Report directory not found (checked '$WEBROOT_PRIMARY' and '$WEBROOT_ALT')."
            exit 1
        fi

        python3 -m http.server
        """)
    view_path = exp_dir / "view-report.sh"
    view_path.write_text(view_sh)
    view_path.chmod(0o755)

    # ------------------------------------------------------------------ done
    print(f"✔  Experiment '{args.exp_name}' scaffolded in {exp_dir}")
    print(f"   Run experiment: ./{args.exp_name}/run.sh")
    print(f"   See experiment report: ./{args.exp_name}/view-report.sh")
    print(f"   If using AFL, see fuzzing speeds: python3 get_fuzzer_speeds.py --exp-dir {args.exp_name}")

if __name__ == "__main__":
    main()
