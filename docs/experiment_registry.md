# Experiment registry

| ID | Phase | Frozen config | Artifact root | Status |
|---|---:|---|---|---|
| P1-SYNTHETIC | P1 | `configs/experiments/offline_baseline.yaml` | `outputs/p1_baseline/` | PASS as a software/component control; not real evidence |
| P3-PILOT-LEGACY | P3 | `configs/experiments/p3_synthetic_pilot.yaml` | `outputs/p3_pilot/` | Superseded; pooled statistic invalid |
| P3-METHOD-PILOT | P3 | `configs/experiments/p3_method_pilot.yaml` | `outputs/p3_method_pilot/` | Development-only; fixed the main protocol |
| P3-MAIN | P2/P3 | `configs/experiments/p3_synthetic_main.yaml` | `outputs/p3_main/` | **PASS:** 20 independent seeds, complete baselines/ablation, effect and dense gates pass |
| P1-REAL | P1 | `docs/p1_real_data_protocol.md` | `outputs/p1_real/` | **PENDING:** genuine Go2 raw trials are not present |

P3 main seeds are disjoint from all pilot seeds. P1-REAL is deliberately not
substituted with synthetic, retargeted, or simulator data.
