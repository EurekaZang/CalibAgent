# CalibAgent

![ICRA readiness](https://img.shields.io/badge/ICRA%20readiness-GO-1f883d)

**ICRA readiness: GO for the frozen P0–P3 claim set.** The executable audit
passes all 19 software, real-data, statistical, provenance, and reproducibility
checks. P1 is supported by 183 traceable Unitree Go2 trials across three
leave-one-session-out folds; P2 and P3 retain their frozen synthetic scope.

CalibAgent is a simulator-agnostic reference implementation of safe,
uncertainty-aware active calibration for the mapping from quadruped velocity
commands `(vx, vy, wz)` to measured body velocity.

This repository implements the P0–P3 engineering prototype defined by
`CalibAgent_工程实现与仿真实验计划_v0.1.docx`:

- frozen interfaces, manifests, architecture decisions, CI, and backend seams;
- offline replay, data conversion, passive M0/M1 models, and grid/random/LHS/Sobol baselines;
- the M2 Bayesian basis model with serializable posterior and predictive uncertainty;
- task-aware integrated-variance planning, candidate diagnostics, and greedy fantasy batches;
- a D-optimal strong baseline, without-task-weight ablation, and dense oracle;
- a raw Go2 trial ingestion path with SE(2) processing, hashes, and session-isolated evaluation.

Isaac Lab, ROS 2, safety supervision, stopping, and domain-shift adaptation are
explicitly later phases (P4–P8). Their backend boundaries exist here without
pretending that hardware or simulator integration has been validated.

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
.venv/bin/python -m calibagent.cli.build_figures \
  --registry outputs/p3_main/trial_trace.csv \
  --output outputs/p3_main/sample_efficiency.png \
  --uncertainty-slice outputs/p3_main/uncertainty_slice.csv
```

The benchmark writes a resolved configuration, run-level metrics, trial traces,
seed-level paired statistics, and a manifest under `outputs/p3_main/`. See
[`docs/requirements_matrix.md`](docs/requirements_matrix.md) for phase-level
evidence and [`docs/experiment_protocol.md`](docs/experiment_protocol.md) for
the evaluation protocol and its corrected statistical-unit warning.

Software CI and publication readiness are separate gates. See
[`docs/completion_semantics.md`](docs/completion_semantics.md) and the
[`2026-07-24 ICRA audit`](docs/audits/icra_p0_p3_2026-07-24.md).
The corrected main result is in [`reports/p3_main_report.md`](reports/p3_main_report.md),
the real Go2 result is in [`reports/p1_real_report.md`](reports/p1_real_report.md),
and acquisition requirements are in
[`docs/p1_real_data_protocol.md`](docs/p1_real_data_protocol.md).

## Claim boundary

The GO verdict is deliberately scoped. P1 demonstrates passive, offline
full-affine calibration on real Go2/LiDAR-odometry trials. P3 demonstrates the
active planner under the frozen synthetic benchmark. It does **not** claim that
P3 has been executed online on a real Go2; that stronger claim belongs to a
later, separately audited phase.

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
in every manifest. Regenerable outputs are intentionally gitignored; frozen P3
evidence is stored under `evidence/p3_main/`. The self-contained, versioned P1
evidence bundle is under `evidence/p1_real/`; its source archive and every
derived artifact are hash-checked by the live audit.
