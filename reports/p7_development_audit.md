# P7 development-attempt audit

All P7 pilot and failed-main directories remain under `outputs/`; none are
pooled with the independent 60-seed confirmation. The sequence below records
the consequential failures and corrections rather than presenting only the
successful endpoint.

| Attempt / commit | Outcome | Diagnosis |
|---|---|---|
| Early pilots through `d2449a4` | Mixed NO-GO/diagnostic GO | Exposed model-prior bias, inverse-sign errors, task-domain mismatch, dead zones, and corridor noninferiority failures |
| `p7_main_no_go_d0f5b7d_open_tail_reliability` | **NO-GO** | B8 near-dense gate failed; max B8/B1 CI upper 1.6245 and mean ratio 1.2687 |
| `p7_pilot_go_0fb04e6_feedback_no_delay` | Pilot GO | Bounded velocity feedback closed long-tail tracking, but startup safety was not yet robust |
| `p7_main_no_go_3b18e07_corridor_feedback_safety` | **NO-GO** | Minimum B8 success 83.33%; task, raw-effect, and near-dense gates failed |
| `65c9d7b` recovery-reengagement pilot | **NO-GO** | Delaying feedback after recovery retained success but widened near-dense CI to 1.5899 |
| `0f8cce9` absolute-height guard pilot | **NO-GO** | Guard over-triggered; minimum B8 success fell to 60% |
| `5e34389` guard-before-slew pilot | **NO-GO** | Success recovered to 95%, but near-dense CI upper remained 1.2715 |
| `50c2cb4` predictive guard after slew | Pilot GO | Correct guard ordering produced 100% minimum B8 success and zero collision |
| `p7_main_no_go_6d6537a_corridor_variance` | **NO-GO**, 30 seeds | Every gate except near-dense passed; corridor mean ratio 1.0952 passed, but CI upper 1.2816 exceeded 1.25 |
| `b01bdd7` persistent-guard pilot | **NO-GO** | Minimum B8 success regressed to 85% |
| `1ef0cc9` recovery-ramp pilot | **NO-GO** | Minimum B8 success 90%, but near-dense CI upper 1.3084 |
| `d988774` independent powered replication | **GO**, 60 new seeds | Restored the unchanged `6d6537a` controller and passed all 11 P7 gates |

The final replication did not select the better of multiple runs at the same
sample size. It followed a failed 30-seed main whose only failure was interval
width, used disjoint seeds, doubled the predeclared independent sample count,
and kept the controller and all substantive thresholds fixed. Intervening
degraded controller variants are retained and reported as NO-GO.
