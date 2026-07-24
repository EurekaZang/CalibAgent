# P6 development-attempt audit

P6 development outputs are retained under `outputs/` and excluded from the
frozen main inference. This record prevents pilot selection from being mistaken
for the main result.

| Attempt | Outcome | What it established |
|---|---|---|
| `p6_failed_launcher_6f5eaf8` | Infrastructure failure; no aggregate summary | Initial launcher did not produce a scientific result |
| `p6_incomplete_dual_scene_0090891` | Incomplete | Relaunching separate pre/post scenes could not prove an in-place shift |
| `p6_pilot_weak_shift_0b11fc9` and `p6_failed_weak_shift_pre_188cde3` | Development-only / failed | Weak shifts did not reliably exercise the detector |
| `p6_no_go_188cde3_consecutive_gate` | **NO-GO** | Physical scenario detection was 85% and full-versus-frozen win rate 85%; detection/effect gates failed |
| `p6_pilot_gainstep_full_hysteresis` | Pilot only, 5 seeds | Bounded evidence window removed false alarms; detection/recovery both 100% |
| `p6_pilot_gainstep_physical_full` | Pilot only, 5 seeds | Physical shift detected/recovered; 13 non-serious envelope aborts exposed the safety regime |
| `p6_pilot_gainstep_mixed_full` | Pilot only, 5 seeds | Mixed shift detected/recovered; 4 non-serious envelope aborts |
| `p6_regression_failed_seeds_full` | Targeted regression, 3 seeds | Former physical failure seeds recovered; not used as publication evidence |
| `p6_main` | **GO**, independent seeds 6601–6620 | All 12 frozen publication gates pass |

The correction changed the shift stimulus and evidence-window semantics before
freezing the final confirmation. It did not waive failed detections, count a
launcher failure as a result, or pool pilot seeds with main seeds.
