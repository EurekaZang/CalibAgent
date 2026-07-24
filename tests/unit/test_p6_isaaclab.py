from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from calibagent.eval.p6_isaaclab import (
    P6BenchmarkConfig,
    _scenario_payload,
    evaluate_p6_summaries,
)


def _summary(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario": scenario["id"],
        "num_seeds": 20,
        "no_shift_false_alarm_rate": 0.0,
        "detection_rate": 1.0,
        "median_detection_delay_trials": 3.0,
        "p95_detection_delay_trials": 4.0,
        "full_recovery_rate": 0.95,
        "median_full_recovery_trials": 7.0,
        "p95_full_recovery_trials": 10.0,
        "recovery_to_dense_budget_ratio": 0.4,
        "full_vs_frozen_final_improvement_ci95": [0.01, 0.04],
        "full_vs_frozen_win_rate": 0.95,
        "valid_observation_ratio": 0.95,
        "serious_safety_events": 0,
        "maximum_abort_latency_s": 0.02,
        "finite": True,
    }


def test_frozen_p6_config_and_gates_pass() -> None:
    config = P6BenchmarkConfig.from_yaml(Path("configs/experiments/p6_domain_shift_main.yaml"))
    summaries = [_summary(item) for item in config.scenarios]

    result = evaluate_p6_summaries(config, summaries)

    assert result["verdict"] == "GO"
    assert all(result["gates"].values())
    payload = _scenario_payload(config, config.scenarios[0], 2, "full")
    assert payload["simulator_seed"] == 780242
    assert payload["methods"] == ["full"]


def test_p6_gates_reject_missed_shift_and_no_effect() -> None:
    config = P6BenchmarkConfig.from_yaml(Path("configs/experiments/p6_domain_shift_main.yaml"))
    summaries = [_summary(item) for item in config.scenarios]
    summaries[0]["detection_rate"] = 0.8
    summaries[0]["full_vs_frozen_final_improvement_ci95"] = [-0.01, 0.02]

    result = evaluate_p6_summaries(config, summaries)

    assert result["verdict"] == "NO_GO"
    assert not result["gates"]["detection_rate"]
    assert not result["gates"]["paired_adaptation_effect"]


def test_p6_allows_earlier_detection_after_three_sample_debounce() -> None:
    config = P6BenchmarkConfig.from_yaml(
        Path("configs/experiments/p6_domain_shift_main.yaml")
    )
    summaries = [_summary(item) for item in config.scenarios]
    summaries[0]["median_detection_delay_trials"] = 2.0

    result = evaluate_p6_summaries(config, summaries)

    assert result["gates"]["detection_delay"]


def test_p6_config_rejects_budget_and_control_changes() -> None:
    config = P6BenchmarkConfig.from_yaml(Path("configs/experiments/p6_domain_shift_main.yaml"))
    trial = dict(config.trial)
    trial["recovery_budget_trials"] = 13
    with pytest.raises(ValueError, match="40%"):
        replace(config, trial=trial).validate()
    with pytest.raises(ValueError, match="controls"):
        replace(config, methods=("frozen", "full")).validate()
