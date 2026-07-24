# Experiment registry

| ID | Phase | Frozen config | Artifact root | Status |
|---|---:|---|---|---|
| P1-SYNTHETIC | P1 | `configs/experiments/offline_baseline.yaml` | `evidence/p1_baseline/` | PASS as a software/component control; not real evidence |
| P3-PILOT-LEGACY | P3 | `configs/experiments/p3_synthetic_pilot.yaml` | `outputs/p3_pilot/` | Superseded; pooled statistic invalid |
| P3-METHOD-PILOT | P3 | `configs/experiments/p3_method_pilot.yaml` | `outputs/p3_method_pilot/` | Development-only; fixed the main protocol |
| P3-MAIN | P2/P3 | `configs/experiments/p3_synthetic_main.yaml` | `evidence/p3_main/` | **PASS:** 20 independent seeds, complete baselines/ablation, effect and dense gates pass |
| P1-REAL | P1 | `docs/p1_real_data_protocol.md` | `evidence/p1_real/` | **PASS:** 183/183 valid Go2 trials, complete native traceability, LOSO effects and rate sensitivity pass |

P3 main seeds are disjoint from all pilot seeds. P1-REAL is genuine Go2
LiDAR-odometry evidence and is not substituted with synthetic, retargeted, or
simulator data.
