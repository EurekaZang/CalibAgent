from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from calibagent.eval.p5_isaaclab import (
    P5BenchmarkConfig,
    _artifact_manifest,
    _checkpoint_path,
    _scenario_payload,
    _sim_version,
    evaluate_p5_summaries,
)


def _summary(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario": scenario["id"],
        "tier": scenario["tier"],
        "num_envs": 20,
        "valid_calibration_ratio": 1.0,
        "valid_validation_ratio": 1.0,
        "actual_motion_ratio": 0.95,
        "calibrated_vs_raw_reduction": 0.25,
        "paired_absolute_improvement_ci95": [0.01, 0.04],
        "safety_aborts": 0,
        "maximum_abort_latency_s": 0.0,
        "serious_safety_events": 0,
        "finite": True,
    }


def test_frozen_p5_config_and_all_gates_pass() -> None:
    config = P5BenchmarkConfig.from_yaml(
        Path("configs/experiments/p5_isaaclab_main.yaml")
    )
    summaries = [_summary(scenario) for scenario in config.scenarios]

    result = evaluate_p5_summaries(config, summaries)

    assert result["verdict"] == "GO"
    assert all(result["gates"].values())
    assert result["tier_a_scenarios"] == 2
    assert result["tier_b_scenarios"] == 2


def test_p5_requires_positive_paired_ci_and_exact_scenarios() -> None:
    config = P5BenchmarkConfig.from_yaml(
        Path("configs/experiments/p5_isaaclab_main.yaml")
    )
    summaries = [_summary(scenario) for scenario in config.scenarios]
    summaries[0]["paired_absolute_improvement_ci95"] = [-0.001, 0.04]
    summaries.pop()

    result = evaluate_p5_summaries(config, summaries)

    assert result["verdict"] == "NO_GO"
    assert not result["gates"]["scenario_identity"]
    assert not result["gates"]["minimum_scenarios"]
    assert not result["gates"]["tier_b_coverage"]
    assert not result["gates"]["paired_improvement_ci95"]


def test_p5_rejects_nonfinite_or_unsafe_scenario() -> None:
    config = P5BenchmarkConfig.from_yaml(
        Path("configs/experiments/p5_isaaclab_main.yaml")
    )
    summaries = [_summary(scenario) for scenario in config.scenarios]
    summaries[2]["finite"] = False
    summaries[2]["serious_safety_events"] = 1

    result = evaluate_p5_summaries(config, summaries)

    assert result["verdict"] == "NO_GO"
    assert not result["gates"]["finite"]
    assert not result["gates"]["serious_safety_events"]


def test_p5_payload_and_cached_checkpoint_are_deterministic(
    tmp_path: Path,
) -> None:
    config = P5BenchmarkConfig.from_yaml(
        Path("configs/experiments/p5_isaaclab_main.yaml")
    )
    payload = _scenario_payload(config, config.scenarios[1], 3)
    content = b"published-policy"
    expected = hashlib.sha256(content).hexdigest()
    cache = tmp_path / "cache"
    cache.mkdir()
    checkpoint = cache / "go2_flat_checkpoint.pt"
    checkpoint.write_bytes(content)

    resolved = _checkpoint_path(
        "flat",
        {"url": "https://invalid.example/checkpoint.pt", "sha256": expected},
        cache,
    )

    assert payload["simulator_seed"] == 740243
    assert payload["seeds"] == list(range(5301, 5321))
    assert payload["safety_min_base_height_m"] == 0.15
    assert payload["safety_max_coupled_load"] == 0.8
    assert payload["model_prior_scale"] == 0.01
    assert resolved == checkpoint


def test_p5_helpers_reject_invalid_inputs_and_hash_artifacts(
    tmp_path: Path,
) -> None:
    config = P5BenchmarkConfig.from_yaml(
        Path("configs/experiments/p5_isaaclab_main.yaml")
    )
    bad_vectorization = dict(config.vectorization)
    bad_vectorization["seeds"] = [5101, 5101]
    bad_vectorization["num_envs"] = 2
    with pytest.raises(ValueError, match="unique"):
        replace(config, vectorization=bad_vectorization).validate()

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "go2_flat_checkpoint.pt").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="hash mismatch"):
        _checkpoint_path(
            "flat",
            {"url": "unused", "sha256": "0" * 64},
            cache,
        )

    output = tmp_path / "evidence"
    output.mkdir()
    (output / "result.txt").write_text("result", encoding="utf-8")
    (output / "manifest.json").write_text("excluded", encoding="utf-8")
    artifacts = _artifact_manifest(output)
    assert set(artifacts) == {"result.txt"}

    isaaclab = tmp_path / "IsaacLab"
    (isaaclab / "_isaac_sim").mkdir(parents=True)
    (isaaclab / "_isaac_sim" / "VERSION").write_text(
        "5.1.0-release\n", encoding="utf-8"
    )
    assert _sim_version(isaaclab) == "5.1.0-release"
