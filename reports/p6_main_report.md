# P6 simulated domain-shift main report

**Verdict: GO.** The frozen confirmation was generated from CalibAgent commit
`23571b347ae344a0019093342d828d4be5e3fb30`, Isaac Lab v2.3.2 commit
`37ddf626871758333d6ed89cf64ad702aef127d0`, Isaac Sim
`5.1.0-rc.19+release.26219.9c81211b.gl`, PhysX, and the SHA-256-pinned official
Go2 flat-policy checkpoint.

The evidence contains three in-place shift scenarios, frozen/passive/full
controls, 20 paired seeds per method and scenario, 12 recovery trials against a
30-trial dense budget, full 50 Hz pose traces, method-level raw metrics,
simulator logs, applied shift events, and 116 hash-bound artifacts.

## Main result

| Shift scenario | Detection / p95 delay | Full recovery / p95 trials | Full − frozen final RMSE improvement, 95% CI | Win rate | Valid ratio | Aborts / serious |
|---|---:|---:|---:|---:|---:|---:|
| Gain and coupling | 100% / 4.0 | 100% / 6.1 | 0.06308 [0.06043, 0.06598] | 100% | 99.11% | 0 / 0 |
| Friction + 3 kg + 3 cm COM + gain | 100% / 2.15 | 100% / 6.0 | 0.05253 [0.04454, 0.05983] | 100% | 90.89% | 205 / 0 |
| Mixed context and physics | 100% / 2.0 | 100% / 7.1 | 0.07654 [0.07483, 0.07824] | 100% | 98.33% | 23 / 0 |

No pre-shift false alarm occurred. Detection and full recovery are 100% in all
three scenarios. Every 4,000-resample paired confidence interval is strictly
positive, and the 12/30 recovery-to-dense budget ratio is exactly 0.40.

The 228 safety aborts are aggregate events across all three controls, not
serious events. They occur under the two physical-shift scenarios, respond at
the 50 Hz monitor cadence (maximum 20 ms), and are fully represented in the
compressed traces. The independent audit verifies next-cycle zero response or,
for a final-sample event, a right-censored safe reset at the following trial.
There are no simulator terminations or serious safety events.

## Scope

P6 demonstrates detection and recovery from controlled in-place domain shifts
inside pinned Isaac Lab. It does not establish sim-to-real robustness or online
real-Go2 safety. Those require the P8 hardware protocol.
