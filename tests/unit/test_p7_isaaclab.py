from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from calibagent.eval.p7_isaaclab import (
    P7BenchmarkConfig,
    _map_payload,
    evaluate_p7_summaries,
)


def _summary(map_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "map": map_config["id"],
        "num_seeds": 20,
        "same_planner": True,
        "b8_success_rate": 0.95,
        "b8_collision_rate": 0.0,
        "b8_vs_b0_completion_time_improvement_ci95_s": [1.0, 2.0],
        "b8_vs_b0_completion_time_win_rate": 0.95,
        "b8_minus_b0_success_ci95": [0.0, 0.15],
        "b0_minus_b8_collision_ci95": [0.0, 0.10],
        "b8_minus_b1_success_ci95": [-0.05, 0.05],
        "b1_minus_b8_collision_ci95": [0.0, 0.05],
        "b8_to_b1_completion_time_ratio_ci95": [0.95, 1.05],
        "b8_to_b1_calibration_budget_ratio": 0.4,
        "minimum_valid_observation_ratio": 0.95,
        "serious_safety_events": 0,
        "maximum_abort_latency_s": 0.02,
        "finite": True,
    }


def test_p7_pilot_config_and_publication_gates() -> None:
    config = P7BenchmarkConfig.from_yaml(Path("configs/experiments/p7_navigation_main.yaml"))
    summaries = [_summary(item) for item in config.maps]

    result = evaluate_p7_summaries(config, summaries)

    assert result["verdict"] == "GO"
    assert all(result["gates"].values())
    payload = _map_payload(config, config.maps[1], 1, "B8_full")
    assert payload["method"] == "B8_full"
    assert payload["simulator_seed"] == 810241
    assert payload["waypoints"] == config.maps[1]["waypoints"]
    assert payload["calibration"]["feature_set"] == "m1_affine"


def test_p7_gates_reject_no_raw_effect_and_dense_regression() -> None:
    config = P7BenchmarkConfig.from_yaml(Path("configs/experiments/p7_navigation_main.yaml"))
    summaries = [_summary(item) for item in config.maps]
    summaries[0]["b8_vs_b0_completion_time_improvement_ci95_s"] = [-0.1, 0.5]
    summaries[1]["b8_to_b1_completion_time_ratio_ci95"] = [1.1, 1.2]

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
    calibration = dict(config.calibration)
    calibration["feature_set"] = "m2_affine_cross_hinge"
    with pytest.raises(ValueError, match="M1 affine"):
        replace(config, calibration=calibration).validate()
