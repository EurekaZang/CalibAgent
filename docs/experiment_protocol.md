# P1-P3 experiment protocol

## Claims and frozen comparisons

P1 tests whether M1 captures cross-axis structure missed by M0 under an
identical session-grouped split. Genuine P1 evidence must follow
`p1_real_data_protocol.md`; synthetic replay is only a software control.

P2 tests the declared base-plus-excess noise contract and 95% predictive
coverage overall and within each synthetic distortion family.

P3 tests whether task-weighted exact integrated variance reduction lowers the
first trial meeting both RMSE and epistemic-uncertainty thresholds relative to
LHS. Random, Sobol, Bayesian D-optimal, without-task-weight, and a full
candidate-pool dense oracle are secondary controls.

The five development seeds fixed a six-command warm start covering both signs
of all three axes, the task distribution, RMSE threshold 0.04, uncertainty
threshold 0.0015, and final evaluation budget 160. The main config was frozen
locally at 2026-07-18 06:21:21 UTC before evaluating the disjoint seeds
1001-1020. This is a local protocol lock, not third-party preregistration.

A run that misses the target is assigned `max_trials + 1`; it is never dropped.
Distortion families use independent latent parameter offsets. Family remains a
repeated condition and seed is the conservative independent unit. Inference
therefore averages families within each seed before a one-sided paired Wilcoxon
test and seed bootstrap.

## Isolation

- task and evaluation commands use disjoint fixed Sobol seeds;
- mapping and observation-noise seeds are paired across methods;
- every sequential method receives the same six safe seed-design commands;
- feature scaling sees predeclared candidate commands but no output;
- held-out mapping truth and reference covariance are used only for metrics;
- pilot and main seeds are disjoint;
- main thresholds, baselines, and seeds are source-versioned.

## Outputs

`outputs/p3_main/trial_trace.csv` contains every sequential command and metric.
`metrics.csv` has 420 unique family/method/seed rows. `paired_statistics.json`
uses 20 independent seeds; it does not pool the 60 repeated family conditions.
`dense_oracle_metrics.csv` records the 256-command performance ceiling.
`manifest.json` points to a resolvable source commit and `resolved_config.json`
contains every algorithm parameter. Figures rebuild from CSV artifacts.

The legacy `outputs/p3_pilot/paired_statistics.json` is retained only as a
historical artifact and is invalid for publication inference.
