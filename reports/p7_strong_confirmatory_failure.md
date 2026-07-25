# P7 first strong-confirmatory result: NO_GO

## Frozen outcome

The preregistered run used six held-out maps, 72 paired seeds per map and seven
calibration methods. It completed once from source commit `8f3c256` with the
frozen config
`configs/experiments/p7_navigation_strong_confirmatory.yaml`. Four primary
gate groups failed:

- B8 task success and its exact confidence bounds;
- B8-over-raw on every required endpoint;
- B8 near-dense noninferiority on every map;
- matched-control navigation noninferiority.

Budget, map and seed identity, same-planner identity, finite computation,
valid-observation coverage and the zero-serious-event gate passed.

## Strongest counterexamples

| Map | B8 success | Exact 95% CI | B8 collision | Relevant time-ratio failure |
|---|---:|---:|---:|---|
| `confirm_asymmetric_corridor` | 1.000 | [0.950, 1.000] | 0.000 | LHS upper 1.347; Sobol upper 1.277 |
| `confirm_dual_gate` | 0.944 | [0.864, 0.985] | 0.000 | LHS upper 1.282; D-opt upper 1.294 |
| `confirm_loaded_arc` | 0.694 | [0.575, 0.798] | 0.000 | LHS upper 1.282 |

No post-hoc threshold change is accepted. Calibration-validation RMSE cannot
override the failed downstream endpoint.

## Trace-level diagnosis

The failed dual-gate and loaded-arc episodes terminate predominantly through
the hard base-height envelope, not collision. The planner-rate height guard is
evaluated at 10 Hz and, even while active, permits 0.24–0.28 m/s commands. In
representative failed seeds, base height falls from roughly 0.17 m to below the
0.15 m hard limit within 60–80 ms, before the next planner decision. Recovery
also disables outer velocity feedback for 2 s, amplifying method-dependent
recovery counts into completion-time differences.

The corrective development hypothesis is therefore registered as:

1. add a 50 Hz predictive base-height interlock with a zero-command latch and
   release hysteresis;
2. activate planner derating and emergency recovery earlier;
3. shorten only the post-recovery feedback reengagement delay;
4. preserve the 0.15 m hard safety limit and all serious-event gates.

The failed confirmatory maps may be used only as development pressure tests.
A positive publication claim requires a subsequently frozen run on new maps,
physics contexts and seeds.
