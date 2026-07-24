# P4 safety and stopping main report

**Verdict: GO.** The frozen P4 benchmark was generated from source commit
`0df7a25808a492ace563b68a8cf3e6c84daba269` and is stored under
`evidence/p4_main/`.

## Stopping result

| Metric | Result | Gate |
|---|---:|---:|
| Frozen active trajectories | 60/60 | complete |
| Premature-stop rate | 0.00% | <5% |
| Median extra trials after oracle target | 2 | ≤3 |
| p95 extra trials | 2 | ≤4 |

The oracle target is computed from frozen held-out RMSE and integrated
uncertainty. The runtime rule requires minimum coverage and two consecutive
validation/uncertainty confirmations; a low-gain signal cannot stop an
unvalidated run.

## Safety result

| Metric | Result | Gate |
|---|---:|---:|
| Hazard injections | 300 | complete |
| Hazard rejection | 100.00% | 100% |
| Expected reason-code coverage | 100.00% | 100% |
| Safe-control false rejection | 0.00% | 0% |
| Runtime fault cases | 160 | complete |
| Maximum abort-detection latency | 0 ms | ≤50 ms |
| Serious events | 0 | 0 |

The state-machine traces independently terminate in `done` for the happy path
and `abort` for the injected fault path. The live publication audit verifies
all artifact hashes and recomputes these metrics from CSV, rather than trusting
the summary JSON.

