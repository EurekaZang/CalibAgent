# P0-P3 evidence matrix

Status is reported at three separate levels. See `completion_semantics.md`.
Presence of an implementation is not evidence that a phase or publication claim
has passed.

| Phase / requirement | Implementation | Software evidence | Phase evidence | Publication status |
|---|---|---|---|---|
| P0 package/src layout and interfaces | Present | Import, JSON, shape, typing tests pass | ADRs present | **NO_GO:** workspace is not versioned |
| P0 backend seams | Present | Component tests pass | Isaac/Go2 intentionally deferred | **NO_GO:** replay vertical slice fails common measurement pipeline |
| P0 manifests/environment/CI | Present | Hash/config tests and local CI commands pass | Manifests exist | **NO_GO:** `UNVERSIONED_WORKTREE`, floating CI dependencies, no observed remote CI |
| P1 converter/Parquet schema | Present | Round-trip and CSV conversion tests pass | Synthetic data only | **NO_GO:** real dense-data evidence absent |
| P1 measurement pipeline | Present | Static-yaw and timestamp-gap tests pass | Dynamic SE(2), bootstrap covariance, empty input not validated | **NO_GO** |
| P1 offline replay | Present | Nearest/consume methods tested | Backend emits two samples and measurement rejects them; baseline bypasses backend | **NO_GO** |
| P1 M0/M1 and passive samplers | Present | Formula/coupling/sampler tests pass | One synthetic affine dataset and one split | **NO_GO:** no real-data result or repeated synthetic seeds |
| P2 minimal M2 basis BLR | Present | Closed-form, PSD, serialization, hypothetical update pass | Synthetic affine coverage gate passes | Conditional only |
| P2 uncertainty calibration | Present | Coverage metric tested | Mean pilot coverage 96.33% | **NO_GO:** generative and update noise contracts double-count variance |
| P3 candidate pool/task/IVR | Present | Formula, weighting, cost, symmetry, batch tests pass | Planner component is credible | Conditional only |
| P3 sample-efficiency claim | Present | Benchmark smoke test passes | Independent seed reanalysis: Active vs LHS `p=0.09375`; only 5 seeds | **NO_GO** |
| P3 strong baselines/ablations | Partial | Random/LHS/Sobol run | D-opt, dense oracle, without-task-weight absent | **NO_GO** |
| P3 target effect | Measured | Raw metrics/checksums valid | 13.52% vs LHS | **NO_GO:** below 30% target |

## Current authoritative verdict

```bash
python -m calibagent.cli.audit_readiness --workspace .
```

Expected verdict on 2026-07-18: `NO_GO`. The prior “Passed” entries were removed
because they conflated L0/L1 implementation evidence with L2/L3 scientific
evidence.

