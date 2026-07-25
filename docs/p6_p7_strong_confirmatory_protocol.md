# P6/P7 strong confirmatory protocol

Status: frozen before confirmatory execution. Development outputs under
`outputs/p6_strong_pilot*` and `outputs/p7_strong_pilot/` are not publication
evidence and must not be pooled with the confirmatory runs.

## Claim boundary

The confirmatory experiments support only the following simulator claims:

1. P6 task-aware active adaptation lowers early post-shift prediction error
   relative to a fixed passive design, while recovering below the declared
   absolute accuracy threshold within at most 40% of the dense budget.
2. P7 calibration with 12 task-aware active trials is noninferior on downstream
   navigation to a 30-trial dense design and four budget-matched 12-trial
   controls under the same planner, compensator, locomotion policy and safety
   logic.

P6 does not claim lower terminal RMSE than the passive control. P7 does not
claim that task weighting beats every calibration design on every map.
Calibration-validation RMSE is reported as a diagnostic rather than substituted
for the downstream navigation endpoint. Neither phase is real-robot evidence.

## Development/confirmation separation

- P6 development seeds are 9101–9108. Confirmatory seeds are 10101–10172.
- P7 development seeds are 9301–9308. Confirmatory seeds are 10201–10272.
- P6 confirmatory physics settings and post-shift distortion draws are disjoint
  from P6-MAIN and the strong pilot.
- All six P7 confirmatory map geometries and physics contexts are disjoint from
  P7-MAIN and the four-map strong pilot.
- Confirmatory configs are source-versioned before execution. A failed
  confirmatory run is retained and registered; gates, methods and maps are not
  changed after looking at its outcomes.

The initially frozen configs are:

- `configs/experiments/p6_domain_shift_strong_confirmatory.yaml`
- `configs/experiments/p7_navigation_strong_confirmatory.yaml`

The first P7 strong confirmation completed as `NO_GO` and remains frozen under
`evidence/p7_strong_confirmatory_failed/`. Its failure was traced to a
planner-rate height guard that could not intercept fast drops between 10 Hz
ticks. Five registered development pilots introduced and stress-tested a 50 Hz
predictive zero-command interlock. The final 32-seed development pilot passed
all gates on all three previously failed pressure maps.

The prospective P7 replication is frozen separately as:

- `configs/experiments/p7_navigation_strong_confirmatory_v2.yaml`

It uses 72 new seeds (10501–10572), a new simulator seed, and six new map
geometries/physics contexts. No first-confirmation or pilot record may be
pooled with this replication. The same P7 endpoints, methods, 1.25 time-ratio
margin, 0.05 success/collision margins and exact-rate bounds remain unchanged.

## P6 primary analysis

The independent unit is a simulator seed within a declared shift scenario.
There are four scenarios and 72 paired seeds per scenario. Frozen, passive and
full methods receive the same pre-shift data, shift, monitoring commands,
validation commands and random seed.

The primary recovery endpoint for each method/seed is the arithmetic mean of
rolling validation RMSE from recovery trials 4 through 9. Trial 4 is the first
complete four-command validation window; trial 9 is 30% of the 30-trial dense
budget. If a complete window is unavailable because of an invalid observation,
that seed remains in the paired analysis and receives the preregistered
conservative RMSE penalty of 0.25. No seed is silently dropped or interpolated.

For every scenario:

- the paired effect is `passive early RMSE - full early RMSE`;
- its 95% interval is a deterministic 4,000-resample paired bootstrap;
- the one-sided Wilcoxon alternative is `full < passive`;
- the lower interval bound must exceed zero and \(p \le 0.01\).

Terminal full RMSE is an absolute accuracy endpoint: the upper 95% bootstrap
bound of its seed mean must be at most 0.140. Full-versus-passive terminal
differences remain reported but are not a superiority gate.

Detection, recovery and no-shift false-alarm rates are gated both by point
estimates and two-sided 95% Clopper–Pearson bounds. With 72/72 successes or
0/72 events, the relevant exact bound is strictly inside 0.95/0.05. Detection
and recovery lower bounds must be at least 0.90; the false-alarm upper bound
must be at most 0.05.

## P7 controls and primary analysis

Each of six held-out maps uses 72 paired seeds. The method set is fixed:

| Method | Calibration design | Trials |
|---|---|---:|
| B0 | Raw identity prior | 0 |
| B1 | Dense safe design | 30 |
| B2 | Safe-snapped Latin hypercube | 12 |
| B3 | Safe-snapped Sobol | 12 |
| B4 | Bayesian D-optimal | 12 |
| B5 | Active IVR without task weighting | 12 |
| B8 | Task-weighted active IVR | 12 |

All methods use the identical waypoint planner, inverse compensator, outer
velocity feedback, locomotion checkpoint, safety envelope, map geometry and
episode seeds. Only the calibration observations and resulting posterior differ.

The primary endpoint is downstream navigation. Per map:

- B8 success must be at least 95%, with exact 95% lower bound at least 90%;
- B8 collision must be at most 5%, with exact 95% upper bound at most 5%;
- B8 must improve completion time over B0 with a positive paired 95% interval;
- B8 must be noninferior to B1 and every budget-matched method in paired
  success/collision, using margins of 0.05;
- the upper paired bootstrap bound of the B8 completion-time ratio must be at
  most 1.25 for B1 and every budget-matched method;
- the B8/B1 calibration-budget ratio must be at most 0.40.

Eight commands that are absent from the planner task support form a held-out
calibration-validation diagnostic. Per-seed RMSE and paired comparisons are
saved for every method. These diagnostics are reported in the paper but are not
used to override a failed navigation endpoint or to assert universal
task-weighting superiority.

## Safety, provenance and failure policy

- Isaac Lab v2.3.2, Isaac Sim 5.1 and the official Go2 flat-policy checkpoint
  are pinned by commit/version/hash.
- PhysX enhanced determinism is required for P7.
- Every process writes its resolved launch config, simulator log, raw trace,
  per-seed metrics and posterior where applicable.
- A startup retry is allowed only before any scientific artifact exists.
- Serious safety events must be zero. Maximum abort latency is 40 ms.
- Output roots are write-once. Existing non-empty output causes failure.
- Manifests hash every scientific artifact and record the source commit.
- A producer summary alone is insufficient: publication readiness requires a
  separate raw-table recomputation and manifest/hash audit.
