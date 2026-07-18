# Experiment registry

| ID | Phase | Frozen config | Artifact root | Status |
|---|---:|---|---|---|
| P1-OFFLINE | P1 | `configs/experiments/offline_baseline.yaml` | `outputs/p1_baseline/` | L1 only: synthetic component gate; end-to-end replay and robot data fail |
| P3-PILOT | P3 | `configs/experiments/p3_synthetic_pilot.yaml` | `outputs/p3_pilot/` | L1 only: pooled pilot statistic invalid for primary LHS claim |

The source workspace contained no dense robot dataset. P1 therefore provides a
tested converter and replay implementation but does not invent a real-data
result. The synthetic replay report is the P1 numerical gate, and the synthetic
known-truth pilot is the authoritative P2/P3 numerical gate.
