"""Paired P3 sample-efficiency benchmark and frozen artifact writer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import stats

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.planning.d_optimal import DOptimalPlanner
from calibagent.core.planning.ivr import IntegratedVariancePlanner, PlannerDiagnostics
from calibagent.core.planning.samplers import latin_hypercube, random_uniform, regular_grid, sobol
from calibagent.core.planning.task import TaskDistribution
from calibagent.data.manifest import build_manifest, write_resolved_config
from calibagent.eval.metrics import (
    gaussian_nll,
    integrated_uncertainty,
    interval_coverage,
    task_weighted_rmse,
)
from calibagent.eval.synthetic import SyntheticDistortion, make_observation


@dataclass(frozen=True)
class BenchmarkConfig:
    output_dir: str
    seeds: tuple[int, ...]
    methods: tuple[str, ...]
    families: tuple[str, ...]
    max_trials: int
    seed_design_count: int
    candidate_count: int
    task_grid_size: int
    evaluation_grid_size: int
    prior_scale: float
    assumed_noise_variance: tuple[float, float, float]
    target_rmse: float
    target_uncertainty: float
    risk_weight: float = 0.0
    distance_weight: float = 0.0
    task_centers: tuple[tuple[float, float, float], ...] = (
        (0.45, 0.0, 0.0),
        (0.25, 0.0, 0.65),
        (0.25, 0.0, -0.65),
    )
    task_scales: tuple[tuple[float, float, float], ...] = (
        (0.32, 0.18, 0.40),
        (0.28, 0.18, 0.35),
        (0.28, 0.18, 0.35),
    )
    task_mixture_weights: tuple[float, ...] = (0.5, 0.25, 0.25)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BenchmarkConfig:
        noise = tuple(float(x) for x in value["assumed_noise_variance"])
        if len(noise) != 3:
            raise ValueError("assumed_noise_variance must have length 3")
        default_centers = ((0.45, 0.0, 0.0), (0.25, 0.0, 0.65), (0.25, 0.0, -0.65))
        default_scales = ((0.32, 0.18, 0.40), (0.28, 0.18, 0.35), (0.28, 0.18, 0.35))
        raw_centers = value.get("task_centers", default_centers)
        raw_scales = value.get("task_scales", default_scales)
        if any(len(row) != 3 for row in (*raw_centers, *raw_scales)):
            raise ValueError("task centers and scales must contain three-vectors")
        centers = tuple((float(row[0]), float(row[1]), float(row[2])) for row in raw_centers)
        scales = tuple((float(row[0]), float(row[1]), float(row[2])) for row in raw_scales)
        mixture = tuple(
            float(item) for item in value.get("task_mixture_weights", (0.5, 0.25, 0.25))
        )
        if len(centers) != len(scales) or len(mixture) != len(centers):
            raise ValueError("task mixture centers, scales, and weights must have equal length")
        return cls(
            output_dir=str(value["output_dir"]),
            seeds=tuple(int(x) for x in value["seeds"]),
            methods=tuple(str(x) for x in value["methods"]),
            families=tuple(str(x) for x in value["families"]),
            max_trials=int(value["max_trials"]),
            seed_design_count=int(value["seed_design_count"]),
            candidate_count=int(value["candidate_count"]),
            task_grid_size=int(value["task_grid_size"]),
            evaluation_grid_size=int(value["evaluation_grid_size"]),
            prior_scale=float(value["prior_scale"]),
            assumed_noise_variance=(noise[0], noise[1], noise[2]),
            target_rmse=float(value["target_rmse"]),
            target_uncertainty=float(value["target_uncertainty"]),
            risk_weight=float(value.get("risk_weight", 0.0)),
            distance_weight=float(value.get("distance_weight", 0.0)),
            task_centers=centers,
            task_scales=scales,
            task_mixture_weights=mixture,
        )


BOUNDS = np.asarray([[-1.0, 1.0], [-0.5, 0.5], [-1.5, 1.5]], dtype=np.float64)


def _distortion_seed(family: str, seed: int) -> int:
    offsets = {"affine": 100_000, "deadzone": 200_000, "heteroscedastic": 300_000}
    return offsets[family] + seed


def _task_and_evaluation(
    config: BenchmarkConfig,
) -> tuple[TaskDistribution, NDArray[np.float64], NDArray[np.float64]]:
    task_commands = sobol(config.task_grid_size, BOUNDS, seed=11003)
    task_commands = task_commands[np.linalg.norm(task_commands[:, :2], axis=1) <= 1.0]
    # Deployment commands emphasize forward motion and moderate yaw, as a
    # navigation command log would. The frozen grid is independent of run seeds.
    centers = np.asarray(config.task_centers, dtype=np.float64)
    scales = np.asarray(config.task_scales, dtype=np.float64)
    mixture_weights = np.asarray(config.task_mixture_weights, dtype=np.float64)
    task = TaskDistribution.gaussian_mixture(
        task_commands,
        centers=centers,
        scales=scales,
        mixture_weights=mixture_weights,
    )
    evaluation = sobol(config.evaluation_grid_size, BOUNDS, seed=23011)
    evaluation = evaluation[np.linalg.norm(evaluation[:, :2], axis=1) <= 1.0]
    # Evaluate under the same declared deployment density, on disjoint points.
    evaluation_task = TaskDistribution.gaussian_mixture(
        evaluation,
        centers=centers,
        scales=scales,
        mixture_weights=mixture_weights,
    )
    return task, evaluation_task.commands, evaluation_task.weights


def _seed_design(count: int) -> NDArray[np.float64]:
    points = np.asarray(
        [
            [-0.6, 0.0, 0.0],
            [0.6, 0.0, 0.0],
            [0.0, -0.3, 0.0],
            [0.0, 0.3, 0.0],
            [0.0, 0.0, -0.9],
            [0.0, 0.0, 0.9],
            [0.3, 0.0, 0.45],
            [0.3, 0.0, -0.45],
        ],
        dtype=np.float64,
    )
    if count > len(points):
        raise ValueError("seed_design_count cannot exceed 8")
    return points[:count]


def _passive_sequence(method: str, count: int, seed: int) -> NDArray[np.float64]:
    if method == "random":
        commands = random_uniform(count * 3, BOUNDS, seed)
    elif method == "lhs":
        commands = latin_hypercube(count * 3, BOUNDS, seed)
    elif method == "sobol":
        commands = sobol(count * 3, BOUNDS, seed)
    elif method in {"grid", "dense"}:
        commands = regular_grid(7, BOUNDS)
    else:
        raise ValueError(f"unknown passive method {method}")
    commands = commands[np.linalg.norm(commands[:, :2], axis=1) <= 1.0]
    if len(commands) < count:
        raise RuntimeError("passive sampler did not produce enough valid commands")
    return np.asarray(commands[:count], dtype=np.float64)


def run_one(
    config: BenchmarkConfig,
    family: str,
    method: str,
    seed: int,
    task: TaskDistribution,
    evaluation_commands: NDArray[np.float64],
    evaluation_weights: NDArray[np.float64],
    pool: CandidatePool,
    transformer: BasisTransformer,
) -> tuple[list[dict[str, Any]], BayesianBasisModel, PlannerDiagnostics | None]:
    distortion = SyntheticDistortion.from_seed(family, _distortion_seed(family, seed))
    observation_rng = np.random.default_rng(seed + 50000)
    model = BayesianBasisModel(transformer, config.prior_scale, list(config.assumed_noise_variance))
    seed_commands = _seed_design(config.seed_design_count)
    active_methods = {"active", "active_no_task", "d_opt"}
    passive = (
        None
        if method in active_methods
        else _passive_sequence(method, config.max_trials - config.seed_design_count, seed + 70000)
    )
    planner = IntegratedVariancePlanner(
        pool,
        risk_weight=config.risk_weight,
        distance_weight=config.distance_weight,
        duplicate_distance=0.025,
    )
    uniform_task = TaskDistribution.uniform(task.commands)
    d_optimal = DOptimalPlanner(pool, duplicate_distance=0.025)
    history: list[NDArray[np.float64]] = []
    truth = distortion.noiseless(evaluation_commands)
    noisy_evaluation, evaluation_noise_variance = distortion.sample(
        evaluation_commands, np.random.default_rng(seed + 60000)
    )
    records: list[dict[str, Any]] = []
    for trial in range(config.max_trials):
        candidate_score = np.nan
        candidate_information = np.nan
        candidate_cost = np.nan
        if trial < len(seed_commands):
            command = seed_commands[trial]
            source = "seed_design"
        elif method in {"active", "active_no_task"}:
            planning_task = task if method == "active" else uniform_task
            candidate = planner.propose(model, planning_task, history, k=1)[0]
            command = candidate.command.as_array()
            candidate_score = candidate.score
            candidate_information = candidate.information_gain
            candidate_cost = candidate.cost
            source = method
        elif method == "d_opt":
            candidate = d_optimal.propose(model, history, k=1)[0]
            command = candidate.command.as_array()
            candidate_score = candidate.score
            candidate_information = candidate.information_gain
            candidate_cost = candidate.cost
            source = method
        else:
            assert passive is not None
            command = passive[trial - len(seed_commands)]
            source = method
        observation = make_observation(distortion, command, observation_rng, trial)
        model.update(observation)
        history.append(command.copy())
        mean, epistemic = model.predict_batch(evaluation_commands, include_noise=False)
        # Held-out reference covariance is evaluation metadata, not planner
        # input. Combining it with epistemic variance evaluates the declared
        # predictive distribution without charging training noise twice.
        variance = epistemic + evaluation_noise_variance
        coverage, interval_width = interval_coverage(mean, variance, noisy_evaluation)
        records.append(
            {
                "family": family,
                "method": method,
                "seed": seed,
                "trial": trial + 1,
                "source": source,
                "cmd_vx": command[0],
                "cmd_vy": command[1],
                "cmd_wz": command[2],
                "candidate_score": candidate_score,
                "candidate_information": candidate_information,
                "candidate_cost": candidate_cost,
                "rmse": task_weighted_rmse(mean, truth, evaluation_weights),
                "integrated_uncertainty": integrated_uncertainty(model, task),
                "nll": gaussian_nll(mean, variance, noisy_evaluation, evaluation_weights),
                "coverage_95": coverage,
                "interval_width_95": interval_width,
            }
        )
    diagnostics = d_optimal.last_diagnostics if method == "d_opt" else planner.last_diagnostics
    return records, model, diagnostics


def _run_dense_oracle(
    config: BenchmarkConfig,
    family: str,
    seed: int,
    evaluation_commands: NDArray[np.float64],
    evaluation_weights: NDArray[np.float64],
    pool: CandidatePool,
    transformer: BasisTransformer,
) -> dict[str, Any]:
    """Fit the full safe candidate pool as a non-sequential performance ceiling."""
    distortion = SyntheticDistortion.from_seed(family, _distortion_seed(family, seed))
    model = BayesianBasisModel(transformer, config.prior_scale, list(config.assumed_noise_variance))
    rng = np.random.default_rng(seed + 80000)
    for trial, command in enumerate(pool.commands):
        model.update(make_observation(distortion, command, rng, trial))
    truth = distortion.noiseless(evaluation_commands)
    noisy, evaluation_noise = distortion.sample(
        evaluation_commands, np.random.default_rng(seed + 60000)
    )
    mean, epistemic = model.predict_batch(evaluation_commands, include_noise=False)
    coverage, _ = interval_coverage(mean, epistemic + evaluation_noise, noisy)
    return {
        "family": family,
        "method": "dense",
        "seed": seed,
        "trials_to_target": config.candidate_count,
        "target_reached": True,
        "final_rmse": task_weighted_rmse(mean, truth, evaluation_weights),
        "final_uncertainty": float(
            np.average(np.sum(epistemic, axis=1), weights=evaluation_weights)
        ),
        "final_coverage_95": coverage,
        "oracle_budget": config.candidate_count,
    }


def _summarize(trace: pd.DataFrame, config: BenchmarkConfig) -> pd.DataFrame:
    summary_rows: list[dict[str, Any]] = []
    for (family, method, seed), group in trace.groupby(["family", "method", "seed"], sort=True):
        reached = group[
            (group["rmse"] <= config.target_rmse)
            & (group["integrated_uncertainty"] <= config.target_uncertainty)
        ]
        summary_rows.append(
            {
                "family": family,
                "method": method,
                "seed": seed,
                "trials_to_target": int(reached["trial"].iloc[0])
                if len(reached)
                else config.max_trials + 1,
                "target_reached": bool(len(reached)),
                "final_rmse": float(group["rmse"].iloc[-1]),
                "final_uncertainty": float(group["integrated_uncertainty"].iloc[-1]),
                "final_coverage_95": float(group["coverage_95"].iloc[-1]),
            }
        )
    return pd.DataFrame(summary_rows)


def _paired_statistics(summary: pd.DataFrame) -> dict[str, Any]:
    results: dict[str, Any] = {}
    # A seed is the preregistered independent unit; distortion family is a
    # repeated condition. Aggregating before inference prevents pseudo-
    # replication while retaining method pairing.
    aggregated = summary.groupby(["seed", "method"], as_index=False)["trials_to_target"].mean()
    for baseline in ("lhs", "random", "sobol", "d_opt", "active_no_task"):
        if baseline not in set(summary["method"]):
            continue
        active = aggregated[aggregated["method"] == "active"].set_index("seed")
        passive = aggregated[aggregated["method"] == baseline].set_index("seed")
        common = active.index.intersection(passive.index)
        active_trials = active.loc[common, "trials_to_target"].to_numpy(dtype=float)
        passive_trials = passive.loc[common, "trials_to_target"].to_numpy(dtype=float)
        differences = passive_trials - active_trials
        if len(differences) and np.any(differences != 0):
            wilcoxon = stats.wilcoxon(active_trials, passive_trials, alternative="less")
            p_value = float(wilcoxon.pvalue)
        else:
            p_value = 1.0
        reduction = 1.0 - float(np.mean(active_trials) / np.mean(passive_trials))
        rng = np.random.default_rng(99117)
        bootstrap = np.asarray(
            [np.mean(rng.choice(differences, len(differences), replace=True)) for _ in range(5000)]
        )
        results[f"active_vs_{baseline}"] = {
            "independent_unit": "seed",
            "paired_runs": len(common),
            "mean_trials_active": float(np.mean(active_trials)),
            "mean_trials_baseline": float(np.mean(passive_trials)),
            "relative_reduction": reduction,
            "mean_paired_trials_saved": float(np.mean(differences)),
            "paired_trials_saved_ci95": [
                float(np.quantile(bootstrap, 0.025)),
                float(np.quantile(bootstrap, 0.975)),
            ],
            "wilcoxon_one_sided_p": p_value,
        }
    return results


def run_suite(config: BenchmarkConfig) -> dict[str, Any]:
    output = Path(config.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    task, evaluation_commands, evaluation_weights = _task_and_evaluation(config)
    command_space = CommandSpace(BOUNDS, max_linear_norm=1.0)
    pool = CandidatePool.generate(command_space, config.candidate_count, seed=31013)
    # Scaling is fitted once on predeclared candidate commands, never outcomes.
    transformer = BasisTransformer("m2_affine_cross_hinge").fit(pool.commands)
    records: list[dict[str, Any]] = []
    representative_model: BayesianBasisModel | None = None
    representative_diagnostics: PlannerDiagnostics | None = None
    representative_family: str | None = None
    representative_seed: int | None = None
    dense_rows: list[dict[str, Any]] = []
    for family in config.families:
        for seed in config.seeds:
            for method in config.methods:
                if method == "dense":
                    dense_rows.append(
                        _run_dense_oracle(
                            config,
                            family,
                            seed,
                            evaluation_commands,
                            evaluation_weights,
                            pool,
                            transformer,
                        )
                    )
                    continue
                run_records, fitted_model, diagnostics = run_one(
                    config,
                    family,
                    method,
                    seed,
                    task,
                    evaluation_commands,
                    evaluation_weights,
                    pool,
                    transformer,
                )
                records.extend(run_records)
                if method == "active" and representative_model is None:
                    representative_model = fitted_model
                    representative_diagnostics = diagnostics
                    representative_family = family
                    representative_seed = seed
    trace = pd.DataFrame(records)
    summary = _summarize(trace, config)
    if dense_rows:
        summary = pd.concat([summary, pd.DataFrame(dense_rows)], ignore_index=True)
    statistics = _paired_statistics(summary)
    trace.to_csv(output / "trial_trace.csv", index=False)
    summary.to_csv(output / "metrics.csv", index=False)
    if dense_rows:
        pd.DataFrame(dense_rows).to_csv(output / "dense_oracle_metrics.csv", index=False)
    if representative_model is None or representative_family is None or representative_seed is None:
        raise RuntimeError("suite must include the active method for P3 diagnostics")
    representative_model.save_state(output / "representative_posterior.npz")
    if representative_diagnostics is not None:
        pd.DataFrame(
            {
                "cmd_vx": representative_diagnostics.commands[:, 0],
                "cmd_vy": representative_diagnostics.commands[:, 1],
                "cmd_wz": representative_diagnostics.commands[:, 2],
                "information_gain": representative_diagnostics.information_gain,
                "cost": representative_diagnostics.cost,
                "score": representative_diagnostics.score,
            }
        ).to_csv(output / "planner_diagnostics.csv", index=False)
    slice_vx = np.linspace(BOUNDS[0, 0], BOUNDS[0, 1], 61)
    slice_wz = np.linspace(BOUNDS[2, 0], BOUNDS[2, 1], 61)
    mesh_vx, mesh_wz = np.meshgrid(slice_vx, slice_wz)
    slice_commands = np.column_stack([mesh_vx.ravel(), np.zeros(mesh_vx.size), mesh_wz.ravel()])
    slice_mean, slice_variance = representative_model.predict_batch(
        slice_commands, include_noise=False
    )
    slice_truth = SyntheticDistortion.from_seed(
        representative_family, _distortion_seed(representative_family, representative_seed)
    ).noiseless(slice_commands)
    pd.DataFrame(
        {
            "vx": slice_commands[:, 0],
            "wz": slice_commands[:, 2],
            "epistemic_trace": np.sum(slice_variance, axis=1),
            "error_norm": np.linalg.norm(slice_mean - slice_truth, axis=1),
        }
    ).to_csv(output / "uncertainty_slice.csv", index=False)
    (output / "paired_statistics.json").write_text(
        json.dumps(statistics, indent=2, sort_keys=True), encoding="utf-8"
    )
    config_dict = asdict(config)
    write_resolved_config(config_dict, output / "resolved_config.json")
    manifest = build_manifest(
        config_dict,
        {"global": 31013, "task": 11003, "evaluation": 23011},
        "synthetic",
        "M2_basis_blr",
        "task_iv_reduction_v1",
    )
    manifest = type(manifest)(
        **{
            **manifest.to_dict(),
            "artifacts": {
                "trials": "trial_trace.csv",
                "metrics": "metrics.csv",
                "statistics": "paired_statistics.json",
                "config": "resolved_config.json",
                "posterior": "representative_posterior.npz",
                "planner_diagnostics": "planner_diagnostics.csv",
                "uncertainty_slice": "uncertainty_slice.csv",
                **({"dense_oracle": "dense_oracle_metrics.csv"} if dense_rows else {}),
            },
        }
    )
    manifest.save_json(output / "manifest.json")
    return statistics
