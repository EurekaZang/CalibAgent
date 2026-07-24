# CalibAgent

![ICRA readiness](https://img.shields.io/badge/ICRA%20readiness-GO-1f883d)

**ICRA readiness: GO for the frozen P0–P5 claim set.** The executable audit
passes all 29 software, real-data, statistical, safety, simulator, provenance,
and reproducibility checks. P1 is supported by 183 traceable Unitree Go2
trials; P4 by 60 stopping trajectories and 460 fault/runtime cases; P5 by four
pinned Isaac Lab scenarios with 20 paired seeds each.

CalibAgent is a simulator-agnostic reference implementation of safe,
uncertainty-aware active calibration for the mapping from quadruped velocity
commands `(vx, vy, wz)` to measured body velocity.

This repository implements the P0–P5 engineering prototype defined by
`CalibAgent_工程实现与仿真实验计划_v0.1.docx`:

- frozen interfaces, manifests, architecture decisions, CI, and backend seams;
- offline replay, data conversion, passive M0/M1 models, and grid/random/LHS/Sobol baselines;
- the M2 Bayesian basis model with serializable posterior and predictive uncertainty;
- task-aware integrated-variance planning, candidate diagnostics, and greedy fantasy batches;
- a D-optimal strong baseline, without-task-weight ablation, and dense oracle;
- a raw Go2 trial ingestion path with SE(2) processing, hashes, and session-isolated evaluation.
- a fail-closed safety filter, runtime state machine, immediate abort path, and
  validation/uncertainty-gated stopping rule;
- a vectorized Isaac Lab/PhysX Go2 closed loop with Tier-A command distortion,
  Tier-B friction/payload/COM/terrain variation, fixed published policies, and
  paired bootstrap statistics.

ROS 2 online execution, sim-to-real domain shift, and real-robot online active
calibration remain later phases (P6–P8). Their boundaries are not promoted by
the P0–P5 verdict.

## Reproduce

```bash
python -m venv .venv
.venv/bin/pip install -r env/analysis/requirements.lock.txt \
  -r env/analysis/requirements-dev.lock.txt
.venv/bin/pip install --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -p pytest_cov --cov=calibagent
.venv/bin/python -m calibagent.cli.audit_readiness --workspace . --require-ready
.venv/bin/calibagent-p1-plan \
  --config configs/experiments/p1_go2_capture.yaml \
  --output outputs/p1_capture/plan.csv
.venv/bin/python -m calibagent.cli.run_benchmark \
  --config configs/experiments/p3_synthetic_main.yaml
.venv/bin/python -m calibagent.cli.run_p4_benchmark \
  --config configs/experiments/p4_safety_stop_main.yaml
.venv/bin/python -m calibagent.cli.build_figures \
  --registry outputs/p3_main/trial_trace.csv \
  --output outputs/p3_main/sample_efficiency.png \
  --uncertainty-slice outputs/p3_main/uncertainty_slice.csv
```

P5 additionally requires the pinned Isaac Lab/Isaac Sim runtime and official
policy checkpoints:

```bash
.venv/bin/python -m calibagent.cli.run_p5_isaaclab \
  --config configs/experiments/p5_isaaclab_main.yaml \
  --isaaclab-root /path/to/IsaacLab-v2.3.2
```

The benchmarks write resolved configurations, run-level metrics, trial/pose
traces, paired statistics, simulator logs, and manifests. See
[`docs/requirements_matrix.md`](docs/requirements_matrix.md) for phase-level
evidence and [`docs/experiment_protocol.md`](docs/experiment_protocol.md) for
the evaluation protocol and its corrected statistical-unit warning.

Software CI and publication readiness are separate gates. See
[`docs/completion_semantics.md`](docs/completion_semantics.md) and the
[`2026-07-24 P0–P5 ICRA audit`](docs/audits/icra_p0_p5_2026-07-24.md).
The corrected main result is in [`reports/p3_main_report.md`](reports/p3_main_report.md),
the real Go2 result is in [`reports/p1_real_report.md`](reports/p1_real_report.md),
the safety/stopping result is in [`reports/p4_main_report.md`](reports/p4_main_report.md),
the simulator result is in [`reports/p5_main_report.md`](reports/p5_main_report.md),
and acquisition requirements are in
[`docs/p1_real_data_protocol.md`](docs/p1_real_data_protocol.md).

## Claim boundary

The GO verdict is deliberately scoped. P1 demonstrates passive, offline
full-affine calibration on real Go2/LiDAR-odometry trials. P3 demonstrates the
active planner under the frozen synthetic benchmark. P4 demonstrates stopping
and safety logic through frozen replay and fault injection. P5 demonstrates the
active closed loop in pinned Isaac Lab simulation. It does **not** claim that
P3–P5 have been executed online on a real Go2, that sim-to-real/domain-shift
robustness is established, or that the simulator result replaces hardware
validation.

## Quick API

```python
from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.task import TaskDistribution
from calibagent.core.planning.ivr import IntegratedVariancePlanner

transformer = BasisTransformer("m2_affine_cross_hinge").fit(command_reference)
model = BayesianBasisModel(transformer, prior_scale=1.0, noise_variance=[0.01] * 3)
task = TaskDistribution.uniform(task_commands)
candidate = IntegratedVariancePlanner().propose(model, task, history=[])[0]
```

## Data policy

Dense-oracle evaluation points are never used to fit the model, tune the
planner, or fit feature scaling. Development and final confirmation seeds are
disjoint and recorded in manifests/reports. Regenerable outputs are
intentionally gitignored. Frozen P3, P4, and P5 evidence is stored under
`evidence/p3_main/`, `evidence/p4_main/`, and `evidence/p5_main/`. The
self-contained P1 evidence bundle is under `evidence/p1_real/`; every frozen
artifact is hash-checked by the live audit.
