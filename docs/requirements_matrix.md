# P0-P3 evidence matrix

| Phase / requirement | Software evidence | Phase/publication evidence | Status |
|---|---|---|---|
| P0 package, interfaces, backend seams | 47 tests, strict typing and lint pass | ADRs and fail-closed later-phase seams | PASS |
| P0 immutable provenance | Git commit and manifest checks | Both evidence manifests resolve to source commit `461d30b` | PASS |
| P0 environment/CI | Exact analysis/dev locks; actions pinned by SHA | Reproduction commands and artifact hashes frozen | PASS |
| P1 raw-to-observation processing | SE(2) dynamic-turn, empty input, gap and replay tests | 101-sample replay vertical slice passes | PASS for software path |
| P1 frozen acquisition design | Deterministic signed-axis/anchor/sentinel/LHS generator | 3 sessions, 183 planned trials, command-plan alignment enforced | PASS |
| P1 real Go2 dense replay | Raw ingestion, hashing and session-split tooling pass fixtures | At least 3 real sessions/150 valid trials required | **NO-GO: data absent** |
| P1 M0/M1 real improvement | Passive baseline implementation verified | M1 must improve over raw and M0 by at least 5% | **NO-GO: data absent** |
| P2 noise contract | Base noise plus heteroscedastic excess charged once | Generative/update variance check passes | PASS |
| P2 uncertainty calibration | Coverage and stratified audit executable | Overall 94.14%; family means 92.70%-95.12% | PASS |
| P3 candidate/task/IVR | Exact IVR, fantasy batch and D-opt tests pass | Complete main artifact has 420 unique rows | PASS |
| P3 sample efficiency | Seed-level statistics generated from raw metrics | 39.52% vs LHS, n=20, p=9.54e-7 | PASS |
| P3 strong controls | LHS/random/Sobol/D-opt/no-task/dense all implemented | Task ablation 27.27%; dense gap 6.90% | PASS |

## Current authoritative verdict

`calibagent-audit --workspace .` returns **NO_GO** solely because the three P1
real-data checks have no genuine input artifact. P0, P2, and P3 checks pass.
