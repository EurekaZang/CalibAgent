# P1–P3 experiment protocol

## Questions and preregistered comparisons

P1 checks whether M1 captures cross-axis structure missed by M0 under identical
train/validation splits. P2 checks posterior correctness and 95% interval
coverage against known synthetic truth. P3 checks whether task-weighted exact
integrated variance reduction lowers trials-to-target relative to LHS and
random sampling.

The primary P3 endpoint is the first effective trial satisfying both frozen
task-weighted RMSE and integrated epistemic-variance thresholds. A run that does
not reach the target is assigned `max_trials + 1`; it is not dropped. In the
current pilot, families with the same seed share latent mapping parameters, so
the conservative independent unit is `seed`; family is a repeated condition,
not an independent replicate. Main experiments must either generate independent
family-specific distortion seeds or use a hierarchical/repeated-measures model.
The report includes a one-sided paired test and a bootstrap interval for trials
saved. Because the configured five seeds are a pilot, p-values are diagnostic
rather than the final paper claim.

## Isolation

- task and evaluation points use disjoint fixed Sobol seeds;
- mappings and noise use the same seeds across methods;
- every method receives the same eight safe seed-design commands;
- the feature standardizer sees candidate commands but no output;
- evaluation truth is called only after a posterior update and never returned
  to the planner;
- thresholds and the pilot seed list are frozen before execution.

## Outputs

`trial_trace.csv` contains every selected command and post-update metric.
`metrics.csv` contains one row per condition and seed. The original
`paired_statistics.json` pools `(family, seed)` and is retained as a raw pilot
artifact, but it is not valid publication evidence for the primary LHS claim.
`manifest.json` and `resolved_config.json` record the attempted execution
identity; manifests with `UNVERSIONED_WORKTREE` do not prove reproducibility.
`build_figures` regenerates the curve from the trace.
