from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from calibagent.eval.p7_isaaclab import (
    P7BenchmarkConfig,
    _as_bool,
    _map_payload,
    _paired_map_summary,
    _write_rows,
    evaluate_p7_summaries,
)


def _summary(map_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "map": map_config["id"],
        "num_seeds": 60,
        "same_planner": True,
        "b8_success_rate": 0.95,
        "b8_collision_rate": 0.0,
        "b8_vs_b0_completion_time_improvement_ci95_s": [1.0, 2.0],
        "b8_vs_b0_completion_time_win_rate": 0.95,
        "b8_minus_b0_success_ci95": [0.0, 0.15],
        "b0_minus_b8_collision_ci95": [0.0, 0.10],
        "b8_minus_b1_success_ci95": [-0.05, 0.05],
        "b1_minus_b8_collision_ci95": [0.0, 0.05],
        "b8_to_b1_mean_completion_time_ratio": 1.05,
        "b8_to_b1_completion_time_ratio_ci95": [0.95, 1.05],
        "b8_to_b1_calibration_budget_ratio": 0.4,
        "minimum_valid_observation_ratio": 0.95,
        "serious_safety_events": 0,
        "maximum_abort_latency_s": 0.02,
        "finite": True,
    }


def test_p7_main_config_and_publication_gates() -> None:
    config = P7BenchmarkConfig.from_yaml(Path("configs/experiments/p7_navigation_main.yaml"))
    summaries = [_summary(item) for item in config.maps]

    result = evaluate_p7_summaries(config, summaries)

    assert result["verdict"] == "GO"
    assert all(result["gates"].values())
    assert config.experiment_role == "main"
    assert len(config.vectorization["seeds"]) == 60
    assert config.vectorization["seeds"] == list(range(8001, 8061))
    payload = _map_payload(config, config.maps[1], 1, "B8_full")
    assert payload["method"] == "B8_full"
    assert payload["simulator_seed"] == 920241
    assert payload["enhanced_determinism"] is True
    assert payload["waypoints"] == config.maps[1]["waypoints"]
    assert payload["calibration"]["feature_set"] == "m1_affine"
    assert payload["calibration"]["model_prior_gain"] == 1.00
    assert payload["calibration"]["active_candidate_source"] == "global_safe_pool"
    assert payload["calibration"]["command_bounds"][0] == [-0.40, 0.40]
    assert payload["navigation"]["inverse_undertracking_confidence_weights"] == [
        1.0,
        0.5,
        0.5,
    ]
    assert payload["navigation"]["inactive_axis_command_limits"] == [
        0.08,
        0.06,
        0.12,
    ]
    assert payload["navigation"]["velocity_feedback"] == {
        "gain": 1.0,
        "ema_alpha": 0.25,
        "maximum_correction": [0.12, 0.08, 0.15],
        "activation_threshold": 0.02,
        "startup_delay_s": 2.0,
        "recovery_reengagement_delay_s": 2.0,
    }
    assert payload["navigation"]["stall_recovery"]["maximum_attempts"] == 3
    assert payload["navigation"]["maximum_linear_accel_mps2"] == 1.0
    assert payload["navigation"]["height_rate_guard"] == {
        "activation_height_m": 0.19,
        "minimum_drop_per_planner_tick_m": 0.003,
        "hold_s": 0.3,
        "maximum_linear_command_norm": 0.28,
    }
    assert payload["navigation"]["stall_recovery"]["emergency_base_height_m"] == 0.16
    assert payload["navigation"]["stall_recovery"]["maximum_emergency_attempts"] == 30


def test_p7_gates_reject_no_raw_effect_and_dense_regression() -> None:
    config = P7BenchmarkConfig.from_yaml(Path("configs/experiments/p7_navigation_main.yaml"))
    summaries = [_summary(item) for item in config.maps]
    summaries[0]["b8_vs_b0_completion_time_improvement_ci95_s"] = [
        -0.1,
        0.5,
    ]
    summaries[1]["b8_to_b1_mean_completion_time_ratio"] = 1.16
    summaries[1]["b8_to_b1_completion_time_ratio_ci95"] = [1.1, 1.26]

    result = evaluate_p7_summaries(config, summaries)

    assert result["verdict"] == "NO_GO"
    assert not result["gates"]["b8_over_raw"]
    assert not result["gates"]["b8_near_dense"]


