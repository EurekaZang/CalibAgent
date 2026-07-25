"""Pinned Isaac Lab P7 downstream-navigation benchmark."""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray

from calibagent.eval.metrics import clopper_pearson_interval
from calibagent.eval.p5_isaaclab import (
    _artifact_manifest,
    _checkpoint_path,
    _git_value,
    _require_clean_repository,
    _run,
    _runtime_metadata,
)
from calibagent.eval.real_replay import file_sha256

_LEGACY_METHODS = ("B0_raw", "B1_dense", "B8_full")
_MATCHED_METHODS = (
    "B2_lhs",
    "B3_sobol",
    "B4_d_opt",
    "B5_active_no_task",
)
_STRONG_METHODS = (
    "B0_raw",
    "B1_dense",
    *_MATCHED_METHODS,
    "B8_full",
)


@dataclass(frozen=True)
class P7BenchmarkConfig:
    output_dir: str
    isaaclab: dict[str, Any]
    vectorization: dict[str, Any]
    methods: tuple[str, ...]
    calibration: dict[str, Any]
    navigation: dict[str, Any]
    safety: dict[str, Any]
    checkpoints: dict[str, dict[str, str]]
    maps: tuple[dict[str, Any], ...]
    publication_gates: dict[str, Any]
    experiment_role: str
    protocol_frozen_utc: str

    @classmethod
    def from_yaml(cls, path: Path) -> P7BenchmarkConfig:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("P7 benchmark config must be a mapping")
        config = cls(
            output_dir=str(payload["output_dir"]),
            isaaclab=dict(payload["isaaclab"]),
            vectorization=dict(payload["vectorization"]),
            methods=tuple(str(item) for item in payload["methods"]),
            calibration=dict(payload["calibration"]),
            navigation=dict(payload["navigation"]),
            safety=dict(payload["safety"]),
            checkpoints={
                str(name): dict(value) for name, value in dict(payload["checkpoints"]).items()
            },
            maps=tuple(dict(item) for item in payload["maps"]),
            publication_gates=dict(payload["publication_gates"]),
            experiment_role=str(payload["experiment_role"]),
            protocol_frozen_utc=str(payload["protocol_frozen_utc"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        seeds = [int(item) for item in self.vectorization["seeds"]]
        map_ids = [str(item["id"]) for item in self.maps]
        if len(seeds) != int(self.vectorization["num_seeds"]) or not seeds:
            raise ValueError("P7 num_seeds must match a non-empty seed list")
        if len(seeds) != len(set(seeds)):
            raise ValueError("P7 seeds must be unique")
        if self.methods not in {_LEGACY_METHODS, _STRONG_METHODS}:
            raise ValueError(
                "P7 requires either frozen B0/B1/B8 controls or the complete strong controls"
            )
        if len(map_ids) != len(set(map_ids)) or len(map_ids) < 3:
            raise ValueError("P7 requires at least three unique maps")
        if self.experiment_role not in {"pilot", "main", "confirmatory"} or (
            self.experiment_role in {"main", "confirmatory"}
            and (
                not self.protocol_frozen_utc
                or len(seeds) < int(self.publication_gates["minimum_seeds_per_map"])
            )
        ):
            raise ValueError("P7 main runs require a frozen, fully covered protocol")
        if int(self.isaaclab["maximum_startup_attempts"]) not in {1, 2}:
            raise ValueError("P7 permits at most one startup-only retry")
        if self.isaaclab.get("enhanced_determinism") is not True:
            raise ValueError("P7 requires PhysX enhanced determinism")
        dense = int(self.calibration["dense_trials"])
        active = int(self.calibration["active_trials"])
        if str(self.calibration["feature_set"]) != "m1_affine":
            raise ValueError("P7 affine navigation requires the frozen M1 affine model")
        if not 0.0 < float(self.calibration["model_prior_gain"]) <= 1.0:
            raise ValueError("P7 model prior gain must be in (0, 1]")
        command_bounds = np.asarray(self.calibration["command_bounds"], dtype=np.float64)
        if (
            command_bounds.shape != (3, 2)
            or np.any(command_bounds[:, 0] >= 0.0)
            or np.any(command_bounds[:, 1] <= 0.0)
        ):
            raise ValueError("P7 command bounds must have shape (3, 2) and straddle zero")
        if float(self.calibration["maximum_linear_norm"]) <= 0.0:
            raise ValueError("P7 maximum linear norm must be positive")
        if active > 0.40 * dense:
            raise ValueError("P7 B8 calibration budget exceeds 40% of B1")
        if str(self.calibration["active_candidate_source"]) != "global_safe_pool":
            raise ValueError("P7 active candidates must use the frozen global safe pool")
        if self.methods == _STRONG_METHODS:
            required_design_seeds = {"lhs_design_seed", "sobol_design_seed"}
            if not required_design_seeds <= set(self.calibration):
                raise ValueError("P7 strong controls require frozen LHS/Sobol design seeds")
            validation_commands = np.asarray(
                self.calibration.get("validation_commands", []),
                dtype=np.float64,
            )
            if (
                validation_commands.ndim != 2
                or validation_commands.shape[1:] != (3,)
                or len(validation_commands) < 6
                or len(np.unique(validation_commands, axis=0)) != len(validation_commands)
                or not np.all(np.isfinite(validation_commands))
                or np.any(validation_commands < command_bounds[:, 0])
                or np.any(validation_commands > command_bounds[:, 1])
                or np.any(
                    np.linalg.norm(validation_commands[:, :2], axis=1)
                    > float(self.calibration["maximum_linear_norm"])
                )
            ):
                raise ValueError("P7 strong controls require unique held-out validation commands")
        if int(self.navigation["sample_rate_hz"]) % int(self.navigation["planner_rate_hz"]):
            raise ValueError("P7 planner rate must divide the sample rate")
        if float(self.navigation["goal_radius_m"]) <= 0.0:
            raise ValueError("P7 goal radius must be positive")
        if (
            float(self.navigation["maximum_linear_accel_mps2"]) <= 0.0
            or float(self.navigation["maximum_angular_accel_rps2"]) <= 0.0
        ):
            raise ValueError("P7 command acceleration limits must be positive")
        confidence_weights = np.asarray(
            self.navigation["inverse_undertracking_confidence_weights"],
            dtype=np.float64,
        )
        if (
            confidence_weights.shape != (3,)
            or not np.all(np.isfinite(confidence_weights))
            or np.any(confidence_weights < 0.0)
        ):
            raise ValueError("P7 inverse confidence weights must contain three nonnegative values")
        inactive_limits = np.asarray(
            self.navigation["inactive_axis_command_limits"],
            dtype=np.float64,
        )
        if (
            inactive_limits.shape != (3,)
            or np.any(np.isnan(inactive_limits))
            or np.any(inactive_limits <= 0.0)
        ):
            raise ValueError("P7 inactive-axis limits must contain three positive values")
        velocity_feedback = dict(self.navigation["velocity_feedback"])
        maximum_correction = np.asarray(
            velocity_feedback["maximum_correction"],
            dtype=np.float64,
        )
        if (
            float(velocity_feedback["gain"]) < 0.0
            or not 0.0 < float(velocity_feedback["ema_alpha"]) <= 1.0
            or maximum_correction.shape != (3,)
            or not np.all(np.isfinite(maximum_correction))
            or np.any(maximum_correction < 0.0)
            or float(velocity_feedback["activation_threshold"]) < 0.0
            or float(velocity_feedback["startup_delay_s"]) < 0.0
            or float(velocity_feedback["startup_delay_s"]) >= float(self.navigation["timeout_s"])
            or float(velocity_feedback["recovery_reengagement_delay_s"]) < 0.0
            or float(velocity_feedback["recovery_reengagement_delay_s"])
            >= float(self.navigation["timeout_s"])
        ):
            raise ValueError("P7 velocity feedback configuration is invalid")
        height_rate_guard = dict(self.navigation["height_rate_guard"])
        if (
            float(height_rate_guard["activation_height_m"])
            < float(self.safety["min_base_height_m"]) + 0.02
            or float(height_rate_guard["activation_height_m"])
            >= float(self.safety["max_base_height_m"])
            or float(height_rate_guard["minimum_drop_per_planner_tick_m"]) <= 0.0
            or float(height_rate_guard["hold_s"]) <= 0.0
            or float(height_rate_guard["maximum_linear_command_norm"])
            <= float(self.navigation["cruise_speed_mps"])
            or float(height_rate_guard["maximum_linear_command_norm"])
            > float(self.calibration["maximum_linear_norm"])
        ):
            raise ValueError("P7 height-rate guard configuration is invalid")
        high_rate_interlock = height_rate_guard.get("high_rate_interlock")
        if high_rate_interlock is not None:
            interlock = dict(high_rate_interlock)
            minimum_projected_height = float(self.safety["min_base_height_m"]) + float(
                interlock["minimum_clearance_m"]
            )
            if (
                interlock.get("enabled") is not True
                or float(interlock["activation_height_m"])
                <= minimum_projected_height
                or float(interlock["release_height_m"])
                <= float(interlock["activation_height_m"])
                or float(interlock["release_height_m"])
                >= float(self.safety["max_base_height_m"])
                or int(interlock["prediction_steps"]) < 1
                or float(interlock["minimum_clearance_m"]) < 0.0
            ):
                raise ValueError("P7 high-rate height interlock configuration is invalid")
        task_commands = np.asarray(self.navigation["task_commands"], dtype=np.float64)
        if (
            task_commands.ndim != 2
            or task_commands.shape[1] != 3
            or len(task_commands) < active - 6
            or len(np.unique(task_commands, axis=0)) != len(task_commands)
            or not np.all(np.isfinite(task_commands))
            or np.any(task_commands < command_bounds[:, 0])
            or np.any(task_commands > command_bounds[:, 1])
            or np.any(
                np.linalg.norm(task_commands[:, :2], axis=1)
                > float(self.calibration["maximum_linear_norm"])
            )
        ):
            raise ValueError("P7 task support must provide unique, finite, safe active candidates")
        recovery = dict(self.navigation["stall_recovery"])
        if (
            float(recovery["minimum_desired_speed_mps"]) <= 0.0
            or float(recovery["maximum_actual_speed_mps"]) <= 0.0
            or float(recovery["maximum_base_height_m"]) <= float(self.safety["min_base_height_m"])
            or float(recovery["emergency_base_height_m"]) <= float(self.safety["min_base_height_m"])
            or float(recovery["emergency_base_height_m"])
            >= float(recovery["maximum_base_height_m"])
            or float(recovery["detection_s"]) <= 0.0
            or float(recovery["zero_command_s"]) <= 0.0
            or float(recovery["emergency_zero_command_s"]) <= 0.0
            or int(recovery["maximum_attempts"]) < 1
            or int(recovery["maximum_emergency_attempts"]) < 1
        ):
            raise ValueError("P7 stall recovery configuration is invalid")
        for map_config in self.maps:
            if str(map_config["checkpoint"]) not in self.checkpoints:
                raise ValueError("P7 map uses an unknown checkpoint")
            if not list(map_config["waypoints"]):
                raise ValueError("P7 map must contain waypoints")
            for obstacle in list(map_config["obstacles"]):
                if any(float(value) <= 0.0 for value in obstacle["size"]):
                    raise ValueError("P7 obstacle sizes must be positive")


def _bootstrap_interval(
    count: int,
    seed: int,
    statistic: Callable[[NDArray[np.int64]], float],
) -> list[float]:
    rng = np.random.default_rng(seed)
    values = np.empty(4000, dtype=np.float64)
    for index in range(len(values)):
        sample = rng.integers(0, count, size=count)
        values[index] = statistic(sample)
    return [
        float(np.quantile(values, 0.025)),
        float(np.quantile(values, 0.975)),
    ]


def _as_bool(value: str) -> bool:
    if value not in {"True", "False"}:
        raise ValueError(f"invalid serialized boolean: {value}")
    return value == "True"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty P7 aggregate: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _paired_map_summary(
    map_config: dict[str, Any],
    map_output: Path,
    simulator_seed: int,
    methods: tuple[str, ...] = _LEGACY_METHODS,
) -> dict[str, Any]:
    method_summaries = {
        method: json.loads((map_output / method / "summary.json").read_text(encoding="utf-8"))
        for method in methods
    }
    rows = [
        row
        for method in methods
        for row in _read_rows(map_output / method / "episode_metrics.csv")
    ]
    _write_rows(map_output / "episode_metrics.csv", rows)
    indexed = {(str(row["method"]), int(row["seed"])): row for row in rows}
    seeds = sorted(int(row["seed"]) for row in rows if row["method"] == "B8_full")
    if any((method, seed) not in indexed for method in methods for seed in seeds):
        raise ValueError("P7 paired method/seed coverage is incomplete")

    def array(method: str, field: str) -> NDArray[np.float64]:
        return np.asarray(
            [float(indexed[(method, seed)][field]) for seed in seeds],
            dtype=np.float64,
        )

    def binary(method: str, field: str) -> NDArray[np.float64]:
        return np.asarray(
            [float(_as_bool(indexed[(method, seed)][field])) for seed in seeds],
            dtype=np.float64,
        )

    b0_time = array("B0_raw", "completion_time_s")
    b1_time = array("B1_dense", "completion_time_s")
    b8_time = array("B8_full", "completion_time_s")
    b0_success = binary("B0_raw", "success")
    b1_success = binary("B1_dense", "success")
    b8_success = binary("B8_full", "success")
    b0_collision = binary("B0_raw", "collision")
    b1_collision = binary("B1_dense", "collision")
    b8_collision = binary("B8_full", "collision")
    count = len(seeds)
    time_improvement = b0_time - b8_time
    success_count = int(np.sum(b8_success))
    collision_count = int(np.sum(b8_collision))
    b8_to_b1_ratio = _bootstrap_interval(
        count,
        simulator_seed + 701,
        lambda sample: float(np.mean(b8_time[sample]) / max(np.mean(b1_time[sample]), 1e-12)),
    )

    def difference_interval(
        left: NDArray[np.float64],
        right: NDArray[np.float64],
        offset: int,
    ) -> list[float]:
        return _bootstrap_interval(
            count,
            simulator_seed + offset,
            lambda sample: float(np.mean(left[sample] - right[sample])),
        )

    def ratio_statistic(
        numerator: NDArray[np.float64],
        denominator: NDArray[np.float64],
    ) -> Callable[[NDArray[np.int64]], float]:
        def statistic(sample: NDArray[np.int64]) -> float:
            return float(
                np.mean(numerator[sample])
                / max(float(np.mean(denominator[sample])), 1e-12)
            )

        return statistic

    def mean_statistic(
        values: NDArray[np.float64],
    ) -> Callable[[NDArray[np.int64]], float]:
        def statistic(sample: NDArray[np.int64]) -> float:
            return float(np.mean(values[sample]))

        return statistic

    planner_hashes = {
        str(summary["planner_config_sha256"]) for summary in method_summaries.values()
    }
    matched_comparisons: dict[str, dict[str, Any]] = {}
    validation_rmse: dict[tuple[str, int], float] = {}
    if methods == _STRONG_METHODS:
        validation_rows = [
            row
            for method in methods
            for row in _read_rows(map_output / method / "calibration_validation.csv")
        ]
        _write_rows(map_output / "calibration_validation.csv", validation_rows)
        validation_frame: dict[tuple[str, int], list[float]] = {}
        for row in validation_rows:
            if not _as_bool(row["valid"]):
                continue
            key = (str(row["method"]), int(row["seed"]))
            squared = sum(
                float(row[field]) ** 2
                for field in ("residual_vx", "residual_vy", "residual_wz")
            )
            validation_frame.setdefault(key, []).append(squared / 3.0)
        if any(
            (method, seed) not in validation_frame
            for method in methods
            for seed in seeds
        ):
            raise ValueError("P7 calibration-validation coverage is incomplete")
        validation_rmse = {
            key: float(np.sqrt(np.mean(values)))
            for key, values in validation_frame.items()
        }
        b8_validation = np.asarray(
            [validation_rmse[("B8_full", seed)] for seed in seeds],
            dtype=np.float64,
        )
        for offset, method in enumerate(_MATCHED_METHODS):
            baseline_time = array(method, "completion_time_s")
            baseline_success = binary(method, "success")
            baseline_collision = binary(method, "collision")
            baseline_validation = np.asarray(
                [validation_rmse[(method, seed)] for seed in seeds],
                dtype=np.float64,
            )
            validation_reduction = 1.0 - b8_validation / np.maximum(
                baseline_validation,
                1e-12,
            )

            matched_comparisons[method] = {
                "calibration_trials": int(method_summaries[method]["calibration_trials"]),
                "b8_minus_baseline_success_ci95": difference_interval(
                    b8_success,
                    baseline_success,
                    811 + 20 * offset,
                ),
                "baseline_minus_b8_collision_ci95": difference_interval(
                    baseline_collision,
                    b8_collision,
                    817 + 20 * offset,
                ),
                "b8_to_baseline_completion_time_ratio": float(
                    np.mean(b8_time) / max(float(np.mean(baseline_time)), 1e-12)
                ),
                "b8_to_baseline_completion_time_ratio_ci95": _bootstrap_interval(
                    count,
                    simulator_seed + 823 + 20 * offset,
                    ratio_statistic(b8_time, baseline_time),
                ),
                "b8_vs_baseline_validation_rmse_reduction_mean": float(
                    np.mean(validation_reduction)
                ),
                "b8_vs_baseline_validation_rmse_reduction_ci95": _bootstrap_interval(
                    count,
                    simulator_seed + 829 + 20 * offset,
                    mean_statistic(validation_reduction),
                ),
                "b8_vs_baseline_validation_rmse_win_rate": float(
                    np.mean(validation_reduction > 0.0)
                ),
            }
    result = {
        "schema_version": "1.0",
        "map": str(map_config["id"]),
        "num_seeds": count,
        "methods": list(methods),
        "planner_config_sha256": next(iter(planner_hashes)) if len(planner_hashes) == 1 else "",
        "same_planner": len(planner_hashes) == 1,
        "b0_success_rate": float(np.mean(b0_success)),
        "b1_success_rate": float(np.mean(b1_success)),
        "b8_success_rate": float(np.mean(b8_success)),
        "b8_success_rate_ci95": list(
            clopper_pearson_interval(success_count, count)
        ),
        "b0_collision_rate": float(np.mean(b0_collision)),
        "b1_collision_rate": float(np.mean(b1_collision)),
        "b8_collision_rate": float(np.mean(b8_collision)),
        "b8_collision_rate_ci95": list(
            clopper_pearson_interval(collision_count, count)
        ),
        "b0_mean_completion_time_s": float(np.mean(b0_time)),
        "b1_mean_completion_time_s": float(np.mean(b1_time)),
        "b8_mean_completion_time_s": float(np.mean(b8_time)),
        "b8_to_b1_mean_completion_time_ratio": float(
            float(np.mean(b8_time)) / max(float(np.mean(b1_time)), 1e-12)
        ),
        "b8_vs_b0_completion_time_improvement_mean_s": float(np.mean(time_improvement)),
        "b8_vs_b0_completion_time_improvement_ci95_s": _bootstrap_interval(
            count,
            simulator_seed + 703,
            lambda sample: float(np.mean(time_improvement[sample])),
        ),
        "b8_vs_b0_completion_time_win_rate": float(np.mean(time_improvement > 0.0)),
        "b8_minus_b0_success_ci95": difference_interval(b8_success, b0_success, 709),
        "b0_minus_b8_collision_ci95": difference_interval(b0_collision, b8_collision, 719),
        "b8_minus_b1_success_ci95": difference_interval(b8_success, b1_success, 727),
        "b1_minus_b8_collision_ci95": difference_interval(b1_collision, b8_collision, 733),
        "b8_to_b1_completion_time_ratio_ci95": b8_to_b1_ratio,
        "b8_to_b1_calibration_budget_ratio": float(
            method_summaries["B8_full"]["calibration_trials"]
            / method_summaries["B1_dense"]["calibration_trials"]
        ),
        "b8_calibration_validation_rmse": (
            float(
                np.mean(
                    [validation_rmse[("B8_full", seed)] for seed in seeds]
                )
            )
            if validation_rmse
            else None
        ),
        "matched_baseline_comparisons": matched_comparisons,
        "minimum_valid_observation_ratio": min(
            float(item["valid_observation_ratio"]) for item in method_summaries.values()
        ),
        "serious_safety_events": sum(
            int(item["serious_safety_events"]) for item in method_summaries.values()
        ),
        "maximum_abort_latency_s": max(
            float(item["maximum_abort_latency_s"]) for item in method_summaries.values()
        ),
        "finite": bool(
            all(bool(item["finite"]) for item in method_summaries.values())
            and np.all(
                np.isfinite(
                    np.concatenate(
                        [
                            array(method, "completion_time_s")
                            for method in methods
                        ]
                    )
                )
            )
            and all(np.isfinite(value) for value in validation_rmse.values())
        ),
        "method_summaries": method_summaries,
    }
    (map_output / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


def evaluate_p7_summaries(
    config: P7BenchmarkConfig,
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    gates = config.publication_gates
    expected = {str(item["id"]) for item in config.maps}
    actual = {str(item["map"]) for item in summaries}
    checks = {
        "map_identity": actual == expected,
        "minimum_maps": len(summaries) >= int(gates["minimum_maps"]),
        "seed_coverage": all(
            int(item["num_seeds"]) >= int(gates["minimum_seeds_per_map"]) for item in summaries
        ),
        "same_planner": all(bool(item["same_planner"]) for item in summaries),
        "b8_task_success": all(
            float(item["b8_success_rate"]) >= float(gates["minimum_b8_success_rate"])
            and float(item["b8_collision_rate"]) <= float(gates["maximum_b8_collision_rate"])
            for item in summaries
        ),
        "b8_over_raw": all(
            float(item["b8_vs_b0_completion_time_improvement_ci95_s"][0])
            > float(gates["minimum_b8_vs_b0_time_improvement_ci95_lower_s"])
            and float(item["b8_vs_b0_completion_time_win_rate"])
            >= float(gates["minimum_b8_vs_b0_time_win_rate"])
            and float(item["b8_minus_b0_success_ci95"][0])
            >= -float(gates["maximum_success_rate_noninferiority_margin"])
            and float(item["b0_minus_b8_collision_ci95"][0])
            >= -float(gates["maximum_collision_rate_noninferiority_margin"])
            for item in summaries
        ),
        "b8_near_dense": all(
            float(item["b8_minus_b1_success_ci95"][0])
            >= -float(gates["maximum_success_rate_noninferiority_margin"])
            and float(item["b1_minus_b8_collision_ci95"][0])
            >= -float(gates["maximum_collision_rate_noninferiority_margin"])
            and float(item["b8_to_b1_mean_completion_time_ratio"])
            <= float(gates["maximum_b8_to_b1_mean_completion_time_ratio"])
            and float(item["b8_to_b1_completion_time_ratio_ci95"][1])
            <= float(gates["maximum_b8_to_b1_completion_time_ratio_ci95_upper"])
            for item in summaries
        ),
        "calibration_budget": all(
            float(item["b8_to_b1_calibration_budget_ratio"])
            <= float(gates["maximum_b8_to_b1_calibration_budget_ratio"])
            for item in summaries
        ),
        "valid_observations": all(
            float(item["minimum_valid_observation_ratio"])
            >= float(gates["minimum_valid_observation_ratio"])
            for item in summaries
        ),
        "safety": (
            sum(int(item["serious_safety_events"]) for item in summaries)
            <= int(gates["maximum_serious_safety_events"])
            and max(
                (float(item["maximum_abort_latency_s"]) for item in summaries),
                default=0.0,
            )
            <= float(gates["maximum_abort_latency_s"])
        ),
        "finite": all(bool(item["finite"]) for item in summaries),
    }
    if "minimum_b8_success_rate_ci95_lower" in gates:
        checks["b8_exact_rate_bounds"] = all(
            float(item["b8_success_rate_ci95"][0])
            >= float(gates["minimum_b8_success_rate_ci95_lower"])
            and float(item["b8_collision_rate_ci95"][1])
            <= float(gates["maximum_b8_collision_rate_ci95_upper"])
            for item in summaries
        )
    required_matched = tuple(
        str(method) for method in gates.get("required_matched_baselines", [])
    )
    if required_matched:
        checks["matched_baseline_coverage"] = (
            config.methods == _STRONG_METHODS
            and required_matched == _MATCHED_METHODS
            and all(
                set(item["matched_baseline_comparisons"]) == set(required_matched)
                and all(
                    int(item["matched_baseline_comparisons"][method]["calibration_trials"])
                    == int(config.calibration["active_trials"])
                    for method in required_matched
                )
                for item in summaries
            )
        )
        checks["matched_navigation_noninferiority"] = all(
            float(comparison["b8_minus_baseline_success_ci95"][0])
            >= -float(gates["maximum_success_rate_noninferiority_margin"])
            and float(comparison["baseline_minus_b8_collision_ci95"][0])
            >= -float(gates["maximum_collision_rate_noninferiority_margin"])
            and float(comparison["b8_to_baseline_completion_time_ratio_ci95"][1])
            <= float(gates["maximum_b8_to_matched_time_ratio_ci95_upper"])
            for item in summaries
            for comparison in item["matched_baseline_comparisons"].values()
        )
        superiority_methods = tuple(
            str(method)
            for method in gates.get("validation_superiority_methods", [])
        )
        noninferiority_methods = tuple(
            str(method)
            for method in gates.get("validation_noninferiority_methods", [])
        )
        if superiority_methods:
            checks["task_weighted_validation_superiority"] = all(
                float(
                    item["matched_baseline_comparisons"][method][
                        "b8_vs_baseline_validation_rmse_reduction_ci95"
                    ][0]
                )
                > float(gates["minimum_validation_rmse_reduction_ci95_lower"])
                for item in summaries
                for method in superiority_methods
            )
        if noninferiority_methods:
            checks["strong_validation_noninferiority"] = all(
                float(
                    item["matched_baseline_comparisons"][method][
                        "b8_vs_baseline_validation_rmse_reduction_ci95"
                    ][0]
                )
                >= -float(gates["maximum_validation_rmse_noninferiority_margin"])
                for item in summaries
                for method in noninferiority_methods
            )
    return {
        "schema_version": "1.0",
        "phase": "P7",
        "verdict": "GO" if summaries and all(checks.values()) else "NO_GO",
        "map_count": len(summaries),
        "minimum_b8_success_rate": min(
            (float(item["b8_success_rate"]) for item in summaries), default=0.0
        ),
        "maximum_b8_collision_rate": max(
            (float(item["b8_collision_rate"]) for item in summaries), default=1.0
        ),
        "minimum_b8_vs_b0_time_improvement_ci95_lower_s": min(
            (float(item["b8_vs_b0_completion_time_improvement_ci95_s"][0]) for item in summaries),
            default=float("-inf"),
        ),
        "maximum_b8_to_b1_time_ratio_ci95_upper": max(
            (float(item["b8_to_b1_completion_time_ratio_ci95"][1]) for item in summaries),
            default=float("inf"),
        ),
        "maximum_b8_to_b1_mean_completion_time_ratio": max(
            (float(item["b8_to_b1_mean_completion_time_ratio"]) for item in summaries),
            default=float("inf"),
        ),
        "total_serious_safety_events": sum(
            int(item["serious_safety_events"]) for item in summaries
        ),
        "maps": summaries,
        "gates": checks,
    }


def _map_payload(
    config: P7BenchmarkConfig,
    map_config: dict[str, Any],
    index: int,
    method: str,
) -> dict[str, Any]:
    return {
        **map_config,
        "method": method,
        "seeds": [int(item) for item in config.vectorization["seeds"]],
        "simulator_seed": int(config.vectorization["simulator_seed"]) + index,
        "enhanced_determinism": bool(config.isaaclab["enhanced_determinism"]),
        "calibration": config.calibration,
        "navigation": config.navigation,
        "safety": config.safety,
    }


def run_p7_suite(
    config_path: Path,
    workspace: Path,
    isaaclab_root: Path,
    checkpoint_cache: Path,
) -> dict[str, Any]:
    root = workspace.resolve()
    isaaclab = isaaclab_root.resolve()
    config = P7BenchmarkConfig.from_yaml(config_path.resolve())
    output = (root / config.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty P7 output: {output}")
    _require_clean_repository(root, "CalibAgent")
    _require_clean_repository(isaaclab, "Isaac Lab")
    runtime = _runtime_metadata(isaaclab, root)
    if _git_value(isaaclab, "rev-parse", "HEAD") != str(config.isaaclab["commit"]):
        raise RuntimeError("Isaac Lab commit does not match the frozen P7 config")
    if not str(runtime["isaac_sim_version"]).startswith(
        str(config.isaaclab["isaac_sim_version_prefix"])
    ):
        raise RuntimeError("Isaac Sim version does not match the frozen P7 config")
    checkpoints = {
        alias: _checkpoint_path(alias, specification, checkpoint_cache.resolve())
        for alias, specification in config.checkpoints.items()
    }
    output.mkdir(parents=True, exist_ok=True)
    resolved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    (output / "resolved_config.json").write_text(
        json.dumps(resolved, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    source_paths = [
        isaaclab / "source" / "isaaclab",
        isaaclab / "source" / "isaaclab_assets",
        isaaclab / "source" / "isaaclab_tasks",
        isaaclab / "source" / "isaaclab_rl",
        isaaclab / "source" / "isaaclab_mimic",
        root / "src",
        root / "sim" / "isaaclab",
    ]
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    environment["TERM"] = "xterm-256color"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in source_paths)
    summaries: list[dict[str, Any]] = []
    for index, map_config in enumerate(config.maps):
        map_id = str(map_config["id"])
        map_output = output / "maps" / map_id
        map_output.mkdir(parents=True)
        for method in config.methods:
            method_output = map_output / method
            method_output.mkdir()
            payload_path = method_output / "launch_config.json"
            payload_path.write_text(
                json.dumps(
                    _map_payload(config, map_config, index, method),
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            command_prefix = [
                str(isaaclab / "isaaclab.sh"),
                "-p",
                str(root / "sim" / "isaaclab" / "scripts" / "run_p7_navigation.py"),
                "--scenario-config",
                str(payload_path),
                "--checkpoint",
                str(checkpoints[str(map_config["checkpoint"])]),
                "--output",
                str(method_output),
                "--headless",
            ]
            required = (
                "summary.json",
                "episode_metrics.csv",
                "calibration_metrics.csv",
                *(
                    ("calibration_validation.csv",)
                    if config.methods == _STRONG_METHODS
                    else ()
                ),
                "nav_trace.csv.gz",
                "posterior_state.npz",
                "distortion_parameters.json",
                "map_geometry.json",
                "scenario_config.json",
            )
            attempts: list[dict[str, Any]] = []
            logs: list[str] = []
            maximum_attempts = int(config.isaaclab["maximum_startup_attempts"])
            returncode = -1
            missing = list(required)
            for attempt in range(1, maximum_attempts + 1):
                command = [
                    *command_prefix,
                    (
                        "--kit_args=--portable-root="
                        f"/tmp/calibagent_kit_p7_{map_id}_{method}_{attempt}"
                    ),
                ]
                result = _run(command, cwd=root, env=environment, check=False)
                returncode = result.returncode
                missing = [name for name in required if not (method_output / name).is_file()]
                logs.append(
                    f"===== STARTUP ATTEMPT {attempt} =====\n" + result.stdout + result.stderr
                )
                attempts.append(
                    {
                        "attempt": attempt,
                        "command": command,
                        "returncode": result.returncode,
                        "missing_required_artifacts": missing,
                    }
                )
                if result.returncode == 0 and not missing:
                    break
                # A retry is allowed only when the simulator died before
                # producing any scientific artifact. Partial runs are evidence,
                # not startup failures, and must fail closed.
                if any((method_output / name).is_file() for name in required):
                    break
            (method_output / "launch_command.json").write_text(
                json.dumps(attempts[0]["command"], indent=2),
                encoding="utf-8",
            )
            (method_output / "launch_attempts.json").write_text(
                json.dumps(attempts, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            (method_output / "simulator.log").write_text(
                "\n".join(logs),
                encoding="utf-8",
            )
            if returncode != 0 or missing:
                raise RuntimeError(
                    f"P7 map {map_id}/{method} failed "
                    f"(returncode={returncode}, missing={missing}); "
                    f"see {method_output / 'simulator.log'}"
                )
        summaries.append(
                _paired_map_summary(
                    map_config,
                    map_output,
                    int(config.vectorization["simulator_seed"]) + index,
                    config.methods,
                )
        )
    aggregate = evaluate_p7_summaries(config, summaries)
    aggregate["runtime"] = runtime
    (output / "summary.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "phase": "P7",
        "backend": "isaaclab_physx_go2_fixed_planner_navigation",
        "git_commit": _git_value(root, "rev-parse", "HEAD"),
        "config_path": str(config_path.resolve().relative_to(root)),
        "config_sha256": file_sha256(config_path),
        "runtime": runtime,
        "checkpoints": {
            alias: {
                "url": specification["url"],
                "sha256": file_sha256(checkpoints[alias]),
            }
            for alias, specification in config.checkpoints.items()
        },
        "artifacts": _artifact_manifest(output),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return aggregate
