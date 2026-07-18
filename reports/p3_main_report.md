# P3 frozen synthetic main experiment

**Phase verdict: PASS for the frozen synthetic P3 claim. Overall P0-P3 ICRA
readiness remains NO-GO until the independent P1 real-data gates pass.**

The method-completeness pilot used only seeds 11, 23, 37, 53, and 71. It fixed
the six-axis warm start, task distribution, target thresholds, 160-trial final
evaluation budget, required baselines, and dense-oracle definition. The main
configuration was frozen locally at 2026-07-18 06:21:21 UTC before running the
20 disjoint main seeds 1001-1020. This is a locally time-ordered protocol lock,
not a claim of third-party preregistration.

Families use disjoint latent parameter seeds. Statistical inference aggregates
the three family conditions within each seed, so the independent sample size is
20 rather than the invalid pooled count of 60.

| Comparison | Active trials | Baseline trials | Reduction | One-sided paired p |
|---|---:|---:|---:|---:|
| LHS (primary) | 18.67 | 30.87 | 39.52% | 9.54e-7 |
| Random | 18.67 | 30.67 | 39.13% | 9.54e-7 |
| Sobol | 18.67 | 25.72 | 27.41% | 9.54e-7 |
| D-optimal | 18.67 | 23.00 | 18.84% | 9.54e-7 |
| Without task weighting | 18.67 | 25.67 | 27.27% | 9.54e-7 |

For the primary comparison, the seed-bootstrap 95% interval for trials saved is
[10.73, 13.73]. All 60 active repeated conditions and all passive conditions
reached the jointly frozen RMSE and epistemic-uncertainty target.

Mean final active RMSE is 0.008462 versus 0.007916 for the 256-command dense
oracle, a 6.90% gap below the 10% gate. Mean active 95% predictive coverage is
94.14%; family means are 95.12% affine, 92.70% deadzone, and 94.60%
heteroscedastic, all inside the frozen 90%-98% interval.

The run contains 420 unique `(family, method, seed)` summary rows and records
every sequential command. It includes LHS, random, Sobol, Bayesian D-optimal,
without-task-weight, and dense-oracle controls. The source commit is
`461d30ba0e785bd82b7a1e8713d602a6e61a0c03`; artifact hashes are frozen in
`reports/artifact_checksums.sha256`.

This report supports the P2 synthetic coverage and P3 synthetic
sample-efficiency claims. It does not substitute for Go2 measurements, Isaac
Lab, safety, stopping, domain shift, or navigation evidence.
