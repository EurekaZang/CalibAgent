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

## Development pilot log

The first interlock pilot (`outputs/p7_navigation_interlock_pilot`) was stopped
after B0 and B1 on the first pressure map. It eliminated hard-envelope aborts
but latched for almost the entire episode: B1 success was 0/16 and the B1
interlock was active for 47,127 sample-environment steps. Inspection of the
original traces showed that the stable loaded Go2 base-height median is only
0.170–0.175 m, so the initial 0.20/0.23 m activation/release thresholds were
physically invalid. This pilot is a failed development result, not evidence.

The second development setting is based on the observed working-height and
per-sample drop distributions. It activates the absolute latch at 0.158 m,
releases at 0.165 m, and otherwise relies on a five-sample projection toward a
0.152 m protected height. The hard 0.150 m envelope is unchanged.

That second pilot removed every navigation hard-envelope abort on the
loaded-arc pressure map, but remained `NO_GO`: B8 completed 11/16 episodes,
with 5,951 interlocked sample-environment steps and 274 emergency recoveries.
The failure mode changed from unsafe termination to excessive safe-stop
dwell. The third setting therefore narrows the latch to 0.155/0.160 m, uses a
three-sample projection toward 0.151 m, and restores planner emergency
activation to 0.155 m. The hard safety limit remains unchanged.

The third pilot improved loaded-arc B8 from 11/16 to 15/16 and reduced mean
completion time from 48.06 s to 38.50 s. Its sole B8 failure on loaded-arc and
sole B8 failure on dual-gate were timely height aborts. The fourth and final
threshold pilot changes only the projection horizon from three to five 20 ms
samples while retaining the short 0.155/0.160 m latch. If it fails, the next
step is a control-structure revision rather than further threshold search.

The fourth pilot achieved 16/16 B8 success on asymmetric-corridor and
loaded-arc, including zero B8 navigation aborts on loaded-arc, but retained one
dual-gate B8 height abort. The fifth development run is a larger 32-seed
factor-combination check on new development seeds: it combines the safe
0.158 m activation identified by v2 with the efficient 0.160 m release and
five-sample prediction identified by v4. No other controller or statistical
setting changes. This is the final threshold-development run.

The fifth pilot passed every registered development gate on all three maps
with 32 new seeds per map. B8 completed 96/96 episodes with zero collisions
and zero serious events. The largest B8/dense completion-time ratio CI upper
bound was 1.028; all four matched-control time and paired success/collision
noninferiority gates passed. This development result authorizes freezing a
new, disjoint confirmatory replication, but is not itself publication
confirmation.

## Prospective replication outcome

Commit `2a25201` subsequently froze six new maps and 72 new seeds
(10501–10572) before the replication was run. None of those maps or seeds
overlap the failed confirmation. The replication passed all 14 registered gate
groups: minimum B8 success was 70/72, all B8 collision counts were zero, the
worst B8/dense completion-time ratio CI upper bound was 1.074, the worst
matched-budget upper bound was 1.090, and serious events were zero.

The failure above remains the first confirmatory result. The final positive
claim is explicitly based on the later disjoint replication; development
pilots are not pooled into either confirmatory estimate. See
`reports/p7_strong_confirmatory_v2_report.md`.
