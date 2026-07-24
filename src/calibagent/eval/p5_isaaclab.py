"""Pinned Isaac Lab P5 benchmark orchestration and publication gates."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from calibagent.eval.real_replay import file_sha256


@dataclass(frozen=True)
class P5BenchmarkConfig:
    output_dir: str
    isaaclab: dict[str, Any]
    vectorization: dict[str, Any]
    trial: dict[str, Any]
    safety: dict[str, Any]
    checkpoints: dict[str, dict[str, str]]
    scenarios: tuple[dict[str, Any], ...]
    publication_gates: dict[str, Any]
    experiment_role: str = "main"
    protocol_frozen_utc: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> P5BenchmarkConfig:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("P5 benchmark config must be a mapping")
        config = cls(
            output_dir=str(payload["output_dir"]),
            isaaclab=dict(payload["isaaclab"]),
            vectorization=dict(payload["vectorization"]),
            trial=dict(payload["trial"]),
            safety=dict(payload["safety"]),
            checkpoints={
                str(name): dict(value)
                for name, value in dict(payload["checkpoints"]).items()
            },
            scenarios=tuple(dict(item) for item in payload["scenarios"]),
            publication_gates=dict(payload["publication_gates"]),
            experiment_role=str(payload.get("experiment_role", "main")),
            protocol_frozen_utc=str(payload.get("protocol_frozen_utc", "")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        seeds = [int(item) for item in self.vectorization["seeds"]]
        scenario_ids = [str(item["id"]) for item in self.scenarios]
        if not seeds or len(seeds) != len(set(seeds)):
            raise ValueError("P5 seeds must be non-empty and unique")
        if int(self.vectorization["num_envs"]) != len(seeds):
            raise ValueError("P5 num_envs must equal the number of seeds")
        if not scenario_ids or len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("P5 scenario ids must be non-empty and unique")
        for scenario in self.scenarios:
            checkpoint = str(scenario["checkpoint"])
            if checkpoint not in self.checkpoints:
                raise ValueError(f"unknown checkpoint alias: {checkpoint}")
            if str(scenario["tier"]) not in {"A", "B"}:
                raise ValueError("P5 scenarios must be assigned to Tier A or Tier B")
        if float(self.safety["min_base_height_m"]) >= float(
            self.safety["max_base_height_m"]
        ):
            raise ValueError("P5 safety base-height limits are inverted")


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def _git_value(repository: Path, *arguments: str) -> str:
    return _run(["git", *arguments], cwd=repository).stdout.strip()


def _require_clean_repository(repository: Path, label: str) -> None:
    status = _git_value(repository, "status", "--short", "--untracked-files=normal")
    if status:
        raise RuntimeError(f"{label} worktree is not clean:\n{status}")


def _sim_version(isaaclab_root: Path) -> str:
    version_file = isaaclab_root / "_isaac_sim" / "VERSION"
    if not version_file.is_file():
        raise FileNotFoundError(f"Isaac Sim VERSION is missing: {version_file}")
    return version_file.read_text(encoding="utf-8").strip()


def _checkpoint_path(
    alias: str,
    specification: dict[str, str],
    cache: Path,
) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"go2_{alias}_checkpoint.pt"
    expected = str(specification["sha256"])
    if path.is_file():
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(
                f"cached checkpoint hash mismatch for {alias}: {actual} != {expected}"
            )
        return path
    temporary = path.with_suffix(".download")
    try:
        urllib.request.urlretrieve(str(specification["url"]), temporary)
        actual = file_sha256(temporary)
        if actual != expected:
            raise ValueError(
                f"downloaded checkpoint hash mismatch for {alias}: "
                f"{actual} != {expected}"
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _scenario_payload(
    config: P5BenchmarkConfig,
    scenario: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    return {
        "scenario_id": str(scenario["id"]),
        "tier": str(scenario["tier"]),
        "task": str(scenario["task"]),
        "distortion": str(scenario["distortion"]),
        "terrain": str(scenario["terrain"]),
        "static_friction": float(scenario["static_friction"]),
        "dynamic_friction": float(scenario["dynamic_friction"]),
        "payload_add_kg": float(scenario["payload_add_kg"]),
        "com_offset_x_m": float(scenario["com_offset_x_m"]),
        "seeds": [int(item) for item in config.vectorization["seeds"]],
        "calibration_trials": int(config.trial["calibration_trials"]),
        "warmup_s": float(config.trial["warmup_s"]),
        "ramp_in_s": float(config.trial["ramp_in_s"]),
        "settle_s": float(config.trial["settle_s"]),
        "measure_s": float(config.trial["measure_s"]),
        "ramp_out_s": float(config.trial["ramp_out_s"]),
        "sample_rate_hz": float(config.trial["sample_rate_hz"]),
        "simulator_seed": int(config.vectorization["simulator_seed"]) + index,
        "safety_min_base_height_m": float(
            config.safety["min_base_height_m"]
        ),
        "safety_max_base_height_m": float(
            config.safety["max_base_height_m"]
        ),
    }


def evaluate_p5_summaries(
    config: P5BenchmarkConfig,
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply frozen P5 gates to scenario summaries without running a simulator."""

    gates = config.publication_gates
    actual_ids = {str(item["scenario"]) for item in summaries}
    expected_ids = {str(item["id"]) for item in config.scenarios}
    tier_a = [item for item in summaries if item["tier"] == "A"]
    tier_b = [item for item in summaries if item["tier"] == "B"]
    gate_results = {
        "scenario_identity": actual_ids == expected_ids,
        "minimum_scenarios": len(summaries) >= int(gates["minimum_scenarios"]),
        "tier_a_coverage": len(tier_a)
        >= int(gates["minimum_tier_a_scenarios"]),
        "tier_b_coverage": len(tier_b)
        >= int(gates["minimum_tier_b_scenarios"]),
        "seed_coverage": all(
            int(item["num_envs"]) >= int(gates["minimum_seeds_per_scenario"])
            for item in summaries
        ),
        "valid_calibration": all(
            float(item["valid_calibration_ratio"])
            >= float(gates["minimum_valid_calibration_ratio"])
            for item in summaries
        ),
        "valid_validation": all(
            float(item["valid_validation_ratio"])
            >= float(gates["minimum_valid_validation_ratio"])
            for item in summaries
        ),
        "actual_motion": all(
            float(item["actual_motion_ratio"])
            >= float(gates["minimum_actual_motion_ratio"])
            for item in summaries
        ),
        "calibration_improvement": all(
            float(item["calibrated_vs_raw_reduction"])
            >= float(gates["minimum_calibrated_vs_raw_rmse_reduction"])
            for item in summaries
        ),
        "paired_improvement_ci95": all(
            float(item["paired_absolute_improvement_ci95"][0])
            > float(gates["minimum_paired_improvement_ci95_lower"])
            for item in summaries
        ),
        "safety_abort_latency": all(
            float(item["maximum_abort_latency_s"])
            <= float(gates["maximum_abort_latency_s"])
            for item in summaries
        ),
        "serious_safety_events": sum(
            int(item["serious_safety_events"]) for item in summaries
        )
        <= int(gates["maximum_serious_safety_events"]),
        "finite": all(bool(item["finite"]) for item in summaries),
    }
    return {
        "schema_version": "1.0",
        "verdict": "GO" if summaries and all(gate_results.values()) else "NO_GO",
        "scenario_count": len(summaries),
        "tier_a_scenarios": len(tier_a),
        "tier_b_scenarios": len(tier_b),
        "seeds_per_scenario": (
            min(int(item["num_envs"]) for item in summaries) if summaries else 0
        ),
        "minimum_valid_calibration_ratio": (
            min(float(item["valid_calibration_ratio"]) for item in summaries)
            if summaries
            else 0.0
        ),
        "minimum_valid_validation_ratio": (
            min(float(item["valid_validation_ratio"]) for item in summaries)
            if summaries
            else 0.0
        ),
        "minimum_actual_motion_ratio": (
            min(float(item["actual_motion_ratio"]) for item in summaries)
            if summaries
            else 0.0
        ),
        "minimum_calibrated_vs_raw_reduction": (
            min(float(item["calibrated_vs_raw_reduction"]) for item in summaries)
            if summaries
            else 0.0
        ),
        "minimum_paired_improvement_ci95_lower": (
            min(
                float(item["paired_absolute_improvement_ci95"][0])
                for item in summaries
            )
            if summaries
            else float("-inf")
        ),
        "total_serious_safety_events": sum(
            int(item["serious_safety_events"]) for item in summaries
        ),
        "total_safety_aborts": sum(
            int(item["safety_aborts"]) for item in summaries
        ),
        "maximum_abort_latency_s": (
            max(float(item["maximum_abort_latency_s"]) for item in summaries)
            if summaries
            else 0.0
        ),
        "scenarios": summaries,
        "gates": gate_results,
    }


