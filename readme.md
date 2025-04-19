# FuzzBench Helper

Scripts to work with local FuzzBench experiments.

**Create experiment:**
```
$ python3 create_experiment.py --fuzzbench-dir ~/fuzzbench --exp-name example --trials 5 --trial-time 1800 --benchmarks freetype2_ftfuzzer bloaty_fuzz_target --fuzzers afl aflplusplus --concurrent-builds 10
✔  Experiment 'example' scaffolded in /home/alvin/fuzzbench-quickstart/example
   Run experiment: ./example/run.sh
   See experiment report: ./example/view-report.sh
```
**See fuzzer performance:**
```
$ .python3 get_fuzzer_speeds.py --exp-dir example
bloaty_fuzz_target
  aflplusplus: 2687.08 exec/s (5 trials, σ 457.90). Trials → [2814.87, 2394.23, 2975.83, 3193.37, 2057.09]
  afl: 501.00 exec/s (5 trials, σ 968.37). Trials → [2228.26, 24.02, 196.7, 29.2, 26.82]
freetype2_ftfuzzer
  aflplusplus: 6550.73 exec/s (5 trials, σ 598.57). Trials → [6815.35, 5834.89, 7267.16, 6029.37, 6806.86]
  afl: 4549.13 exec/s (5 trials, σ 313.39). Trials → [4755.3, 4028.04, 4634.3, 4513.74, 4814.27]
```
