# P0-P7 evidence matrix

| Phase / requirement | Software evidence | Phase/publication evidence | Status |
|---|---|---|---|
| P0 package, interfaces, backend seams | 126 tests, 85.77% branch-aware coverage, strict typing and lint pass | ADRs and fail-closed external-runtime seams | PASS |
| P0 immutable provenance | Git commit, manifest and source-archive checks | P1 real evidence resolves to `100fe68`; existing P1 synthetic/P3 manifests resolve to `461d30b` | PASS |
| P0 environment/CI | Exact analysis/dev locks; actions pinned by SHA | Reproduction commands and artifact hashes frozen | PASS |
| P1 raw-to-observation processing | SE(2) dynamic-turn, empty input, gap and replay tests | 101-sample replay vertical slice passes | PASS for software path |
| P1 frozen acquisition design | Deterministic signed-axis/anchor/sentinel/LHS generator | 3 sessions, 183 planned trials, command-plan alignment enforced | PASS |
| P1 real Go2 dense replay | Fixed-horizon SE(2) steady check, fail-closed delivery verifier and native-attempt trace tests pass | 183/183 valid trials, 3 sessions, 100% plan completion/match, 183/183 native traces | PASS |
| P1 M0/M1 real improvement | Leave-one-session-out passive evaluation with all-fold enforcement | M1 improves 54.45% vs raw and 34.07% vs M0; weakest fold 51.55%/30.08% | PASS |
| P1 sampling-rate sensitivity | Even/odd half-rate decimation is executable and hash-bound | 183/183 valid in both ≈10 Hz views; max velocity RMSE to 20 Hz is 0.00497; effects remain 54.30%/33.92% or better | PASS |
| P2 noise contract | Base noise plus heteroscedastic excess charged once | Generative/update variance check passes | PASS |
| P2 uncertainty calibration | Coverage and stratified audit executable | Overall 94.14%; family means 92.70%-95.12% | PASS |
| P3 candidate/task/IVR | Exact IVR, fantasy batch and D-opt tests pass | Complete main artifact has 420 unique rows | PASS |
| P3 sample efficiency | Seed-level statistics generated from raw metrics | 39.52% vs LHS, n=20, p=9.54e-7 | PASS |
| P3 strong controls | LHS/random/Sobol/D-opt/no-task/dense all implemented | Task ablation 27.27%; dense gap 6.90% | PASS |
| P4 validation-gated stopping | Confirmation/patience/budget unit tests and frozen P3 trace replay | 60/60 runs; 0% premature; median/p95 extra trials 2/2 | PASS |
| P4 hard safety and runtime state machine | Fail-closed command/state rules, immediate abort, legal-transition tests | 300/300 hazards rejected, 0 safe false rejection, 160/160 runtime faults detected, 0 serious events | PASS |
| P5 pinned simulator/runtime | Isaac Lab v2.3.2 commit, Isaac Sim 5.1, PhysX, official Go2 policies and SHA-256 locks | Manifest verifies 38/38 artifacts and both policy hashes | PASS |
| P5 Tier-A/Tier-B coverage | Vectorized distortion library and deterministic physical event configuration | 2 Tier-A + 2 Tier-B scenarios, 20 paired seeds/scenario, 4/4 finite pose traces | PASS |
| P5 calibration effect | M2 identity-structured BLR, active IVR, fixed 8-command holdout, paired bootstrap | Worst RMSE reduction 9.30%; worst 95% CI lower bound 0.00981; win rate 100% in all scenarios | PASS |
| P5 safety under physics | P4 envelope prefilters and post-checks candidates; 50 Hz runtime monitor | 17 timely aborts, maximum response 20 ms, 0 simulator terminations/serious events | PASS |
| P6 pinned simulated shift runtime | Frozen Isaac/PhysX/policy/config locks; in-place material/mass/COM event audit | 116/116 artifacts hash-valid; three shift identities and all event deltas match | PASS |
| P6 detection and recovery | Bounded-evidence detector, posterior inflation, frozen/passive/full controls | 3 scenarios × 3 methods × 20 seeds; detection/recovery 100%; p95 delays 4.0/7.1 trials | PASS |
| P6 adaptation effect and safety | Seed-paired 4,000-sample bootstrap; full compressed trace audit | Worst effect CI lower 0.04454; 228 timely envelope aborts across controls, max 20 ms, 0 serious events | PASS |
| P7 fixed-planner navigation | Planner hash, enhanced determinism, B0/B1/B8 isolation and serialized posteriors | 3 maps × 3 methods × 60 seeds = 540 episodes; all launches single-attempt | PASS |
| P7 downstream task effect | Seed-paired success/collision/time and 4,000-sample bootstrap recomputation | B8 success 100%, collision 0%; worst B8-vs-B0 CI lower 38.69 s | PASS |
| P7 near-dense and budget | B1=30 trials, B8=12; identical planner and policy | B8/B1 mean ratio ≤1.0446, worst CI upper 1.1236, budget ratio 0.40 | PASS |
| P6 strong confirmation | Four held-out shifts, frozen/passive/full controls, exact rate intervals, early active-vs-passive endpoint | 4 × 72 paired seeds; early-effect CI lower bounds 0.00537–0.01536; detection lower bound ≥0.925; terminal CI upper ≤0.12564 | **PASS** |
| P6 strong trace/provenance | Independent raw recomputation and hash-bound full-resolution trace scan | 158/158 source artifacts, 12/12 pose traces, max abort latency 20 ms, 0 serious events | **PASS** |
| P7 first strong confirmation | Six maps, seven controls, 72 paired seeds; failure retained without pooling | B8 success fell to 50/72 on loaded arc; four primary gate groups failed | **NO-GO retained** |
| P7 strong disjoint replication | Six new maps, seven controls, 72 new paired seeds; exact and paired-bootstrap inference | B8 success ≥70/72, collision 0/72, worst dense/matched time CI upper 1.074/1.090 | **PASS** |
| P7 strong trace/provenance | Independent raw recomputation, one-launch/posterior checks and full trace scan | 566/566 source artifacts, 42/42 navigation traces, 3,024 episode records, 0 serious events | **PASS** |
| P8 online real Go2 | `Go2RosBackend` remains an intentional fail-closed placeholder; the data protocol and code map are specified in `docs/p8_go2_real_deployment_data_handoff_zh.md` and `docs/p8_go2_implementation_guide_zh.md`; the historical P1 ROS runner is versioned as implementation reference | No completed backend/watchdog/P8 runner or confirmatory online calibration, real navigation, or real shift-recovery bundle exists yet | **PENDING** |

## Current authoritative verdict

`calibagent-audit --workspace . --require-ready` returns **GO** with 39/39
checks passing. This verdict applies to the frozen claim boundary stated in
`README.md`; it does not promote P8 or real-robot online P3–P7 claims.

`calibagent-audit-strong --workspace . --require-ready` separately returns
**GO** with 12/12 checks for the stronger P6/P7 simulator claim. With the
supplemental output trees mounted, `--raw` repeats the full 1.06 GB
trajectory/hash audit. This stronger verdict does not alter the real-hardware
claim boundary.
