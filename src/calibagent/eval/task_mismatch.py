"""Post-hoc task-distribution mismatch sensitivity on frozen acquisitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from numpy.typing import NDArray

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.planning.samplers import sobol
from calibagent.core.planning.task import TaskDistribution
from calibagent.eval.benchmark import BOUNDS, BenchmarkConfig, _distortion_seed
from calibagent.eval.metrics import task_weighted_rmse
from calibagent.eval.synthetic import SyntheticDistortion, make_observation


@dataclass(frozen=True)
class DistributionSpec:
    identifier: str
    mixture_weights: tuple[float, ...] | None
    uniform: bool


@dataclass(frozen=True)
class TaskMismatchConfig:
    source_config: str
    source_trace: str
    output_dir: str
    methods: tuple[str, ...]
    baselines: tuple[str, ...]
    budgets: tuple[int, ...]
    evaluation_grid_size: int
    evaluation_grid_seed: int
    bootstrap_draws: int
    bootstrap_seed: int
    task_centers: tuple[tuple[float, float, float], ...]
    task_scales: tuple[tuple[float, float, float], ...]
    distributions: tuple[DistributionSpec, ...]
    gates: dict[str, Any]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TaskMismatchConfig:
        centers = tuple(tuple(float(x) for x in row) for row in value["task_centers"])
        scales = tuple(tuple(float(x) for x in row) for row in value["task_scales"])
        if len(centers) != len(scales) or any(len(row) != 3 for row in (*centers, *scales)):
            raise ValueError("task centers and scales must contain matching three-vectors")
        distributions = tuple(
            DistributionSpec(
                identifier=str(item["id"]),
                mixture_weights=(
                    tuple(float(x) for x in item["mixture_weights"])
                    if "mixture_weights" in item
                    else None
                ),
                uniform=bool(item.get("uniform", False)),
            )
            for item in value["distributions"]
        )
        identifiers = [item.identifier for item in distributions]
        if len(set(identifiers)) != len(identifiers) or "declared" not in identifiers:
            raise ValueError("distribution identifiers must be unique and include declared")
        for item in distributions:
            if item.uniform == (item.mixture_weights is not None):
                raise ValueError("each distribution must specify exactly one weighting rule")
            if item.mixture_weights is not None and len(item.mixture_weights) != len(centers):
                raise ValueError("mixture weights must match task centers")
        methods = tuple(str(item) for item in value["methods"])
        baselines = tuple(str(item) for item in value["baselines"])
        if "active" not in methods or any(item not in methods for item in baselines):
            raise ValueError("methods must contain active and every baseline")
        budgets = tuple(int(item) for item in value["budgets"])
        if not budgets or sorted(set(budgets)) != list(budgets) or min(budgets) < 1:
            raise ValueError("budgets must be unique, increasing, and positive")
        return cls(
            source_config=str(value["source_config"]),
            source_trace=str(value["source_trace"]),
            output_dir=str(value["output_dir"]),
            methods=methods,
            baselines=baselines,
            budgets=budgets,
            evaluation_grid_size=int(value["evaluation_grid_size"]),
            evaluation_grid_seed=int(value["evaluation_grid_seed"]),
            bootstrap_draws=int(value["bootstrap_draws"]),
            bootstrap_seed=int(value["bootstrap_seed"]),
            task_centers=centers,
            task_scales=scales,
            distributions=distributions,
            gates=dict(value["gates"]),
            raw=dict(value),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> TaskMismatchConfig:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("task-mismatch config must be a mapping")
        return cls.from_dict(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _evaluation_tasks(config: TaskMismatchConfig) -> dict[str, TaskDistribution]:
    commands = sobol(config.evaluation_grid_size * 2, BOUNDS, config.evaluation_grid_seed)
    commands = commands[np.linalg.norm(commands[:, :2], axis=1) <= 1.0]
    if len(commands) < config.evaluation_grid_size:
        raise RuntimeError("insufficient safe evaluation commands")
    commands = commands[: config.evaluation_grid_size]
    centers = np.asarray(config.task_centers, dtype=np.float64)
    scales = np.asarray(config.task_scales, dtype=np.float64)
    tasks: dict[str, TaskDistribution] = {}
    for spec in config.distributions:
        tasks[spec.identifier] = (
            TaskDistribution.uniform(commands)
            if spec.uniform
            else TaskDistribution.gaussian_mixture(
                commands,
                centers,
                scales,
                np.asarray(spec.mixture_weights, dtype=np.float64),
            )
        )
    return tasks


def _bootstrap_mean(values: NDArray[np.float64], draws: int, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    samples = np.mean(
        rng.choice(values, size=(draws, len(values)), replace=True),
        axis=1,
    )
    return [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))]


def run_task_mismatch(config_path: Path, workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    config = TaskMismatchConfig.from_yaml(config_path)
    source_config_path = workspace / config.source_config
    source_trace_path = workspace / config.source_trace
    source_config = BenchmarkConfig.from_dict(
        json.loads(source_config_path.read_text(encoding="utf-8"))
    )
    trace = pd.read_csv(source_trace_path)
    output = workspace / config.output_dir
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)

    expected = {
        (family, method, seed)
        for family in source_config.families
        for method in config.methods
        for seed in source_config.seeds
    }
    actual = {
        (str(family), str(method), int(seed))
        for family, method, seed in trace[["family", "method", "seed"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
        if str(method) in config.methods
    }
    if actual != expected:
        raise ValueError("source trace does not contain the expected paired method grid")

    task_distributions = _evaluation_tasks(config)
    evaluation_commands = next(iter(task_distributions.values())).commands
    command_space = CommandSpace(BOUNDS, max_linear_norm=1.0)
    pool = CandidatePool.generate(command_space, source_config.candidate_count, seed=31013)
    transformer = BasisTransformer("m2_affine_cross_hinge").fit(pool.commands)
    rows: list[dict[str, Any]] = []
    max_budget = max(config.budgets)
    for (family, method, seed), group in trace.loc[
        trace["method"].isin(config.methods)
    ].groupby(["family", "method", "seed"], sort=True):
        distortion = SyntheticDistortion.from_seed(
            str(family), _distortion_seed(str(family), int(seed))
        )
        truth = distortion.noiseless(evaluation_commands)
        model = BayesianBasisModel(
            transformer,
            source_config.prior_scale,
            list(source_config.assumed_noise_variance),
        )
        rng = np.random.default_rng(int(seed) + 50000)
        for record in group.sort_values("trial").itertuples(index=False):
            trial = int(record.trial)
            if trial > max_budget:
                break
            command = np.asarray(
                [record.cmd_vx, record.cmd_vy, record.cmd_wz], dtype=np.float64
            )
            model.update(make_observation(distortion, command, rng, trial - 1))
            if trial not in config.budgets:
                continue
            prediction, _ = model.predict_batch(evaluation_commands, include_noise=False)
            for identifier, task in task_distributions.items():
                rows.append(
                    {
                        "family": str(family),
                        "method": str(method),
                        "seed": int(seed),
                        "budget": trial,
                        "distribution": identifier,
                        "rmse": task_weighted_rmse(prediction, truth, task.weights),
                    }
                )
    per_condition = pd.DataFrame(rows)
    if per_condition.empty or not np.isfinite(per_condition["rmse"]).all():
        raise RuntimeError("task-mismatch analysis produced invalid metrics")
    per_condition.to_csv(output / "per_condition.csv", index=False)

    repeated = per_condition.groupby(
        ["distribution", "method", "budget", "seed"], as_index=False
    )["rmse"].mean()
    comparison_rows: list[dict[str, Any]] = []
    offset = 0
    for distribution in task_distributions:
        for budget in config.budgets:
            selected = repeated.loc[
                (repeated["distribution"] == distribution)
                & (repeated["budget"] == budget)
            ]
            active = selected.loc[selected["method"] == "active"].set_index("seed")
            for baseline in config.baselines:
                control = selected.loc[selected["method"] == baseline].set_index("seed")
                paired = control.loc[active.index, "rmse"].to_numpy(dtype=float) - active[
                    "rmse"
                ].to_numpy(dtype=float)
                interval = _bootstrap_mean(
                    paired,
                    config.bootstrap_draws,
                    config.bootstrap_seed + offset,
                )
                offset += 1
                comparison_rows.append(
                    {
                        "distribution": distribution,
                        "budget": budget,
                        "baseline": baseline,
                        "mean_baseline_minus_task_ivr_rmse": float(np.mean(paired)),
                        "ci95_lower": interval[0],
                        "ci95_upper": interval[1],
                        "task_ivr_win_rate": float(np.mean(paired > 0.0)),
                        "paired_seeds": len(paired),
                    }
                )
    comparisons = pd.DataFrame(comparison_rows)
    comparisons.to_csv(output / "comparisons.csv", index=False)

    active = repeated.loc[repeated["method"] == "active"].copy()
    declared = active.loc[active["distribution"] == "declared"].set_index(
        ["budget", "seed"]
    )["rmse"]
    ratio_rows: list[dict[str, Any]] = []
    for row in active.itertuples(index=False):
        ratio_rows.append(
            {
                "distribution": row.distribution,
                "budget": int(row.budget),
                "seed": int(row.seed),
                "task_ivr_mismatch_to_declared_rmse_ratio": float(
                    row.rmse / declared.loc[(int(row.budget), int(row.seed))]
                ),
            }
        )
    ratios = pd.DataFrame(ratio_rows)
    ratios.to_csv(output / "task_ivr_mismatch_ratios.csv", index=False)

    gates = config.gates
    robustness_budget = int(gates["robustness_budget"])
    maximum_ratio = float(
        ratios.loc[ratios["budget"] == robustness_budget]
        .groupby("distribution")["task_ivr_mismatch_to_declared_rmse_ratio"]
        .mean()
        .max()
    )
    lhs_positive = int(
        (
            comparisons.loc[
                (comparisons["budget"] == robustness_budget)
                & (comparisons["baseline"] == "lhs"),
                "ci95_lower",
            ]
            > 0.0
        ).sum()
    )
    declared_budget = int(gates["declared_advantage_budget"])
    declared = comparisons.loc[
        (comparisons["distribution"] == "declared")
        & (comparisons["budget"] == declared_budget)
    ]
    checks = {
        "finite_and_complete": bool(
            len(per_condition)
            == len(source_config.families)
            * len(source_config.seeds)
            * len(config.methods)
            * len(config.budgets)
            * len(task_distributions)
        ),
        "bounded_mismatch_inflation": maximum_ratio
        <= float(gates["maximum_task_ivr_mismatch_to_declared_rmse_ratio"]),
        "lhs_robustness": lhs_positive
        >= int(gates["minimum_distributions_beating_lhs_ci95_lower"]),
        "declared_task_advantage": bool((declared["ci95_lower"] > 0.0).all()),
    }
    summary = {
        "schema_version": "1.0",
        "verdict": "GO" if all(checks.values()) else "NO_GO",
        "checks": checks,
        "families": list(source_config.families),
        "paired_seeds": len(source_config.seeds),
        "distributions": list(task_distributions),
        "budgets": list(config.budgets),
        "maximum_mean_task_ivr_mismatch_to_declared_rmse_ratio_at_robustness_budget": maximum_ratio,
        "distributions_beating_lhs_ci95_lower_at_robustness_budget": lhs_positive,
        "comparison_records": comparison_rows,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "resolved_config.json").write_text(
        json.dumps(config.raw, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    artifacts = {}
    for name in (
        "comparisons.csv",
        "per_condition.csv",
        "resolved_config.json",
        "summary.json",
        "task_ivr_mismatch_ratios.csv",
    ):
        path = output / name
        artifacts[name] = {"path": name, "sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "schema_version": "1.0",
        "source_config_sha256": _sha256(source_config_path),
        "source_trace_sha256": _sha256(source_trace_path),
        "artifacts": artifacts,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
