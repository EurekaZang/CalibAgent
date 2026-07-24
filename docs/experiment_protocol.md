# P1-P7 experiment protocol

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

## P6 simulated domain-shift protocol

P6 uses the same pinned Isaac Lab/Isaac Sim/PhysX runtime and official flat Go2
policy as P5. Each scenario executes frozen, passive-update, and full
detection-plus-active-recovery controls on 20 paired seeds (6601–6620). The
three predeclared shifts are gain/coupling, friction plus 3 kg payload plus
3 cm COM, and a mixed gain/physics/context shift. Physics changes are applied
in place rather than by relaunching the environment.

The detector must reject isolated and two-sample outliers, latch from at least
three positive observations in a five-trial window, and raise no pre-shift
false alarms. Recovery receives 12 trials, exactly 40% of the 30-trial dense
budget. Publication gates require detection and full recovery rates of at least
95%/90%, p95 delays of at most 5/12 trials, a strictly positive paired
full-versus-frozen 95% bootstrap CI, at least 90% full win rate, at least 80%
valid observations, abort response within 40 ms, and zero serious events.

All three methods share seeds, shift events, policy, commands used for monitoring,
and safety limits. Four thousand seed-level bootstrap resamples are used for
the paired final-RMSE effect. Development outputs are excluded from the frozen
6601–6620 confirmation and retained in
`reports/p6_development_audit.md`.

## P7 simulated downstream-navigation protocol

P7 holds the local waypoint planner, map geometry, locomotion policy, command
limits, safety logic, and physics fixed across B0 raw, B1 dense, and B8 full.
B1 uses 30 calibration trials; B8 uses 12 (40%). The independent confirmation
uses seeds 8001–8060 on open-field, slalom, and narrow-corridor maps, for 540
paired episode records. Isaac PhysX enhanced determinism is enabled, and every
method/map launch must finish in one successful startup attempt with a finite
serialized posterior and complete navigation trace.

The primary downstream gates are B8 success at least 90%, collision at most
5%, a positive B8-versus-B0 completion-time improvement CI and at least 90%
win rate. B8 must also be noninferior to B1 in success/collision, have mean
completion-time ratio at most 1.15 and bootstrap CI upper bound at most 1.25,
retain at least 80% valid observations, respond to aborts within 40 ms, and
produce zero serious events. Each interval uses 4,000 seed-level resamples.

The first 30-seed main run passed every gate except the narrow-corridor B8/B1
ratio CI (upper 1.2816 versus 1.25). The final 60-seed result is an independent,
powered replication with new seeds. Its controller is byte-identical to the
30-seed frozen controller, all effect/noninferiority/safety thresholds are
unchanged, and failed intervening controller changes remain disclosed in
`reports/p7_development_audit.md`.
