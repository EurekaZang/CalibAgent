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
| P6-NO-GO-1 | P6 | commit `188cde3` | `outputs/p6_no_go_188cde3_consecutive_gate/` | **NO-GO:** physical scenario detection and full-win rates were 85% |
| P6-PILOTS | P6 | commits `4224340`–`41d62bc` | `outputs/p6_pilot_*` | Development-only; bounded shift stimulus and evidence-window semantics |
| P6-MAIN | P6 | `configs/experiments/p6_domain_shift_main.yaml` | `evidence/p6_main/` | **PASS:** 3 scenarios × 3 controls × 20 seeds; all detection, recovery, effect, budget, safety, and provenance gates pass |
| P7-MAIN-30 | P7 | commit `6d6537a` | `outputs/p7_main_no_go_6d6537a_corridor_variance/` | **NO-GO:** corridor B8/B1 CI upper 1.2816 exceeded 1.25; all other gates passed |
| P7-DEGRADED-PILOTS | P7 | commits `b01bdd7`, `1ef0cc9` | corresponding `outputs/p7_pilot_no_go_*` roots | **NO-GO:** persistent guard and recovery ramp reduced reliability; changes reverted |
| P7-MAIN-60 | P7 | `configs/experiments/p7_navigation_main.yaml` | `evidence/p7_main/` | **PASS:** 3 maps × 3 methods × 60 new seeds; all task, raw-effect, near-dense, budget, safety, runtime, and provenance gates pass |
| P6-STRONG-CONFIRM | P6 | `configs/experiments/p6_domain_shift_strong_confirmatory.yaml` | `evidence/p6_strong_confirmatory/` | **PASS:** 4 shifts × 3 controls × 72 paired seeds; active-over-passive early recovery, exact rate, terminal accuracy, safety, and provenance gates pass |
| P7-STRONG-CONFIRM-1 | P7 | `configs/experiments/p7_navigation_strong_confirmatory.yaml` | `evidence/p7_strong_confirmatory_failed/` | **NO-GO retained:** B8 success and raw/dense/matched navigation gate groups failed |
| P7-INTERLOCK-PILOTS | P7 | commits `70df308`–`e5f4cab` | development outputs only | Development-only: five registered settings diagnosed and corrected the high-rate base-height blind interval |
| P7-STRONG-CONFIRM-2 | P7 | `configs/experiments/p7_navigation_strong_confirmatory_v2.yaml` | `evidence/p7_strong_confirmatory_v2/` | **PASS:** 6 new maps × 7 controls × 72 new paired seeds; all 14 registered gate groups pass |

P3 main seeds are disjoint from all pilot seeds. P1-REAL is genuine Go2
LiDAR-odometry evidence and is not substituted with synthetic, retargeted, or
simulator data. P5 main seeds 5301–5320 and simulator seed 740240+ are disjoint
from the two completed development attempts. P5 is simulator evidence and is
not labeled as real-robot online evidence. P6 main seeds 6601–6620 are disjoint
from its pilots. P7 main seeds 8001–8060 are disjoint from the failed 30-seed
main and all pilots; its controller matches the frozen `6d6537a` controller.
P6/P7 are simulator evidence and are not labeled as P8 real-robot evidence.
P6 strong seeds 10101–10172 are disjoint from prior P6 development/main seeds.
P7 strong replication seeds 10501–10572 and all six replication maps are
disjoint from the failed confirmation. Git commit ancestry records failure,
controller correction, development pilots, protocol freeze, and replication;
no development result is pooled into the confirmatory estimates.
