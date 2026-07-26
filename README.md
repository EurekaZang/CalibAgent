# CalibAgent

![ICRA readiness](https://img.shields.io/badge/ICRA%20readiness-GO-1f883d)

**ICRA readiness: GO for the frozen P0–P7 claim set.** The executable audit
passes all 39 software, real-data, statistical, safety, simulator, provenance,
and reproducibility checks. P1 is supported by 183 traceable Unitree Go2
trials; P4 by 60 stopping trajectories and 460 fault/runtime cases; P5 by four
pinned Isaac Lab scenarios with 20 paired seeds each; P6 by three domain-shift
scenarios with three controls and 20 seeds each; and P7 by three navigation
maps, three methods, and 60 seeds per map.

**Strong P6/P7 simulator readiness: GO (12/12 independent checks).** The
strong-confirmatory extension raises P6 to four shifts × 72 seeds × three
controls and P7 to six new maps × 72 seeds × seven controls. It retains the
first failed P7 confirmation and bases the positive P7 claim only on a later,
disjoint, prospectively frozen replication. Full-source audits verify 158/158
P6 and 566/566 P7 artifacts, including every full-resolution trajectory.

CalibAgent is a simulator-agnostic reference implementation of safe,
uncertainty-aware active calibration for the mapping from quadruped velocity
commands `(vx, vy, wz)` to measured body velocity.

This repository implements the frozen P0–P7 engineering and evaluation stack
derived from
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
- an online shift detector with frozen/passive/full controls, bounded posterior
  inflation and active recovery under in-place gain/friction/payload/COM shifts;
- a fixed-planner navigation evaluation comparing raw B0, dense B1, and
  budgeted active B8 calibration against LHS, Sobol, D-optimal, and no-task
  matched-budget controls on held-out navigation maps.
- an independent strong-confirmatory audit that recomputes paired statistics,
  exact rate intervals, trace safety, source hashes, and failed-to-replication
  provenance without trusting the producer's `GO` field.

Real-robot online active calibration remains P8. P6 and P7 establish
domain-shift recovery and downstream navigation only in the pinned simulator;
they are not promoted as sim-to-real or real-hardware results.

## Reproduce

```bash
python -m venv .venv
.venv/bin/pip install -r env/analysis/requirements.lock.txt \
  -r env/analysis/requirements-dev.lock.txt
.venv/bin/pip install --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -p pytest_cov --cov=calibagent
.venv/bin/python -m calibagent.cli.audit_readiness --workspace . --require-ready
.venv/bin/python -m calibagent.cli.audit_strong_readiness \
  --workspace . --require-ready
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

P5–P7 additionally require the pinned Isaac Lab/Isaac Sim runtime and official
policy checkpoints:

```bash
.venv/bin/python -m calibagent.cli.run_p5_isaaclab \
  --config configs/experiments/p5_isaaclab_main.yaml \
  --isaaclab-root /path/to/IsaacLab-v2.3.2
.venv/bin/python -m calibagent.cli.run_p6_isaaclab \
  --config configs/experiments/p6_domain_shift_main.yaml \
  --isaaclab-root /path/to/IsaacLab-v2.3.2
.venv/bin/python -m calibagent.cli.run_p7_isaaclab \
  --config configs/experiments/p7_navigation_main.yaml \
  --isaaclab-root /path/to/IsaacLab-v2.3.2
```

When the full supplemental output trees are mounted, repeat the 1.06 GB
trajectory/hash audit with:

```bash
.venv/bin/python -m calibagent.cli.audit_strong_readiness \
  --workspace . --raw --require-ready
```

The benchmarks write resolved configurations, run-level metrics, trial/pose
traces, paired statistics, simulator logs, and manifests. See
[`docs/requirements_matrix.md`](docs/requirements_matrix.md) for phase-level
evidence and [`docs/experiment_protocol.md`](docs/experiment_protocol.md) for
the evaluation protocol and its corrected statistical-unit warning.

Software CI and publication readiness are separate gates. See
[`docs/completion_semantics.md`](docs/completion_semantics.md) and the
[`2026-07-24 P0–P7 ICRA audit`](docs/audits/icra_p0_p7_2026-07-24.md).
The corrected main result is in [`reports/p3_main_report.md`](reports/p3_main_report.md),
the real Go2 result is in [`reports/p1_real_report.md`](reports/p1_real_report.md),
the safety/stopping result is in [`reports/p4_main_report.md`](reports/p4_main_report.md),
the simulator result is in [`reports/p5_main_report.md`](reports/p5_main_report.md),
the shift result is in [`reports/p6_main_report.md`](reports/p6_main_report.md),
the navigation result is in [`reports/p7_main_report.md`](reports/p7_main_report.md),
the strong shift result is in
[`reports/p6_strong_confirmatory_report.md`](reports/p6_strong_confirmatory_report.md),
the retained P7 failure is in
[`reports/p7_strong_confirmatory_failure.md`](reports/p7_strong_confirmatory_failure.md),
the successful disjoint replication is in
[`reports/p7_strong_confirmatory_v2_report.md`](reports/p7_strong_confirmatory_v2_report.md),
and acquisition requirements are in
[`docs/p1_real_data_protocol.md`](docs/p1_real_data_protocol.md). The complete
P8 online-hardware handoff, including software gates, safety, sample counts,
raw channels, schemas, randomization, QC, and publication gates, is
[`docs/p8_go2_real_deployment_data_handoff_zh.md`](docs/p8_go2_real_deployment_data_handoff_zh.md).

## Claim boundary

The GO verdict is deliberately scoped. P1 demonstrates passive, offline
full-affine calibration on real Go2/LiDAR-odometry trials. P3 demonstrates the
active planner under the frozen synthetic benchmark. P4 demonstrates stopping
and safety logic through frozen replay and fault injection. P5 demonstrates the
active closed loop in pinned Isaac Lab simulation. P6 demonstrates simulated
in-place shift detection and recovery, and P7 demonstrates simulator navigation
with a fixed planner. It does **not** claim that P3–P7 have been executed
online on a real Go2, that sim-to-real robustness is established, or that the
simulator results replace hardware validation.

For the stronger P6/P7 claim, P6 establishes an early-recovery advantage over
passive updating and an absolute terminal-accuracy bound; it does not establish
terminal superiority over passive updating. P7 establishes benefit over raw
control and registered noninferiority to dense and matched-budget controls only
in the pinned simulator. The first strong P7 confirmation failed and is part of
the evidence record.

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
intentionally gitignored. Frozen P3–P7 evidence is stored under the corresponding
`evidence/p3_main/` through `evidence/p7_main/` roots. The
self-contained P1 evidence bundle is under `evidence/p1_real/`; every frozen
artifact is hash-checked by the live audit.
The stronger P6/P7 compact evidence is under
`evidence/p6_strong_confirmatory/` and
`evidence/p7_strong_confirmatory_v2/`; hash-bound trace receipts link those
trees to the full supplemental trajectories.