def test_p7_config_rejects_budget_and_method_changes() -> None:
    config = P7BenchmarkConfig.from_yaml(Path("configs/experiments/p7_navigation_main.yaml"))
    calibration = dict(config.calibration)
    calibration["active_trials"] = 13
    with pytest.raises(ValueError, match="40%"):
        replace(config, calibration=calibration).validate()
    with pytest.raises(ValueError, match="B0/B1/B8"):
        replace(config, methods=("B0_raw", "B8_full")).validate()
    isaaclab = dict(config.isaaclab)
    isaaclab["maximum_startup_attempts"] = 3
    with pytest.raises(ValueError, match="startup-only"):
        replace(config, isaaclab=isaaclab).validate()
    calibration = dict(config.calibration)
    calibration["feature_set"] = "m2_affine_cross_hinge"
    with pytest.raises(ValueError, match="M1 affine"):
        replace(config, calibration=calibration).validate()
    navigation = dict(config.navigation)
    navigation["inverse_undertracking_confidence_weights"] = [0.0, -0.1]
    with pytest.raises(ValueError, match="three nonnegative"):
        replace(config, navigation=navigation).validate()
    isaaclab = dict(config.isaaclab)
    isaaclab["enhanced_determinism"] = False
    with pytest.raises(ValueError, match="enhanced determinism"):
        replace(config, isaaclab=isaaclab).validate()
    calibration = dict(config.calibration)
    calibration["active_candidate_source"] = "task_distribution_support"
    with pytest.raises(ValueError, match="global safe pool"):
        replace(config, calibration=calibration).validate()
    navigation = dict(config.navigation)
    navigation["inactive_axis_command_limits"] = [0.08, 0.0, 0.12]
    with pytest.raises(ValueError, match="three positive"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["velocity_feedback"] = {
        **config.navigation["velocity_feedback"],
        "ema_alpha": 0.0,
    }
    with pytest.raises(ValueError, match="feedback configuration"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["maximum_linear_accel_mps2"] = 0.0
    with pytest.raises(ValueError, match="acceleration limits"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["stall_recovery"] = {
        **config.navigation["stall_recovery"],
        "emergency_base_height_m": config.safety["min_base_height_m"],
    }
    with pytest.raises(ValueError, match="stall recovery configuration"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["height_rate_guard"] = {
        **config.navigation["height_rate_guard"],
        "maximum_linear_command_norm": config.navigation["cruise_speed_mps"],
    }
    with pytest.raises(ValueError, match="height-rate guard"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["height_rate_guard"] = {
        **config.navigation["height_rate_guard"],
        "high_rate_interlock": {
            "enabled": True,
            "activation_height_m": config.safety["min_base_height_m"],
            "release_height_m": 0.23,
            "minimum_clearance_m": 0.01,
            "prediction_steps": 5,
        },
    }
    with pytest.raises(ValueError, match="high-rate height interlock"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["velocity_feedback"] = {
        **config.navigation["velocity_feedback"],
        "recovery_reengagement_delay_s": config.navigation["timeout_s"],
    }
    with pytest.raises(ValueError, match="feedback configuration"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["velocity_feedback"] = {
        **config.navigation["velocity_feedback"],
        "startup_delay_s": config.navigation["timeout_s"],
    }
    with pytest.raises(ValueError, match="feedback configuration"):
        replace(config, navigation=navigation).validate()


def _write_episode_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_p7_map_aggregation_recomputes_paired_intervals(tmp_path: Path) -> None:
    methods = ("B0_raw", "B1_dense", "B8_full")
    completion = {
        "B0_raw": [60.0, 60.0, 60.0],
        "B1_dense": [20.0, 21.0, 22.0],
        "B8_full": [21.0, 21.0, 21.0],
    }
    for method in methods:
        method_dir = tmp_path / method
        method_dir.mkdir()
        summary = {
            "planner_config_sha256": "same-planner",
            "calibration_trials": 30 if method == "B1_dense" else 12,
            "valid_observation_ratio": 0.99,
            "serious_safety_events": 0,
            "maximum_abort_latency_s": 0.0,
            "finite": True,
        }
        (method_dir / "summary.json").write_text(
            json.dumps(summary),
            encoding="utf-8",
        )
        rows = [
            {
                "map": "map",
                "seed": seed,
                "method": method,
                "success": "True" if method != "B0_raw" else "False",
                "collision": "False",
                "completion_time_s": completion[method][index],
            }
            for index, seed in enumerate((1, 2, 3))
        ]
        _write_episode_rows(method_dir / "episode_metrics.csv", rows)

    result = _paired_map_summary({"id": "map"}, tmp_path, 300)

    assert result["num_seeds"] == 3
    assert result["same_planner"] is True
    assert result["b8_success_rate"] == 1.0
    assert result["b8_collision_rate"] == 0.0
    assert result["b8_vs_b0_completion_time_improvement_ci95_s"][0] > 0.0
    assert result["b8_to_b1_calibration_budget_ratio"] == 0.4
    assert len(list(csv.DictReader((tmp_path / "episode_metrics.csv").open()))) == 9


def test_p7_strong_aggregation_includes_budget_matched_controls(
    tmp_path: Path,
) -> None:
    config = P7BenchmarkConfig.from_yaml(
        Path("configs/experiments/p7_navigation_strong_pilot.yaml")
    )
    completion = {
        "B0_raw": 60.0,
        "B1_dense": 20.0,
        "B2_lhs": 22.0,
        "B3_sobol": 21.5,
        "B4_d_opt": 20.5,
        "B5_active_no_task": 21.0,
        "B8_full": 20.5,
    }
    validation = {
        "B0_raw": 0.30,
        "B1_dense": 0.08,
        "B2_lhs": 0.13,
        "B3_sobol": 0.12,
        "B4_d_opt": 0.10,
        "B5_active_no_task": 0.14,
        "B8_full": 0.09,
    }
    for method in config.methods:
        method_dir = tmp_path / method
        method_dir.mkdir()
        trials = 30 if method == "B1_dense" else 0 if method == "B0_raw" else 12
        (method_dir / "summary.json").write_text(
            json.dumps(
                {
                    "planner_config_sha256": "same-planner",
                    "calibration_trials": trials,
                    "valid_observation_ratio": 0.99,
                    "serious_safety_events": 0,
                    "maximum_abort_latency_s": 0.0,
                    "finite": True,
                }
            ),
            encoding="utf-8",
        )
        _write_episode_rows(
            method_dir / "episode_metrics.csv",
            [
                {
                    "map": "map",
                    "seed": seed,
                    "method": method,
                    "success": "False" if method == "B0_raw" else "True",
                    "collision": "False",
                    "completion_time_s": completion[method] + 0.1 * index,
                }
                for index, seed in enumerate((1, 2, 3))
            ],
        )
        _write_episode_rows(
            method_dir / "calibration_validation.csv",
            [
                {
                    "map": "map",
                    "seed": seed,
                    "method": method,
                    "residual_vx": validation[method],
                    "residual_vy": validation[method],
                    "residual_wz": validation[method],
                    "valid": "True",
                }
                for seed in (1, 2, 3)
            ],
        )

    result = _paired_map_summary(
        {"id": "map"},
        tmp_path,
        300,
        config.methods,
    )

    assert set(result["matched_baseline_comparisons"]) == {
        "B2_lhs",
        "B3_sobol",
        "B4_d_opt",
        "B5_active_no_task",
    }
    assert (
        result["matched_baseline_comparisons"]["B5_active_no_task"][
            "b8_vs_baseline_validation_rmse_reduction_ci95"
        ][0]
        > 0.0
    )
    assert result["b8_success_rate_ci95"][0] > 0.0


def test_p7_confirmatory_contract_gates_exact_rates_and_matched_navigation() -> None:
    config = P7BenchmarkConfig.from_yaml(
        Path("configs/experiments/p7_navigation_strong_confirmatory.yaml")
    )
    summaries = []
    for map_config in config.maps:
        item = _summary(map_config)
        item.update(
            {
                "num_seeds": 72,
                "b8_success_rate": 1.0,
                "b8_collision_rate": 0.0,
                "b8_success_rate_ci95": [0.951, 1.0],
                "b8_collision_rate_ci95": [0.0, 0.049],
                "matched_baseline_comparisons": {
                    method: {
                        "calibration_trials": 12,
                        "b8_minus_baseline_success_ci95": [0.0, 0.0],
                        "baseline_minus_b8_collision_ci95": [0.0, 0.0],
                        "b8_to_baseline_completion_time_ratio_ci95": [0.95, 1.10],
                    }
                    for method in (
                        "B2_lhs",
                        "B3_sobol",
                        "B4_d_opt",
                        "B5_active_no_task",
                    )
                },
            }
        )
        summaries.append(item)

    result = evaluate_p7_summaries(config, summaries)

    assert result["verdict"] == "GO"
    assert result["gates"]["b8_exact_rate_bounds"]
    assert result["gates"]["matched_navigation_noninferiority"]
    assert "task_weighted_validation_superiority" not in result["gates"]


def test_p7_csv_helpers_fail_closed_on_invalid_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty P7 aggregate"):
        _write_rows(tmp_path / "empty.csv", [])
    with pytest.raises(ValueError, match="serialized boolean"):
        _as_bool("not-a-boolean")


def test_p7_config_rejects_invalid_map_and_planner_contracts() -> None:
    config = P7BenchmarkConfig.from_yaml(Path("configs/experiments/p7_navigation_main.yaml"))
    vectorization = dict(config.vectorization)
    vectorization["seeds"] = []
    vectorization["num_seeds"] = 0
    with pytest.raises(ValueError, match="non-empty"):
        replace(config, vectorization=vectorization).validate()
    vectorization = dict(config.vectorization)
    vectorization["seeds"] = [8001] * 60
    with pytest.raises(ValueError, match="unique"):
        replace(config, vectorization=vectorization).validate()
    with pytest.raises(ValueError, match="three unique maps"):
        replace(config, maps=config.maps[:2]).validate()
    with pytest.raises(ValueError, match="frozen"):
        replace(config, protocol_frozen_utc="").validate()
    calibration = dict(config.calibration)
    calibration["command_bounds"] = [[0.0, 1.0]] * 3
    with pytest.raises(ValueError, match="straddle zero"):
        replace(config, calibration=calibration).validate()
    calibration = dict(config.calibration)
    calibration["maximum_linear_norm"] = 0.0
    with pytest.raises(ValueError, match="linear norm"):
        replace(config, calibration=calibration).validate()
    navigation = dict(config.navigation)
    navigation["sample_rate_hz"] = 51
    with pytest.raises(ValueError, match="divide"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["goal_radius_m"] = 0.0
    with pytest.raises(ValueError, match="goal radius"):
        replace(config, navigation=navigation).validate()
    navigation = dict(config.navigation)
    navigation["task_commands"] = [[0.1, 0.0, 0.0]]
    with pytest.raises(ValueError, match="task support"):
        replace(config, navigation=navigation).validate()
    map_config = dict(config.maps[0])
    map_config["waypoints"] = []
    with pytest.raises(ValueError, match="waypoints"):
        replace(config, maps=(map_config, *config.maps[1:])).validate()
    map_config = dict(config.maps[1])
    map_config["obstacles"] = [{"center": [0.0, 0.0], "size": [-1.0, 1.0, 1.0]}]
    with pytest.raises(ValueError, match="obstacle sizes"):
        replace(config, maps=(config.maps[0], map_config, config.maps[2])).validate()
