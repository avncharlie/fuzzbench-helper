# FuzzBench Quickstart

Script to quickly set up local FuzzBench experiments.

```
$ python3 create_experiment.py --fuzzbench-dir ~/fuzzbench --exp-name example --trials 5 --trial-time 1800 --benchmarks freetype2_ftfuzzer bloaty_fuzz_target --fuzzers afl aflplusplus --concurrent-builds 10
✔  Experiment 'example' scaffolded in /home/alvin/fuzzbench-quickstart/example
   Run experiment: ./example/run.sh
   See experiment report: ./example/view-report.sh
```