def _runtime_metadata(isaaclab_root: Path, workspace: Path) -> dict[str, str]:
    python = _run(
        [
            str(isaaclab_root / "_isaac_sim" / "python.sh"),
            "-c",
            "import platform; print(platform.python_version())",
        ],
        cwd=workspace,
    ).stdout.strip()
    gpu = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version",
            "--format=csv,noheader",
        ],
        cwd=workspace,
    ).stdout.strip()
    return {
        "isaaclab_commit": _git_value(isaaclab_root, "rev-parse", "HEAD"),
        "isaaclab_describe": _git_value(
            isaaclab_root, "describe", "--tags", "--always"
        ),
        "isaac_sim_version": _sim_version(isaaclab_root),
        "isaac_python_version": python,
        "gpu_and_driver": gpu,
    }


def _artifact_manifest(output: Path) -> dict[str, dict[str, str]]:
    return {
        str(path.relative_to(output)): {
            "path": str(path.relative_to(output)),
            "sha256": file_sha256(path),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def run_p5_suite(
    config_path: Path,
    workspace: Path,
    isaaclab_root: Path,
    checkpoint_cache: Path,
) -> dict[str, Any]:
    """Execute all frozen P5 scenarios in the pinned Isaac Lab runtime."""

    root = workspace.resolve()
    isaaclab = isaaclab_root.resolve()
    config = P5BenchmarkConfig.from_yaml(config_path.resolve())
    output = (root / config.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty P5 output: {output}")
    _require_clean_repository(root, "CalibAgent")
    _require_clean_repository(isaaclab, "Isaac Lab")
    runtime = _runtime_metadata(isaaclab, root)
    if runtime["isaaclab_commit"] != str(config.isaaclab["commit"]):
        raise RuntimeError("Isaac Lab commit does not match the frozen P5 config")
    if not runtime["isaac_sim_version"].startswith(
        str(config.isaaclab["isaac_sim_version_prefix"])
    ):
        raise RuntimeError("Isaac Sim version does not match the frozen P5 config")
    checkpoints = {
        alias: _checkpoint_path(alias, specification, checkpoint_cache.resolve())
        for alias, specification in config.checkpoints.items()
    }
    output.mkdir(parents=True, exist_ok=True)
    resolved_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    (output / "resolved_config.json").write_text(
        json.dumps(resolved_payload, indent=2, sort_keys=True),
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
    environment["TERM"] = "xterm-256color"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in source_paths)
    summaries: list[dict[str, Any]] = []
    for index, scenario in enumerate(config.scenarios):
        scenario_id = str(scenario["id"])
        scenario_output = output / "scenarios" / scenario_id
        scenario_output.mkdir(parents=True)
        payload = _scenario_payload(config, scenario, index)
        scenario_config_path = scenario_output / "launch_config.json"
        scenario_config_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        command = [
            str(isaaclab / "isaaclab.sh"),
            "-p",
            str(root / "sim" / "isaaclab" / "scripts" / "run_scenario.py"),
            "--scenario-config",
            str(scenario_config_path),
            "--checkpoint",
            str(checkpoints[str(scenario["checkpoint"])]),
            "--output",
            str(scenario_output),
            "--headless",
        ]
        (scenario_output / "launch_command.json").write_text(
            json.dumps(command, indent=2),
            encoding="utf-8",
        )
        result = _run(command, cwd=root, env=environment, check=False)
        (scenario_output / "simulator.log").write_text(
            result.stdout + result.stderr,
            encoding="utf-8",
        )
        required = (
            "summary.json",
            "trial_metrics.csv",
            "per_seed_metrics.csv",
            "pose_trace.csv",
            "distortion_parameters.json",
            "scenario_config.json",
        )
        missing = [name for name in required if not (scenario_output / name).is_file()]
        if result.returncode != 0 or missing:
            raise RuntimeError(
                f"Isaac Lab scenario {scenario_id} failed "
                f"(returncode={result.returncode}, missing={missing}); "
                f"see {scenario_output / 'simulator.log'}"
            )
        summary = json.loads(
            (scenario_output / "summary.json").read_text(encoding="utf-8")
        )
        if str(summary["scenario"]) != scenario_id:
            raise RuntimeError(f"scenario identity mismatch for {scenario_id}")
        summaries.append(summary)

    aggregate = evaluate_p5_summaries(config, summaries)
    aggregate["runtime"] = runtime
    (output / "summary.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    source_commit = _git_value(root, "rev-parse", "HEAD")
    manifest = {
        "schema_version": "1.0",
        "phase": "P5",
        "backend": "isaaclab_physx_go2_vectorized",
        "git_commit": source_commit,
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
