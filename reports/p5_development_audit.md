# P5 development-attempt audit

This record prevents failed attempts from disappearing behind the final GO.
Neither completed development attempt is pooled with the final confirmation.

## Attempt 1 — commit `1d82dc9`

The weak `prior_scale=1.0` M2 model overfit the 12-trial calibration set.

| Scenario | RMSE reduction | CI lower | Calibration / validation valid | Outcome |
|---|---:|---:|---:|---|
| Tier-A affine | 9.74% | -0.00232 | 99.58% / 98.12% | CI failed |
| Tier-A deadzone | 2.65% | -0.01285 | 99.17% / 99.38% | effect and CI failed |
| Tier-B friction/payload | -192.43% | -0.19533 | 100% / 100% | severe model degradation |
| Tier-B rough | -4.30% | -0.00866 | 90.42% / 89.38% | effect and CI failed |

Diagnosis also found that the Go2 task had disabled its inherited COM event, so
the declared COM offset was not actually applied. The revision introduced a
strong identity-structured prior, an explicit startup COM event, and independent
confirmation seeds.

## Attempt 2 — commit `4d38e1d`

All four effect and CI gates passed after regularization and COM enforcement,
but rough-terrain calibration validity was 73.33% (required 85%). The active
planner repeatedly ranked coupled high-linear/high-yaw candidates near the
flat-terrain envelope boundary. There were 41 timely safety aborts and zero
serious events.

The final protocol prefilters the planning pool with a stricter coupled-load
boundary while retaining the post-planner hard filter. Final seeds 5301–5320
and simulator seed 740240+ are disjoint from both completed attempts.

## Launcher-only failure — commit `40666f8`

No metrics or validation artifacts were generated. IVR was incorrectly asked
for 128 non-duplicate candidates although duplicate-distance exclusion left
fewer than 128. The correction prefilters the pool and requests only the top 12
safe candidates. The unseen final seeds were then rerun from commit `ceec54c`.

