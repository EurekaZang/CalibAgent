# ADR-001: Freeze public calibration contracts

- Status: Accepted
- Date: 2026-07-17
- Phase: P0

## Decision

`VelocityCommand`, `RobotContext`, `TrialObservation`,
`PredictiveDistribution`, and the four Protocols in
`calibagent.interfaces` are the stable integration surface. New optional fields
may be added with a schema-version bump. Existing meanings, array ordering
`[vx, vy, wz]`, timestamp semantics, and covariance units may not change
silently.

All execution backends must produce `RawTrialData`; only the shared measurement
pipeline may construct an online `TrialObservation`. Offline imported datasets
must round-trip through the same Parquet schema.

## Consequences

The algorithm package can be tested without Isaac Lab or ROS. Backend stubs
raise `NotImplementedError` rather than fabricate validation. A future schema
change requires an ADR, migration, and round-trip regression test.

