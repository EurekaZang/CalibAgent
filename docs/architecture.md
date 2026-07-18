# P0 architecture freeze

CalibAgent follows a ports-and-adapters boundary. The pure Python package under
`src/calibagent/core` owns numerical models and experiment design. It imports
neither Isaac Lab, ROS 2, nor Unitree SDK. `RobotBackend` is the single execution
port, and every backend returns the same `RawTrialData` contract. The shared
measurement pipeline turns raw time series into `TrialObservation` before any
model sees the data.

The P0–P3 data flow is:

```text
candidate pool / passive sampler
             |
             v
      RobotBackend port  ----> RawTrialData
             |                       |
             |                       v
             |              MeasurementPipeline
             |                       |
             +----------------> TrialObservation
                                     |
                                     v
                    M0/M1 fit or M2 Bayesian update
                                     |
                   +-----------------+------------------+
                   v                                    v
          evaluation grid                    IV-reduction planner
          (targets isolated)                 (commands/weights only)
```

The synthetic benchmark samples a known mapping directly but still creates the
same `TrialObservation` object. This is a formula-level test tier, not evidence
of Isaac Lab or robot validity.

## Dependency rules

- `interfaces` depends only on the standard library and NumPy data types.
- `core` may depend on interfaces, NumPy, and SciPy, never a backend.
- `measurement` depends on interfaces and NumPy.
- `backends` adapt external systems; stubs fail closed until their phase.
- `eval` consumes public model/planner APIs and never mutates algorithms.
- all experiment differences are configuration values, not copied constants.

Public contracts are frozen in ADR-001. Provenance and evaluation isolation are
frozen in ADR-002.

