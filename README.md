# CalibAgent

[English](README.md) | [简体中文](README_zh-CN.md)

[![Software CI](https://github.com/EurekaZang/CalibAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/EurekaZang/CalibAgent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.12-3776AB)
![License](https://img.shields.io/badge/License-MIT-2F855A)
![Scoped publication audit](https://img.shields.io/badge/P0--P7%20scoped%20audit-GO-1F883D)

**Safe, uncertainty-aware active velocity calibration for quadruped robots.**

CalibAgent is the research codebase for an ICRA-targeted study of how a
quadruped can select a small number of safe velocity commands, learn its
command-to-motion map, quantify epistemic uncertainty, and use the calibrated
model for navigation and post-shift recovery.

> **ICRA readiness: GO for the frozen P0–P7 claim set.**
> **Strong P6/P7 simulator readiness: GO.** The first strong P7 confirmation
> failed and remains part of the evidence record; the positive navigation
> claim rests only on the later disjoint replication. CalibAgent does **not**
> claim that P3–P7 have been executed online on a real Go2 or that sim-to-real
> robustness has been established. **Real-robot online active calibration
> remains P8.**

<p align="center">
  <img src="docs/assets/readme/p7_slalom_seed_8006.png"
       alt="A paired Isaac Lab slalom episode in which raw control stalls and twelve-trial active calibration reaches the goal region."
       width="900">
</p>

<p align="center">
  <em>Illustrative paired P7 episode (seed 8006), not the aggregate statistical
  result. B0 raw control times out; B8 enters the goal region after 12
  calibration trials. The map, trajectories, and
  <a href="scripts/build_readme_figures.py">figure script</a> are versioned.</em>
</p>

## Abstract

Velocity commands on a legged robot are not executed exactly: actuator
dynamics, learned locomotion policies, terrain, payload, and saturation create
a context-dependent mapping from commanded body velocity
`u = (vx, vy, wz)` to measured velocity `y`. CalibAgent treats this mismatch as
a sequential experimental-design problem. A Bayesian basis model estimates
the mapping and its predictive uncertainty; a task-weighted integrated
variance reduction planner chooses informative commands; non-learned safety
filters and validation-gated stopping constrain execution.

The frozen evidence spans synthetic studies, 183 passive Unitree Go2 trials,
fault injection, and pinned Isaac Lab/PhysX experiments. In the synthetic main
study, active calibration used 39.52% fewer trials than LHS to reach the joint
accuracy-and-uncertainty target. In strong simulator confirmation, active
recovery improved early post-shift error over passive updating across four
held-out shifts. A prospectively frozen navigation replication evaluated
3,024 episodes on six new maps: B8 achieved at least 70/72 successes per map,
zero collisions, and registered noninferiority to dense and matched-budget
controls. These findings are simulator-scoped unless explicitly identified as
real Go2 replay evidence.

## Research question

> Can a quadruped identify a task-relevant command-to-motion model with fewer
> safe trials than passive designs, while preserving calibrated uncertainty,
> bounded stopping behavior, adaptation after domain shift, and downstream
> navigation performance?

CalibAgent decomposes this question into a staged evidence program:

- **P0–P1:** define portable interfaces and validate passive calibration on
  real Go2/LiDAR-odometry data;
- **P2–P3:** test uncertainty calibration and task-aware active design under
  controlled synthetic mappings;
- **P4:** verify stopping and fail-closed safety independently of the learned
  model;
- **P5–P7:** evaluate the complete loop, shift recovery, and fixed-planner
  navigation in a pinned simulator;
- **P8:** conduct online real-Go2 confirmation under the frozen hardware
  protocol.

## Method

```mermaid
flowchart LR
    T["Task distribution"] --> P["Safe candidate pool"]
    M["Bayesian command-to-motion model"] --> A["Task-weighted IVR planner"]
    P --> A
    A --> S["Non-learned safety filter"]
    S --> B["RobotBackend<br/>Isaac Lab · replay · Go2 (P8)"]
    B --> R["Raw pose / command / health streams"]
    R --> O["SE(2) measurement pipeline"]
    O --> M
    M --> C["Validation + uncertainty stopping"]
    C -->|continue| A
    C -->|accept| I["Inverse compensation"]
    I --> N["Fixed-planner navigation"]
    O --> D["Shift detector"]
    D -->|latched shift| X["Posterior inflation + active recovery"]
    X --> A
```

The numerical core imports neither Isaac Lab nor ROS 2. All environments
implement the same `RobotBackend`/`RawTrialData` contract, and the shared
measurement pipeline produces a `TrialObservation` before any model update.
This ports-and-adapters boundary separates algorithmic claims from simulator
or robot integration.

### Main components

1. **Uncertainty-aware model.** M2 is a Bayesian basis model with
   cross-axis, hinge, and interaction terms, a serializable posterior, and
   predictive epistemic variance.
2. **Task-aware acquisition.** The planner minimizes integrated posterior
   variance over a declared task-command distribution. Random, LHS, Sobol,
   Bayesian D-optimal, no-task, and dense controls are implemented under
   matched data-access rules.
3. **Independent safety layer.** A hard command/state envelope filters every
   candidate. The runtime state machine latches aborts and commands zero
   velocity without delegating safety to the learned model.
4. **Shift response.** Bounded evidence accumulation detects persistent
   changes, inflates stale posterior certainty, and allocates a fixed active
   recovery budget.
5. **Downstream evaluation.** Calibration methods are compared with identical
   waypoint planners, maps, policies, physics, seeds, and safety limits.

## Evidence and principal results

| Stage | Design and independent unit | Principal frozen result | Claim boundary |
|---|---|---|---|
| **P1 real replay** | 183 valid Go2 trials; three acquisition sessions; leave-one-session-out evaluation | M1 reduced pooled RMSE by **54.45% vs. raw** and **34.07% vs. M0** | Passive offline calibration on one robot/date/environment |
| **P2–P3 synthetic** | 20 independent seeds; three repeated distortion families; six acquisition controls | Active reached the joint target in 18.67 trials vs. 30.87 for LHS, a **39.52% reduction** (`p = 9.54e-7`) | Controlled synthetic mappings |
| **P4 safety/stopping** | 60 stopping trajectories, 300 hazards, 160 runtime faults | 0% premature stops; median/p95 excess trials 2/2; 100% hazard rejection; **0 serious events** | Replay and fault-injection evidence |
| **P5 closed loop** | Four Isaac Lab scenarios × 20 paired seeds; 12 active trials | Worst scenario RMSE reduction **9.30%**; all paired CI lower bounds positive; maximum abort response 20 ms | Pinned Isaac Lab/PhysX and official Go2 policies |
| **P6 strong shift** | Four held-out shifts × 72 paired seeds × frozen/passive/full | Passive-minus-full early RMSE CI lower bounds **0.00537–0.01536**; terminal RMSE CI upper ≤ 0.12564; **0 serious events** | Registered simulator shifts; no terminal superiority claim over passive |
| **P7 strong navigation** | Six new maps × 72 paired seeds × seven methods = **3,024 episodes** | Minimum B8 success **70/72**; collisions **0/72** on every map; worst dense/matched time-ratio CI upper **1.074/1.090** | Positive claim comes only from the disjoint replication |

The detailed evidence map is in
[`docs/requirements_matrix.md`](docs/requirements_matrix.md). Full numerical
results, estimands, intervals, and limitations are reported in
[`reports/`](reports/).

## Simulator results

### Sample efficiency and model uncertainty

<p align="center">
  <img src="evidence/p3_main/sample_efficiency.png"
       alt="Task-weighted RMSE and epistemic variance versus effective calibration trials for active and passive acquisition methods."
       width="900">
</p>

The task-weighted active method reaches the registered joint target earlier
than the passive designs. The right panel shows the corresponding reduction in
integrated epistemic variance. Inference uses the 20 independent seeds, not the
60 repeated seed-by-family conditions.

### Shift recovery and downstream navigation

<table>
  <tr>
    <td width="50%">
      <img src="reports/figures/p6_strong_confirmatory.png"
           alt="Strong P6 active recovery effects and terminal RMSE with 95 percent bootstrap intervals.">
    </td>
    <td width="50%">
      <img src="reports/figures/p7_strong_confirmatory_v2.png"
           alt="Strong P7 navigation success intervals and paired completion-time noninferiority results.">
    </td>
  </tr>
  <tr>
    <td><strong>P6.</strong> Full active recovery improves the registered early
      window over passive updating and remains below the absolute terminal
      RMSE gate.</td>
    <td><strong>P7.</strong> The disjoint replication passes exact success and
      collision gates and paired completion-time noninferiority gates.</td>
  </tr>
</table>

The first strong P7 confirmation failed and remains in
[`evidence/p7_strong_confirmatory_failed/`](evidence/p7_strong_confirmatory_failed/).
The successful result uses new maps, new seeds, and a prospectively frozen
protocol; failed and development runs are not pooled into the positive
estimate.

## Publication-integrity design

- **Protocol isolation:** development and confirmation seeds are disjoint;
  task commands and held-out evaluation commands use separate fixed seeds.
- **Correct statistical unit:** paired simulator seed is the independent unit;
  repeated scenarios or maps are not treated as independent replicates.
- **Endpoint discipline:** downstream navigation endpoints cannot be rescued
  by a favorable calibration diagnostic.
- **Failure retention:** failed confirmation and corrective pilots remain
  versioned and are excluded from confirmatory estimates.
- **Executable audit:** publication checks recompute statistics and verify
  hashes, manifests, runtime locks, trace coverage, safety response, and Git
  ancestry without trusting a producer-written `GO` field.
- **Claim separation:** software CI, simulator readiness, real-data replay, and
  online hardware confirmation are distinct gates.

See the frozen
[`experiment protocol`](docs/experiment_protocol.md),
[`strong-confirmatory protocol`](docs/p6_p7_strong_confirmatory_protocol.md),
and
[`completion semantics`](docs/completion_semantics.md).

## Reproduce the audited package

### 1. Install

```bash
git clone https://github.com/EurekaZang/CalibAgent.git
cd CalibAgent
python -m venv .venv
.venv/bin/pip install \
  -r env/analysis/requirements.lock.txt \
  -r env/analysis/requirements-dev.lock.txt
.venv/bin/pip install --no-deps -e .
```

### 2. Run software and publication gates

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/pytest -p pytest_cov --cov=calibagent
.venv/bin/ruff check .
.venv/bin/mypy src/calibagent
.venv/bin/calibagent-audit --workspace . --require-ready
.venv/bin/calibagent-audit-strong --workspace . --require-ready
./scripts/audit_source_delivery.sh
```

With the 1.06 GB supplemental trajectory trees mounted:

```bash
.venv/bin/calibagent-audit-strong \
  --workspace . --raw --require-ready
```

### 3. Rebuild README figures

```bash
.venv/bin/python -m calibagent.cli.build_figures \
  --registry evidence/p3_main/trial_trace.csv \
  --output evidence/p3_main/sample_efficiency.png \
  --uncertainty-slice evidence/p3_main/uncertainty_slice.csv
.venv/bin/python scripts/build_readme_figures.py
```

P5–P7 reproduction additionally requires the pinned Isaac Lab v2.3.2/Isaac
Sim runtime and official Unitree Go2 policy checkpoints. Commands and runtime
locks are listed in
[`docs/experiment_registry.md`](docs/experiment_registry.md).

## Repository structure

| Path | Purpose |
|---|---|
| [`src/calibagent/core/`](src/calibagent/core/) | Bayesian models, active planners, stopping, safety, shift detection |
| [`src/calibagent/interfaces/`](src/calibagent/interfaces/) | Backend-independent data and execution contracts |
| [`src/calibagent/backends/`](src/calibagent/backends/) | Replay, Isaac Lab, and fail-closed Go2 adapters |
| [`src/calibagent/eval/`](src/calibagent/eval/) | Frozen benchmark and publication-audit implementations |
| [`configs/experiments/`](configs/experiments/) | Versioned development and confirmatory protocols |
| [`evidence/`](evidence/) | Compact, hash-bound evidence required by live audits |
| [`reports/`](reports/) | Phase reports, audit records, and publication figures |
| [`docs/`](docs/) | Architecture decisions, protocols, claim matrix, and hardware handoff |
| [`tests/`](tests/) | Unit, integration, regression, and governance tests |

## Real-robot P8

P1 provides real Go2 passive-replay evidence, but the online P8 boundary is
still open. `Go2RosBackend` intentionally fails closed until its ROS 2/Unitree
implementation, independent watchdog, P8-NAV/P8-SHIFT runners, and hardware
gates are complete.

Hardware collaborators should start with:

- the
  [Go2 implementation and simulator-code guide](docs/p8_go2_implementation_guide_zh.md);
- the
  [complete real-robot experiment and data handoff](docs/p8_go2_real_deployment_data_handoff_zh.md).

## Data and provenance

Regenerable outputs are gitignored. Frozen compact evidence is versioned under
`evidence/`; manifests bind artifacts to source commits, configurations,
runtime versions, policy hashes, and the supplemental full-resolution traces.
Dense-oracle evaluation points never fit the model, planner, or feature
scaling. See [`docs/experiment_protocol.md`](docs/experiment_protocol.md) for
the data-access rules.

## Citation

The manuscript citation will be added when the public preprint is released.
Until then, cite the repository version used in your work:

```bibtex
@software{calibagent_2026,
  author  = {{CalibAgent contributors}},
  title   = {CalibAgent: Safe and Uncertainty-Aware Active Velocity
             Calibration for Quadruped Robots},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/EurekaZang/CalibAgent}
}
```

## License

CalibAgent is released under the [MIT License](LICENSE).
