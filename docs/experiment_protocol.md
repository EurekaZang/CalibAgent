# P1-P5 experiment protocol

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

`evidence/p3_main/trial_trace.csv` contains every sequential command and metric.
`metrics.csv` has 420 unique family/method/seed rows. `paired_statistics.json`
uses 20 independent seeds; it does not pool the 60 repeated family conditions.
`dense_oracle_metrics.csv` records the 256-command performance ceiling.
`manifest.json` points to a resolvable source commit and `resolved_config.json`
contains every algorithm parameter. Figures rebuild from CSV artifacts.

The legacy `outputs/p3_pilot/paired_statistics.json` is retained only as a
historical artifact and is invalid for publication inference.

## P4 safety and stopping protocol

P4 replays the 60 frozen active trajectories from P3 without refitting or
selecting trajectories. Stopping requires the minimum trial/coverage gates,
validation RMSE, uncertainty threshold, and two consecutive confirmations.
The oracle target is the first trial satisfying the frozen validation and
uncertainty gates. Publication thresholds are premature stopping below 5%,
median extra trials at most 3, and p95 extra trials at most 4.

Hard safety is evaluated separately through 20 replicates of 15 hazard
families (300 cases), 20 safe controls, and 160 runtime fault cases. The
planner cannot bypass the non-learned filter. State-machine happy/fault paths
must terminate in `done`/`abort`; an invalid transition fails closed.

## P5 Isaac Lab protocol

P5 runs the official Unitree Go2 manager-based velocity tasks under Isaac Lab
v2.3.2 commit `37ddf626871758333d6ed89cf64ad702aef127d0`, Isaac Sim 5.1,
PhysX, and hash-pinned official flat/rough policy checkpoints. CalibAgent does
not train the locomotion policy. It selects commands outside the task,
applies the P4 safety envelope, processes root-pose measurements, updates an M2
Bayesian model, and evaluates eight fixed held-out commands.

The main design has 20 paired seeds (5301–5320), 12 calibration trials, and:

- Tier A affine command distortion on flat terrain;
- Tier A deadzone/saturation distortion on flat terrain;
- Tier B low friction + 2 kg payload + 2 cm COM shift;
- Tier B rough terrain + 1 kg payload + 1 cm COM shift.

Each scenario must improve pooled RMSE by at least 5%, have a strictly positive
paired-seed bootstrap 95% CI lower bound, retain at least 85% calibration and
80% validation rows, show actual motion in at least 85% of valid held-out
trials, contain no nonfinite values or serious event, and issue zero command
within 40 ms of a safety abort.

Two completed development attempts are not pooled with the main result. The
first exposed weak-prior overfit; the second used independent seeds and exposed
rough-terrain coupled-command invalidity. The final safety-constrained protocol
was frozen before the disjoint 5301–5320 confirmation. A later launcher failure
generated no metrics and only corrected an impossible request for 128
non-duplicate candidates; the same unseen confirmation seeds were rerun.
