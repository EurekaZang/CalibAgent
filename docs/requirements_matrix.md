# P0-P3 evidence matrix

| Phase / requirement | Software evidence | Phase/publication evidence | Status |
|---|---|---|---|
| P0 package, interfaces, backend seams | 59 tests, 85.93% branch-aware coverage, strict typing and lint pass | ADRs and fail-closed later-phase seams | PASS |
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

## Current authoritative verdict

`calibagent-audit --workspace . --require-ready` returns **GO** with 19/19
checks passing. This verdict applies to the frozen claim boundary stated in
`README.md`; it does not promote later P4–P8 or real-robot online P3 claims.
