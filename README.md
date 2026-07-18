# CalibAgent

![ICRA readiness](https://img.shields.io/badge/ICRA%20readiness-NO--GO-b42318)

**ICRA readiness: NO-GO.** The code is a software-verified research prototype;
its phase evidence and publication claims have not passed the independent audit.

CalibAgent is a simulator-agnostic reference implementation of safe,
uncertainty-aware active calibration for the mapping from quadruped velocity
commands `(vx, vy, wz)` to measured body velocity.

This repository implements the P0–P3 engineering prototype defined by
`CalibAgent_工程实现与仿真实验计划_v0.1.docx`:

- frozen interfaces, manifests, architecture decisions, CI, and backend seams;
- offline replay, data conversion, passive M0/M1 models, and grid/random/LHS/Sobol baselines;
- the M2 Bayesian basis model with serializable posterior and predictive uncertainty;
- task-aware integrated-variance planning, candidate diagnostics, and greedy fantasy batches.

Isaac Lab, ROS 2, safety supervision, stopping, and domain-shift adaptation are
explicitly later phases (P4–P8). Their backend boundaries exist here without
pretending that hardware or simulator integration has been validated.

## Reproduce

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -p pytest_cov --cov=calibagent
.venv/bin/python -m calibagent.cli.audit_readiness --workspace .
.venv/bin/python -m calibagent.cli.run_benchmark \
  --config configs/experiments/p3_synthetic_pilot.yaml
.venv/bin/python -m calibagent.cli.build_figures \
  --registry outputs/p3_pilot/trial_trace.csv \
  --output outputs/p3_pilot/sample_efficiency.png \
  --uncertainty-slice outputs/p3_pilot/uncertainty_slice.csv
```

The benchmark writes a resolved configuration, run-level metrics, trial traces,
paired statistics, and a manifest under `outputs/p3_pilot/`. See
[`docs/requirements_matrix.md`](docs/requirements_matrix.md) for phase-level
evidence and [`docs/experiment_protocol.md`](docs/experiment_protocol.md) for
the evaluation protocol and its corrected statistical-unit warning.

Software CI and publication readiness are separate gates. See
[`docs/completion_semantics.md`](docs/completion_semantics.md) and the
[`2026-07-18 ICRA audit`](docs/audits/icra_p0_p3_2026-07-18.md).

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
planner, or fit feature scaling. Pilot and main seeds are disjoint and recorded
in every manifest. Raw outputs are intentionally gitignored; compact frozen
P3 evidence is stored in `reports/` after verification.
