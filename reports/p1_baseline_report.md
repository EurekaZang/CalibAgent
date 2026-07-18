# P1 synthetic component baseline report

**Corrected verdict (2026-07-18): L1 software evidence only; P1 is not phase-complete.**

- Execution date: 2026-07-17
- Backend: canonical Parquet offline replay
- Split: session-grouped, 400 training rows / 100 validation rows
- Held-out session: `p1-session-2`
- Sampling budget: 30 observations, except the 400-row dense reference
- Mapping: seeded synthetic affine distortion with cross-axis coupling

## Results

| Sampler | M0 RMSE | M1 RMSE | M1 reduction vs raw command |
|---|---:|---:|---:|
| Grid | 0.06083 | 0.02716 | 82.19% |
| Random | 0.04838 | 0.02796 | 81.66% |
| LHS | 0.04816 | 0.02747 | 81.98% |
| Sobol | 0.04904 | 0.02737 | 82.05% |
| Dense (400) | 0.04861 | 0.02638 | 82.70% |

The uncalibrated raw-command RMSE was 0.15244. Under LHS sampling, the M1
full-coupling model reduced RMSE by 42.97% relative to M0, verifying that the
P1 implementation captures the injected cross-axis mapping. The 30-sample M1
methods were within 3.0-6.0% of the dense M1 RMSE.

The validation session was never used for feature fitting, model fitting, or
sampler selection. Invalid observations are excluded before the split is
consumed. `split.json`, the run manifest, canonical input Parquet, and exact
metrics remain under `outputs/p1_baseline/`; hashes are frozen in
`reports/artifact_checksums.sha256`.

## Claim boundary

This is a known synthetic component gate, not a Go2 result. The supplied
workspace contained no existing robot dense dataset. The baseline runner also
consumes `TrialObservation` directly; it does not exercise the
`OfflineReplayBackend -> MeasurementPipeline -> model` vertical slice. That
backend currently emits two samples and the measurement pipeline rejects the
result. Consequently this report must not be cited as evidence that P1 is
complete or that the common backend architecture has been validated.
