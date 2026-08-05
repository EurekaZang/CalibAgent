from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from calibagent.eval.p6_isaaclab import (
    _REQUIRED_METHOD_ARTIFACTS,
    P6BenchmarkConfig,
    _aggregate_method_outputs,
    _as_bool,
    _method_artifacts_complete,
    _scenario_payload,
    _write_csv_rows,
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
    assert payload["simulator_seed"] == 790242
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
    config = P6BenchmarkConfig.from_yaml(Path("configs/experiments/p6_domain_shift_main.yaml"))
    summaries = [_summary(item) for item in config.scenarios]
    summaries[0]["median_detection_delay_trials"] = 2.0

    result = evaluate_p6_summaries(config, summaries)

    assert result["gates"]["detection_delay"]


def test_p6_strong_gates_require_active_over_passive_and_exact_rates() -> None:
    config = P6BenchmarkConfig.from_yaml(
        Path("configs/experiments/p6_domain_shift_strong_pilot.yaml")
    )
    summaries = []
    for scenario in config.scenarios:
        item = _summary(scenario)
        item.update(
            {
                "num_seeds": 8,
                "no_shift_false_alarm_rate_ci95": [0.0, 0.20],
                "detection_rate_ci95": [0.80, 1.0],
                "full_recovery_rate_ci95": [0.80, 1.0],
                "full_vs_passive_early_rmse_improvement_ci95": [0.01, 0.03],
                "full_vs_passive_early_rmse_wilcoxon_one_sided_p": 0.01,
                "full_minus_passive_final_rmse_ci95": [-0.01, 0.01],
            }
        )
        summaries.append(item)

    result = evaluate_p6_summaries(config, summaries)

    assert result["verdict"] == "GO"
    assert result["gates"]["active_over_passive_early_recovery"]
    assert result["gates"]["active_terminal_noninferiority"]


def test_p6_confirmatory_contract_uses_exact_rates_and_absolute_accuracy() -> None:
    config = P6BenchmarkConfig.from_yaml(
        Path("configs/experiments/p6_domain_shift_strong_confirmatory.yaml")
    )
    summaries = []
    for scenario in config.scenarios:
        item = _summary(scenario)
        item.update(
            {
                "num_seeds": 72,
                "no_shift_false_alarm_rate_ci95": [0.0, 0.049],
                "detection_rate_ci95": [0.951, 1.0],
                "full_recovery_rate_ci95": [0.951, 1.0],
                "full_vs_passive_early_rmse_improvement_ci95": [0.005, 0.02],
                "full_vs_passive_early_rmse_wilcoxon_one_sided_p": 0.001,
                "full_final_rmse_ci95": [0.10, 0.13],
            }
        )
        summaries.append(item)

    result = evaluate_p6_summaries(config, summaries)

    assert result["verdict"] == "GO"
    assert result["gates"]["rate_confidence_bounds"]
    assert result["gates"]["active_terminal_accuracy"]
    assert "active_terminal_noninferiority" not in result["gates"]


def test_p6_config_rejects_budget_and_control_changes() -> None:
    config = P6BenchmarkConfig.from_yaml(Path("configs/experiments/p6_domain_shift_main.yaml"))
    trial = dict(config.trial)
    trial["recovery_budget_trials"] = 13
    with pytest.raises(ValueError, match="40%"):
        replace(config, trial=trial).validate()
    with pytest.raises(ValueError, match="controls"):
        replace(config, methods=("frozen", "full")).validate()


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_p6_method_aggregation_recomputes_paired_effect(tmp_path: Path) -> None:
    methods = ("frozen", "passive", "full")
    scenario = {"id": "shift"}
    final = {
        "frozen": [0.30, 0.28],
        "passive": [0.22, 0.21],
        "full": [0.18, 0.16],
    }
    for method in methods:
        method_dir = tmp_path / method
        method_dir.mkdir()
        summary = {
            "no_shift_false_alarm_rate": 0.0,
            "detection_rate": 1.0,
            "median_detection_delay_trials": 2.0,
            "p95_detection_delay_trials": 3.0,
            "recovery_to_dense_budget_ratio": 0.4,
            "valid_observation_ratio": 0.95,
            "safety_aborts": 0,
            "maximum_abort_latency_s": 0.0,
            "serious_safety_events": 0,
            "finite": True,
            "primary_recovery_horizon_trials": 5,
            "validation_window_trials": 4,
            "invalid_window_rmse_penalty": 0.25,
        }
        (method_dir / "summary.json").write_text(
            json.dumps(summary),
            encoding="utf-8",
        )
        per_seed = [
            {
                "scenario": "shift",
                "seed": seed,
                "method": method,
                "false_alarm": "False",
                "detected": "True",
                "detection_delay_trials": 2,
                "pre_shift_rmse": 0.1,
                "initial_shifted_rmse": 0.3,
                "target_rmse": 0.2,
                "recovered": "True",
                "recovery_trials": index + 3,
                "final_rmse": final[method][index],
            }
            for index, seed in enumerate((1, 2))
        ]
        _write_rows(method_dir / "per_seed_metrics.csv", per_seed)
        for filename in ("monitor_metrics.csv", "recovery_metrics.csv"):
            _write_rows(
                method_dir / filename,
                [{"scenario": "shift", "seed": 1, "method": method}],
            )
        _write_rows(
            method_dir / "recovery_curve.csv",
            [
                {
                    "scenario": "shift",
                    "seed": seed,
                    "method": method,
                    "recovery_trial": trial,
                    "rolling_rmse": final[method][index] + 0.02 * (5 - trial),
                    "target_rmse": 0.2,
                }
                for index, seed in enumerate((1, 2))
                for trial in (4, 5)
            ],
        )

    result = _aggregate_method_outputs(scenario, tmp_path, methods, 100)

    assert result["num_seeds"] == 2
    assert result["full_recovery_rate"] == 1.0
    assert result["full_vs_frozen_final_improvement_mean"] == pytest.approx(0.12)
    assert result["full_vs_frozen_final_improvement_ci95"][0] > 0.0
    assert result["full_vs_passive_early_rmse_improvement_ci95"][0] > 0.0
    assert result["full_minus_passive_final_rmse_ci95"][1] < 0.0
    assert (tmp_path / "paired_recovery_effects.csv").is_file()
    assert len(list(csv.DictReader((tmp_path / "per_seed_metrics.csv").open()))) == 6
    assert json.loads((tmp_path / "summary.json").read_text())["finite"] is True


def test_p6_csv_helpers_fail_closed_on_invalid_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty aggregate"):
        _write_csv_rows(tmp_path / "empty.csv", [])
    with pytest.raises(ValueError, match="serialized boolean"):
        _as_bool("not-a-boolean")


def test_p6_resume_requires_the_complete_artifact_contract(tmp_path: Path) -> None:
    assert not _method_artifacts_complete(tmp_path)
    for name in _REQUIRED_METHOD_ARTIFACTS:
        path = tmp_path / name
        if name in {"summary.json", "scenario_config.json"}:
            path.write_text('{"complete": true}', encoding="utf-8")
        else:
            path.write_bytes(b"evidence")
    assert _method_artifacts_complete(tmp_path)
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    assert not _method_artifacts_complete(tmp_path)


def test_p6_config_rejects_invalid_evidence_contracts() -> None:
    config = P6BenchmarkConfig.from_yaml(Path("configs/experiments/p6_domain_shift_main.yaml"))
    vectorization = dict(config.vectorization)
    vectorization["num_seeds"] = 19
    with pytest.raises(ValueError, match="num_seeds"):
        replace(config, vectorization=vectorization).validate()
    vectorization = dict(config.vectorization)
    vectorization["seeds"] = [6601] * 20
    with pytest.raises(ValueError, match="unique"):
        replace(config, vectorization=vectorization).validate()
    with pytest.raises(ValueError, match="scenario ids"):
        replace(config, scenarios=(config.scenarios[0], config.scenarios[0])).validate()
    detector = dict(config.detector)
    detector["minimum_positive_evidence"] = 2
    with pytest.raises(ValueError, match="isolated"):
        replace(config, detector=detector).validate()
    detector = dict(config.detector)
    detector["evidence_window_trials"] = 2
    with pytest.raises(ValueError, match="too short"):
        replace(config, detector=detector).validate()
    scenario = dict(config.scenarios[0])
    scenario["checkpoint"] = "missing"
    with pytest.raises(ValueError, match="unknown checkpoint"):
        replace(config, scenarios=(scenario,)).validate()
    scenario = dict(config.scenarios[0])
    scenario["post_physics"] = {**scenario["post_physics"], "static_friction": 0.0}
    with pytest.raises(ValueError, match="friction"):
        replace(config, scenarios=(scenario,)).validate()
