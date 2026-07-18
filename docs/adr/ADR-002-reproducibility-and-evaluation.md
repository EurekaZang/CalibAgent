# ADR-002: Freeze provenance and leakage boundaries

- Status: Accepted
- Date: 2026-07-17
- Phase: P0

## Decision

Every run records a canonical configuration hash, code revision (or explicit
`UNVERSIONED_WORKTREE`), all named seeds, backend/model/planner identifiers, and
relative artifact paths. Resolved configuration is written beside the manifest.

Feature scaling is fitted only on a predeclared command-space reference.
Task-grid commands and weights are visible to the active planner; evaluation
targets are not. Pilot seeds are frozen in configuration and excluded from all
future main experiments. Active and passive methods share distortion,
observation-noise, task-grid, evaluation-grid, and seed design.

## Consequences

Dense-oracle data is evaluation-only. It cannot initialize priors, choose the
feature set, tune target thresholds, or provide candidate outcomes. Statistical
comparisons are paired by distortion family and seed.

