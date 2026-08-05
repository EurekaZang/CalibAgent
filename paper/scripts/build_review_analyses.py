#!/usr/bin/env python3
"""Derive reviewer-requested analyses from immutable P1/P3/P6/P7 evidence.

The script never edits the frozen evidence bundles.  It reconstructs declared
models from recorded commands where needed and writes paper-facing secondary
analyses under ``paper/process``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.models.least_squares import LeastSquaresVelocityModel
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.planning.samplers import sobol
from calibagent.core.planning.task import TaskDistribution
from calibagent.data.observations import load_observations
from calibagent.eval.benchmark import BOUNDS, BenchmarkConfig, _distortion_seed
from calibagent.eval.metrics import task_weighted_rmse
from calibagent.eval.replay import _selection_indices
from calibagent.eval.synthetic import SyntheticDistortion, make_observation


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "paper/process/phase4_artifacts/reviewer_analysis"
OUT.mkdir(parents=True, exist_ok=True)


def _bootstrap_mean(values: np.ndarray, seed: int, draws: int = 4000) -> list[float]:
    rng = np.random.default_rng(seed)
    samples = np.mean(
        rng.choice(values, size=(draws, len(values)), replace=True),
        axis=1,
    )
    return [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))]


def _p1_analysis() -> dict[str, Any]:
    observations = [
        item
        for item in load_observations(ROOT / "evidence/p1_real/observations.parquet")
        if item.valid
    ]
    sessions = sorted({item.context.session_id for item in observations})
    residuals: dict[str, list[np.ndarray]] = {"raw": [], "m0": [], "m1": []}
    matrices: list[dict[str, Any]] = []
    for validation_session in sessions:
        training = [
            item for item in observations if item.context.session_id != validation_session
        ]
        validation = [
            item for item in observations if item.context.session_id == validation_session
        ]
        training_commands = np.vstack([item.command.as_array() for item in training])
        selected_indices = _selection_indices("lhs", training_commands, 30, 1701)
        selected = [training[int(index)] for index in selected_indices]
        commands = np.vstack([item.command.as_array() for item in validation])
        targets = np.vstack([item.mean_velocity for item in validation])
        m0 = LeastSquaresVelocityModel("M0_diagonal_affine").fit(selected)
        m1 = LeastSquaresVelocityModel("M1_full_affine").fit(selected)
        predictions = {
            "raw": commands,
            "m0": np.vstack([m0.predict(command).mean for command in commands]),
            "m1": np.vstack([m1.predict(command).mean for command in commands]),
        }
        for name, prediction in predictions.items():
            residuals[name].append(prediction - targets)
        coefficients = np.vstack(m1.coefficients_)
        matrices.append(
            {
                "held_out_session": validation_session,
                "bias": coefficients[:, 0].tolist(),
                "gain_coupling_matrix": coefficients[:, 1:].tolist(),
            }
        )
    axis_rmse = {
        name: np.sqrt(np.mean(np.vstack(values) ** 2, axis=0))
        for name, values in residuals.items()
    }
    rows = []
    for axis, label in enumerate(("vx", "vy", "wz")):
        rows.append(
            {
                "axis": label,
                "raw_rmse": float(axis_rmse["raw"][axis]),
                "m0_rmse": float(axis_rmse["m0"][axis]),
                "m1_rmse": float(axis_rmse["m1"][axis]),
                "m1_vs_raw_reduction": float(
                    1.0 - axis_rmse["m1"][axis] / axis_rmse["raw"][axis]
                ),
                "m1_vs_m0_reduction": float(
                    1.0 - axis_rmse["m1"][axis] / axis_rmse["m0"][axis]
                ),
            }
        )
    pd.DataFrame(rows).to_csv(OUT / "p1_axis_metrics.csv", index=False)
    return {"axis_metrics": rows, "fold_affine_models": matrices}


def _first_trial(group: pd.DataFrame, condition: np.ndarray, horizon: int) -> int:
    reached = group.loc[condition, "trial"]
    return int(reached.iloc[0]) if len(reached) else horizon + 1


def _audit_task(config: BenchmarkConfig) -> TaskDistribution:
    commands = sobol(1024, BOUNDS, seed=43019)
    commands = commands[np.linalg.norm(commands[:, :2], axis=1) <= 1.0]
    return TaskDistribution.gaussian_mixture(
        commands,
        centers=np.asarray(config.task_centers, dtype=np.float64),
        scales=np.asarray(config.task_scales, dtype=np.float64),
        mixture_weights=np.asarray(config.task_mixture_weights, dtype=np.float64),
    )


def _p3_analysis() -> dict[str, Any]:
    trace = pd.read_csv(ROOT / "evidence/p3_main/trial_trace.csv")
    metrics = pd.read_csv(ROOT / "evidence/p3_main/metrics.csv")
    config = BenchmarkConfig.from_dict(
        json.loads((ROOT / "evidence/p3_main/resolved_config.json").read_text())
    )
    methods = ("active", "lhs", "d_opt", "active_no_task")
    labels = {
        "active": "Task IVR",
        "lhs": "LHS",
        "d_opt": "D-optimal",
        "active_no_task": "No-task IVR",
    }

    family_rows: list[dict[str, Any]] = []
    for family in config.families:
        selected = metrics[metrics["family"] == family]
        active = selected[selected["method"] == "active"].set_index("seed")
        for method in methods:
            current = selected[selected["method"] == method].set_index("seed")
            values = current["trials_to_target"].to_numpy(dtype=float)
            row: dict[str, Any] = {
                "family": family,
                "method": method,
                "method_label": labels[method],
                "mean_trials": float(np.mean(values)),
                "target_rate": float(np.mean(current["target_reached"].astype(bool))),
                "mean_trials_ci95": _bootstrap_mean(values, 51001 + len(family_rows)),
            }
            if method != "active":
                common = active.index.intersection(current.index)
                saved = (
                    current.loc[common, "trials_to_target"].to_numpy(dtype=float)
                    - active.loc[common, "trials_to_target"].to_numpy(dtype=float)
                )
                row["active_trials_saved"] = float(np.mean(saved))
                row["active_trials_saved_ci95"] = _bootstrap_mean(
                    saved, 52001 + len(family_rows)
                )
            family_rows.append(row)
    pd.DataFrame(family_rows).to_csv(OUT / "p3_family_metrics.csv", index=False)

    gate_rows: list[dict[str, Any]] = []
    for (family, method, seed), group in trace.groupby(
        ["family", "method", "seed"], sort=True
    ):
        if method not in methods:
            continue
        ordered = group.sort_values("trial")
        accuracy_trial = _first_trial(
            ordered,
            ordered["rmse"].to_numpy(dtype=float) <= config.target_rmse,
            config.max_trials,
        )
        uncertainty_trial = _first_trial(
            ordered,
            ordered["integrated_uncertainty"].to_numpy(dtype=float)
            <= config.target_uncertainty,
            config.max_trials,
        )
        joint_trial = _first_trial(
            ordered,
            (
                ordered["rmse"].to_numpy(dtype=float) <= config.target_rmse
            )
            & (
                ordered["integrated_uncertainty"].to_numpy(dtype=float)
                <= config.target_uncertainty
            ),
            config.max_trials,
        )
        binding = (
            "accuracy"
            if accuracy_trial > uncertainty_trial
            else "uncertainty"
            if uncertainty_trial > accuracy_trial
            else "simultaneous"
        )
        gate_rows.append(
            {
                "family": family,
                "method": method,
                "seed": int(seed),
                "accuracy_trial": accuracy_trial,
                "uncertainty_trial": uncertainty_trial,
                "joint_trial": joint_trial,
                "binding_gate": binding,
            }
        )
    gate_frame = pd.DataFrame(gate_rows)
    gate_frame.to_csv(OUT / "p3_gate_decomposition.csv", index=False)

    # Reconstruct each model only to its declared crossing time, then evaluate
    # once on a disjoint Sobol audit grid that neither acquisition nor the
    # primary target calculation can access.
    command_space = CommandSpace(BOUNDS, max_linear_norm=1.0)
    pool = CandidatePool.generate(command_space, config.candidate_count, seed=31013)
    transformer = BasisTransformer("m2_affine_cross_hinge").fit(pool.commands)
    audit_task = _audit_task(config)
    audit_rows: list[dict[str, Any]] = []
    crossing = gate_frame.set_index(["family", "method", "seed"])
    for (family, method, seed), group in trace.groupby(
        ["family", "method", "seed"], sort=True
    ):
        if method not in methods:
            continue
        stop_trial = int(crossing.loc[(family, method, seed), "joint_trial"])
        distortion = SyntheticDistortion.from_seed(
            str(family), _distortion_seed(str(family), int(seed))
        )
        model = BayesianBasisModel(
            transformer,
            config.prior_scale,
            list(config.assumed_noise_variance),
        )
        observation_rng = np.random.default_rng(int(seed) + 50000)
        for record in group.sort_values("trial").itertuples(index=False):
            if int(record.trial) > stop_trial:
                break
            command = np.asarray(
                [record.cmd_vx, record.cmd_vy, record.cmd_wz], dtype=np.float64
            )
            model.update(
                make_observation(
                    distortion, command, observation_rng, int(record.trial) - 1
                )
            )
        truth = distortion.noiseless(audit_task.commands)
        noisy, audit_noise = distortion.sample(
            audit_task.commands, np.random.default_rng(int(seed) + 64000)
        )
        prediction, epistemic = model.predict_batch(
            audit_task.commands, include_noise=False
        )
        total_variance = epistemic + audit_noise
        inside = np.abs(noisy - prediction) <= 1.959963984540054 * np.sqrt(
            np.maximum(total_variance, 0.0)
        )
        axis_rmse = np.sqrt(np.average((prediction - truth) ** 2, axis=0, weights=audit_task.weights))
        audit_rows.append(
            {
                "family": family,
                "method": method,
                "seed": int(seed),
                "primary_crossing_trial": stop_trial,
                "audit_rmse": task_weighted_rmse(
                    prediction, truth, audit_task.weights
                ),
                "audit_rmse_vx": float(axis_rmse[0]),
                "audit_rmse_vy": float(axis_rmse[1]),
                "audit_rmse_wz": float(axis_rmse[2]),
                "audit_coverage_vx": float(np.mean(inside[:, 0])),
                "audit_coverage_vy": float(np.mean(inside[:, 1])),
                "audit_coverage_wz": float(np.mean(inside[:, 2])),
            }
        )
    audit_frame = pd.DataFrame(audit_rows)
    audit_frame.to_csv(OUT / "p3_disjoint_audit.csv", index=False)

    sensitivity_rows: list[dict[str, Any]] = []
    for rmse_threshold in (0.030, 0.040, 0.050):
        for uncertainty_threshold in (0.0010, 0.0015, 0.0020):
            crossing_rows: list[dict[str, Any]] = []
            for (family, method, seed), group in trace.groupby(
                ["family", "method", "seed"], sort=True
            ):
                if method not in methods:
                    continue
                ordered = group.sort_values("trial")
                trial = _first_trial(
                    ordered,
                    (
                        ordered["rmse"].to_numpy(dtype=float) <= rmse_threshold
                    )
                    & (
                        ordered["integrated_uncertainty"].to_numpy(dtype=float)
                        <= uncertainty_threshold
                    ),
                    config.max_trials,
                )
                crossing_rows.append(
                    {
                        "family": family,
                        "method": method,
                        "seed": int(seed),
                        "trial": trial,
                    }
                )
            crossing_frame = pd.DataFrame(crossing_rows)
            aggregated = crossing_frame.groupby(["seed", "method"])["trial"].mean()
            active_values = aggregated.xs("active", level="method")
            for baseline in ("lhs", "d_opt", "active_no_task"):
                baseline_values = aggregated.xs(baseline, level="method")
                common = active_values.index.intersection(baseline_values.index)
                saved = baseline_values.loc[common] - active_values.loc[common]
                sensitivity_rows.append(
                    {
                        "rmse_threshold": rmse_threshold,
                        "uncertainty_threshold": uncertainty_threshold,
                        "baseline": baseline,
                        "mean_trials_saved": float(saved.mean()),
                        "all_seeds_positive": bool(np.all(saved.to_numpy() > 0)),
                    }
                )
    pd.DataFrame(sensitivity_rows).to_csv(
        OUT / "p3_threshold_sensitivity.csv", index=False
    )
    binding_summary = (
        gate_frame.groupby(["method", "binding_gate"]).size().unstack(fill_value=0)
    )
    audit_summary = (
        audit_frame.groupby(["family", "method"], as_index=False)
        .agg(
            audit_rmse=("audit_rmse", "mean"),
            coverage_vx=("audit_coverage_vx", "mean"),
            coverage_vy=("audit_coverage_vy", "mean"),
            coverage_wz=("audit_coverage_wz", "mean"),
        )
        .to_dict(orient="records")
    )
    return {
        "primary_thresholds": {
            "rmse": config.target_rmse,
            "integrated_epistemic_variance": config.target_uncertainty,
        },
        "independent_grids": {
            "candidate_seed": 31013,
            "task_seed": 11003,
            "primary_evaluation_seed": 23011,
            "posthoc_audit_seed": 43019,
        },
        "family_metrics": family_rows,
        "binding_gate_counts": binding_summary.to_dict(orient="index"),
        "disjoint_audit_summary": audit_summary,
        "threshold_sensitivity": sensitivity_rows,
    }


def _p6_analysis() -> dict[str, Any]:
    summary = json.loads(
        (ROOT / "evidence/p6_strong_confirmatory/summary.json").read_text()
    )
    rows = []
    for item in summary["scenarios"]:
        rows.append(
            {
                "scenario": item["scenario"],
                "no_shift_false_alarm_rate": item["no_shift_false_alarm_rate"],
                "no_shift_false_alarm_ci95_lower": item[
                    "no_shift_false_alarm_rate_ci95"
                ][0],
                "no_shift_false_alarm_ci95_upper": item[
                    "no_shift_false_alarm_rate_ci95"
                ][1],
                "detection_rate": item["detection_rate"],
                "detection_ci95_lower": item["detection_rate_ci95"][0],
                "p95_detection_delay_trials": item["p95_detection_delay_trials"],
                "p95_recovery_trials": item["p95_full_recovery_trials"],
            }
        )
    pd.DataFrame(rows).to_csv(OUT / "p6_detector_audit.csv", index=False)
    return {"detector_audit": rows}


def _p7_analysis() -> dict[str, Any]:
    summary = json.loads(
        (ROOT / "evidence/p7_strong_confirmatory_v2/summary.json").read_text()
    )
    matched_rows: list[dict[str, Any]] = []
    planner_hashes: set[str] = set()
    failure_rows: list[dict[str, Any]] = []
    for item in summary["maps"]:
        for method_summary in item["method_summaries"].values():
            planner_hashes.add(str(method_summary["planner_config_sha256"]))
        for baseline, comparison in item["matched_baseline_comparisons"].items():
            matched_rows.append(
                {
                    "map": item["map"],
                    "baseline": baseline,
                    "completion_ratio": comparison[
                        "b8_to_baseline_completion_time_ratio"
                    ],
                    "completion_ratio_ci95_lower": comparison[
                        "b8_to_baseline_completion_time_ratio_ci95"
                    ][0],
                    "completion_ratio_ci95_upper": comparison[
                        "b8_to_baseline_completion_time_ratio_ci95"
                    ][1],
                    "success_difference_ci95_lower": comparison[
                        "b8_minus_baseline_success_ci95"
                    ][0],
                    "success_difference_ci95_upper": comparison[
                        "b8_minus_baseline_success_ci95"
                    ][1],
                    "validation_rmse_reduction": comparison[
                        "b8_vs_baseline_validation_rmse_reduction_mean"
                    ],
                }
            )
        episode_path = (
            ROOT
            / "evidence/p7_strong_confirmatory_v2/maps"
            / item["map"]
            / "episode_metrics.csv"
        )
        episodes = pd.read_csv(episode_path)
        failures = episodes[(episodes["method"] == "B8_full") & (~episodes["success"])]
        for row in failures.to_dict(orient="records"):
            failure_rows.append(
                {
                    "map": row["map"],
                    "seed": int(row["seed"]),
                    "collision": bool(row["collision"]),
                    "completion_time_s": float(row["completion_time_s"]),
                    "final_goal_distance_m": float(row["goal_distance_m"]),
                    "serious_safety_event": bool(row["serious_safety_event"]),
                }
            )
    pd.DataFrame(matched_rows).to_csv(OUT / "p7_matched_controls.csv", index=False)
    pd.DataFrame(failure_rows).to_csv(OUT / "p7_full_failures.csv", index=False)
    trial_duration = 0.50 + 0.30 + 0.60 + 0.70 + 0.50
    return {
        "time_estimand": {
            "name": "60-s capped completion time",
            "failure_value_s": 60.0,
            "arrival_time_is_nan_on_failure": True,
            "primary_time_includes_failures": True,
            "navigation_excludes_calibration": True,
            "calibration_trial_duration_s": trial_duration,
            "full_calibration_time_s": 12 * trial_duration,
            "dense_calibration_time_s": 30 * trial_duration,
        },
        "single_common_planner_hash": len(planner_hashes) == 1,
        "planner_hashes": sorted(planner_hashes),
        "matched_controls": matched_rows,
        "full_failures": failure_rows,
    }


def main() -> None:
    result = {
        "schema_version": "1.0",
        "source_policy": "derived only from immutable P1/P3/P6/P7 evidence",
        "p1": _p1_analysis(),
        "p3": _p3_analysis(),
        "p6": _p6_analysis(),
        "p7": _p7_analysis(),
    }
    (OUT / "reviewer_analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
