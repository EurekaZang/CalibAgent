# P5 Isaac Lab main report

**Verdict: GO.** The final confirmation was generated from CalibAgent commit
`ceec54cfc5ff34482b1c724c2afa0687bbea4589`, Isaac Lab v2.3.2 commit
`37ddf626871758333d6ed89cf64ad702aef127d0`, and Isaac Sim
`5.1.0-rc.19+release.26219.9c81211b.gl` on an RTX 5090 with driver 580.173.02.

The main evidence contains four scenarios, 20 paired seeds per scenario, 12
active calibration trials per seed, eight fixed held-out commands, full 50 Hz
pose traces, simulator logs, distortion parameters, per-seed metrics, and
SHA-256 provenance.

## Main result

| Scenario | Tier | Calibration / validation valid | Actual motion | RMSE reduction | Paired improvement 95% CI | Win rate | Safety aborts / serious |
|---|---:|---:|---:|---:|---:|---:|---:|
| Affine distortion, flat | A | 93.75% / 96.25% | 87.66% | 30.03% | [0.04290, 0.04780] | 100% | 0 / 0 |
| Deadzone/saturation, flat | A | 98.33% / 100.00% | 95.00% | 31.70% | [0.04495, 0.05002] | 100% | 0 / 0 |
| Low friction + 2 kg + 2 cm COM | B | 100.00% / 100.00% | 100.00% | 9.30% | [0.00981, 0.01017] | 100% | 0 / 0 |
| Rough terrain + 1 kg + 1 cm COM | B | 96.25% / 81.25% | 100.00% | 17.85% | [0.01477, 0.01889] | 100% | 17 / 0 |

Worst-case gates are therefore: 9.30% RMSE reduction (required ≥5%), paired
CI lower bound 0.00981 (required >0), 93.75% calibration validity (required
≥85%), 81.25% validation validity (required ≥80%), and 87.66% actual motion
(required ≥85%).

All 17 rough-terrain envelope crossings were detected by the 50 Hz monitor and
the next recorded control cycle was zero, giving a maximum 20 ms response
against the 40 ms gate. No simulator termination, nonfinite trace, or serious
safety event occurred.

## Scope

This is a fixed-policy Isaac Lab/PhysX result. It demonstrates the complete
CalibAgent command-selection, safety, measurement, model-update, and held-out
evaluation loop under controllable and physical simulator variation. It is not
evidence of real-robot online active calibration or sim-to-real robustness.
Those claims require P6–P8 evidence.

