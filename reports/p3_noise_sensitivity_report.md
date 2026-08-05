# P3 candidate-noise sensitivity report

## Purpose

The registered P3 planner ranks candidates using the frozen per-axis process
variance and adds each trial's measured excess covariance to the Bayesian
update after execution.  This supplemental experiment tests the strongest
alternative: in the heteroscedastic family only, an oracle supplies the exact
candidate-dependent excess variance before selection.  The oracle arm is a
sensitivity ceiling, not a replacement for the registered method.

## Design

- Family: heteroscedastic synthetic distortion.
- Independent unit: seed; 20 seeds (1001--1020).
- Methods: registered task IVR, oracle noise-aware task IVR, LHS, D-optimal,
  and active IVR without task weights.
- Common warm start: six trials; maximum budget: 160 trials.
- Frozen joint target: task-weighted RMSE at most 0.04 and integrated epistemic
  variance at most 0.0015.
- Candidate, task, and evaluation grids and all random seeds match P3.

## Results

| Method | Trials to target | RMSE at crossing | Integrated variance at crossing | 95% coverage at crossing |
|---|---:|---:|---:|---:|
| Registered task IVR | **20.0** | 0.02332 | 0.001426 | 0.9420 |
| Oracle noise-aware task IVR | 21.0 | **0.02320** | 0.001425 | 0.9398 |
| D-optimal | 31.0 | 0.02035 | 0.001302 | 0.9483 |
| No-task IVR | 31.0 | 0.02271 | 0.001384 | 0.9458 |
| LHS | 36.9 | 0.02235 | 0.001444 | 0.9469 |

The oracle candidate-noise term changes the task-IVR crossing time by one
trial and reduces crossing RMSE by 0.00012.  Both task-weighted variants retain
an 11-trial advantage over D-optimal and no-task IVR; the registered variant
saves 16.9 trials over LHS (paired 95% bootstrap interval [15.05, 18.90]).
Thus, candidate-dependent noise changes the selected design slightly but does
not explain the registered ranking or sample-efficiency result.

## Interpretation boundary

Equation (4) in the paper is exact conditional on the variance supplied to the
design update.  The registered implementation supplies the frozen process
variance because a future real-trial covariance is unavailable before
execution; the realized covariance is still used in the posterior update.  If
a candidate-noise predictor is available, the implemented planner now accepts
its nonnegative per-candidate variance and evaluates the fully conditional
denominator.  The oracle result above establishes sensitivity under known
heteroscedastic variance; it is not a claim that real candidate variances are
known exactly.

## Reproduce

```bash
.venv/bin/calibagent-benchmark \
  --config configs/experiments/p3_noise_sensitivity.yaml
```

The compact evidence bundle is `evidence/p3_noise_sensitivity/` and records
source commit `fbefc8d83cedb183147d7cb94bcabea33a2058f8`.
