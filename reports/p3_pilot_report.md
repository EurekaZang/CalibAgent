# P3 task-aware active-planning pilot report

**Corrected verdict (2026-07-18): diagnostic pilot only; P3 is not
phase-complete and is not publication-ready.**

- Execution date: 2026-07-17
- Frozen config hash: `49861a954796b740`
- Families: affine, deadzone/saturation, heteroscedastic
- Pilot seeds: 11, 23, 37, 53, 71
- Paired runs per comparison: 15
- Common safe seed design: 8 commands
- Maximum budget: 30 effective trials
- Target: RMSE <= 0.08 and integrated epistemic variance <= 0.02

## Original pooled result (not valid as the primary publication statistic)

| Comparison | Active trials | Baseline trials | Relative reduction | Paired trials saved (95% bootstrap CI) | One-sided Wilcoxon p |
|---|---:|---:|---:|---:|---:|
| Active vs LHS | 14.07 | 16.27 | 13.52% | 2.20 [1.13, 3.27] | 0.00219 |
| Active vs random | 14.07 | 16.67 | 15.60% | 2.60 [2.13, 3.13] | 0.000031 |
| Active vs Sobol | 14.07 | 16.07 | 12.45% | 2.00 [1.53, 2.47] | 0.000031 |

The original calculation treats `(family, seed)` as 15 independent units. That
assumption is invalid for this pilot: affine and deadzone conditions with the
same seed share latent mapping parameters, noise streams, selected commands and
uncertainty trajectories. Their trials-to-target vectors are duplicated.

## Independent-unit reanalysis

After averaging repeated family conditions within each seed, the independent
sample size is five:

| Comparison | Independent n | One-sided paired p | Verdict |
|---|---:|---:|---|
| Active vs LHS | 5 | 0.09375 | Not significant |
| Active vs random | 5 | 0.03125 | Diagnostic only; underpowered |
| Active vs Sobol | 5 | 0.03125 | Diagnostic only; underpowered |

The primary Active-vs-LHS completion gate therefore fails. The observed 13.52%
LHS reduction also remains below the project target of 30%.

## Uncertainty evidence

Final active 95% predictive coverage averaged 96.33% across all families and
seeds (range 92.45%-98.72%), inside the engineering target on average. The
representative uncertainty slice had Spearman correlation 0.576 between
epistemic variance and forward-error magnitude, supporting the G1 requirement
that uncertainty and error are positively associated. Coverage uses a fixed
noisy evaluation draw shared by all paired methods; RMSE uses the corresponding
noiseless mapping mean.

## Reproducibility and diagnostics

The suite records every command, posterior metric, chosen-candidate IV score,
and cost. It also writes the complete final candidate diagnostic table, a
serializable representative posterior, the resolved config, and a manifest.
Pilot and evaluation/task Sobol seeds are separate, and outcome targets never
enter the planner. The sample-efficiency curve and uncertainty/error heatmap are
rebuilt from CSV artifacts rather than manually edited.

The evidence is a synthetic P3 diagnostic pilot. It establishes planner
execution and artifact generation, not a statistically supported method
advantage, nor Isaac Lab, Go2, safety, stopping, domain shift, or navigation
performance. `paired_statistics.json` is retained for provenance but is
superseded for claim assessment by this correction and the readiness audit.
