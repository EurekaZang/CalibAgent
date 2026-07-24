# Experiment registry

| ID | Phase | Frozen config | Artifact root | Status |
|---|---:|---|---|---|
| P1-SYNTHETIC | P1 | `configs/experiments/offline_baseline.yaml` | `evidence/p1_baseline/` | PASS as a software/component control; not real evidence |
| P3-PILOT-LEGACY | P3 | `configs/experiments/p3_synthetic_pilot.yaml` | `outputs/p3_pilot/` | Superseded; pooled statistic invalid |
| P3-METHOD-PILOT | P3 | `configs/experiments/p3_method_pilot.yaml` | `outputs/p3_method_pilot/` | Development-only; fixed the main protocol |
| P3-MAIN | P2/P3 | `configs/experiments/p3_synthetic_main.yaml` | `evidence/p3_main/` | **PASS:** 20 independent seeds, complete baselines/ablation, effect and dense gates pass |
| P1-REAL | P1 | `docs/p1_real_data_protocol.md` | `evidence/p1_real/` | **PASS:** 183/183 valid Go2 trials, complete native traceability, LOSO effects and rate sensitivity pass |
| P4-MAIN | P4 | `configs/experiments/p4_safety_stop_main.yaml` | `evidence/p4_main/` | **PASS:** stopping, fault injection, abort latency, and runtime state-machine gates pass |
| P5-ATTEMPT-1 | P5 | frozen at commit `1d82dc9` | development output only | **NO-GO:** weak prior overfit; all failed effects retained in `reports/p5_development_audit.md` |
| P5-ATTEMPT-2 | P5 | frozen at commit `4d38e1d` | development output only | **NO-GO:** effects passed, but rough-terrain calibration validity was 73.33% |
| P5-LAUNCH-FAIL | P5 | commit `40666f8` | development log only | No scientific result; candidate request exhausted unique pool before artifact generation |
| P5-MAIN | P5 | `configs/experiments/p5_isaaclab_main.yaml` | `evidence/p5_main/` | **PASS:** four scenarios × 20 independent paired seeds; all effect, validity, safety, runtime, and provenance gates pass |

P3 main seeds are disjoint from all pilot seeds. P1-REAL is genuine Go2
LiDAR-odometry evidence and is not substituted with synthetic, retargeted, or
simulator data. P5 main seeds 5301–5320 and simulator seed 740240+ are disjoint
from the two completed development attempts. P5 is simulator evidence and is
not labeled as real-robot online evidence.
