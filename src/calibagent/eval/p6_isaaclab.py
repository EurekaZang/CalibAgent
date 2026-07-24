"""Pinned Isaac Lab P6 domain-shift and adaptation benchmark."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from calibagent.eval.p5_isaaclab import (
    _artifact_manifest,
    _checkpoint_path,
    _git_value,
    _require_clean_repository,
    _run,
    _runtime_metadata,
)
from calibagent.eval.real_replay import file_sha256


@dataclass(frozen=True)
class P6BenchmarkConfig:
    output_dir: str
    isaaclab: dict[str, Any]
    vectorization: dict[str, Any]
    methods: tuple[str, ...]
    trial: dict[str, Any]
    detector: dict[str, Any]
    adaptation: dict[str, Any]
    safety: dict[str, Any]
    checkpoints: dict[str, dict[str, str]]
    scenarios: tuple[dict[str, Any], ...]
    publication_gates: dict[str, Any]
    experiment_role: str
    protocol_frozen_utc: str

    @classmethod
    def from_yaml(cls, path: Path) -> P6BenchmarkConfig:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("P6 benchmark config must be a mapping")
        config = cls(
            output_dir=str(payload["output_dir"]),
            isaaclab=dict(payload["isaaclab"]),
            vectorization=dict(payload["vectorization"]),
            methods=tuple(str(item) for item in payload["methods"]),
            trial=dict(payload["trial"]),
            detector=dict(payload["detector"]),
            adaptation=dict(payload["adaptation"]),
            safety=dict(payload["safety"]),
            checkpoints={
                str(name): dict(value) for name, value in dict(payload["checkpoints"]).items()
            },
            scenarios=tuple(dict(item) for item in payload["scenarios"]),
            publication_gates=dict(payload["publication_gates"]),
            experiment_role=str(payload["experiment_role"]),
            protocol_frozen_utc=str(payload["protocol_frozen_utc"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        seeds = [int(item) for item in self.vectorization["seeds"]]
        scenario_ids = [str(item["id"]) for item in self.scenarios]
        if len(seeds) != int(self.vectorization["num_seeds"]):
            raise ValueError("P6 num_seeds must match the seed list")
        if len(seeds) != len(set(seeds)):
            raise ValueError("P6 seeds must be unique")
        if self.methods != ("frozen", "passive", "full"):
            raise ValueError("P6 requires frozen/passive/full controls")
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("P6 scenario ids must be unique")
        if int(self.trial["recovery_budget_trials"]) > 0.40 * int(
            self.trial["dense_budget_trials"]
        ):
            raise ValueError("P6 recovery budget exceeds 40% of dense")
        if int(self.detector["minimum_consecutive"]) < 3:
            raise ValueError("P6 detector must reject isolated/two-sample outliers")
        for scenario in self.scenarios:
            if str(scenario["checkpoint"]) not in self.checkpoints:
                raise ValueError("P6 scenario uses an unknown checkpoint")
            for phase in ("pre_physics", "post_physics"):
                physics = dict(scenario[phase])
                if float(physics["static_friction"]) <= 0.0:
                    raise ValueError("P6 friction must be positive")


def evaluate_p6_summaries(
    config: P6BenchmarkConfig,
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    gates = config.publication_gates
    expected = {str(item["id"]) for item in config.scenarios}
    actual = {str(item["scenario"]) for item in summaries}
    checks = {
        "scenario_identity": actual == expected,
        "minimum_scenarios": len(summaries) >= int(gates["minimum_scenarios"]),
        "seed_coverage": all(
            int(item["num_seeds"]) >= int(gates["minimum_seeds_per_scenario"]) for item in summaries
        ),
        "false_alarm_control": all(
            float(item["no_shift_false_alarm_rate"])
            <= float(gates["maximum_no_shift_false_alarm_rate"])
            for item in summaries
        ),
        "detection_rate": all(
            float(item["detection_rate"]) >= float(gates["minimum_detection_rate"])
            for item in summaries
        ),
        "detection_delay": all(
            float(gates["minimum_median_detection_delay_trials"])
            <= float(item["median_detection_delay_trials"])
            <= float(gates["maximum_median_detection_delay_trials"])
            and float(item["p95_detection_delay_trials"])
            <= float(gates["maximum_p95_detection_delay_trials"])
            for item in summaries
        ),
        "full_recovery": all(
            float(item["full_recovery_rate"]) >= float(gates["minimum_full_recovery_rate"])
            and float(item["median_full_recovery_trials"])
            <= float(gates["maximum_median_recovery_trials"])
            and float(item["p95_full_recovery_trials"])
            <= float(gates["maximum_p95_recovery_trials"])
            for item in summaries
        ),
        "recovery_budget": all(
            float(item["recovery_to_dense_budget_ratio"])
            <= float(gates["maximum_recovery_to_dense_budget_ratio"])
            for item in summaries
        ),
        "paired_adaptation_effect": all(
            float(item["full_vs_frozen_final_improvement_ci95"][0])
            > float(gates["minimum_full_vs_frozen_improvement_ci95_lower"])
            and float(item["full_vs_frozen_win_rate"]) >= float(gates["minimum_full_win_rate"])
            for item in summaries
        ),
        "valid_observations": all(
            float(item["valid_observation_ratio"])
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
    return {
        "schema_version": "1.0",
        "phase": "P6",
        "verdict": "GO" if summaries and all(checks.values()) else "NO_GO",
        "scenario_count": len(summaries),
        "minimum_detection_rate": min(
            (float(item["detection_rate"]) for item in summaries), default=0.0
        ),
        "maximum_p95_detection_delay_trials": max(
            (float(item["p95_detection_delay_trials"]) for item in summaries),
            default=float("inf"),
        ),
        "minimum_full_recovery_rate": min(
            (float(item["full_recovery_rate"]) for item in summaries), default=0.0
        ),
        "maximum_p95_full_recovery_trials": max(
            (float(item["p95_full_recovery_trials"]) for item in summaries),
            default=float("inf"),
        ),
        "total_serious_safety_events": sum(
            int(item["serious_safety_events"]) for item in summaries
        ),
        "scenarios": summaries,
        "gates": checks,
    }


def _scenario_payload(
    config: P6BenchmarkConfig,
    scenario: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    return {
        **scenario,
        "seeds": [int(item) for item in config.vectorization["seeds"]],
        "methods": list(config.methods),
        "trial": config.trial,
        "detector": config.detector,
        "adaptation": config.adaptation,
        "safety": config.safety,
        "simulator_seed": int(config.vectorization["simulator_seed"]) + index,
    }


def run_p6_suite(
    config_path: Path,
    workspace: Path,
    isaaclab_root: Path,
    checkpoint_cache: Path,
) -> dict[str, Any]:
    root = workspace.resolve()
    isaaclab = isaaclab_root.resolve()
    config = P6BenchmarkConfig.from_yaml(config_path.resolve())
    output = (root / config.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty P6 output: {output}")
    _require_clean_repository(root, "CalibAgent")
    _require_clean_repository(isaaclab, "Isaac Lab")
    runtime = _runtime_metadata(isaaclab, root)
    if runtime["isaaclab_commit"] != str(config.isaaclab["commit"]):
        raise RuntimeError("Isaac Lab commit does not match the frozen P6 config")
    if not runtime["isaac_sim_version"].startswith(
        str(config.isaaclab["isaac_sim_version_prefix"])
    ):
        raise RuntimeError("Isaac Sim version does not match the frozen P6 config")
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
    environment["TERM"] = "xterm-256color"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in source_paths)
    summaries: list[dict[str, Any]] = []
    for index, scenario in enumerate(config.scenarios):
        scenario_id = str(scenario["id"])
        scenario_output = output / "scenarios" / scenario_id
        scenario_output.mkdir(parents=True)
        payload_path = scenario_output / "launch_config.json"
        payload_path.write_text(
            json.dumps(
                _scenario_payload(config, scenario, index),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        command = [
            str(isaaclab / "isaaclab.sh"),
            "-p",
            str(root / "sim" / "isaaclab" / "scripts" / "run_p6_scenario.py"),
            "--scenario-config",
            str(payload_path),
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
            "monitor_metrics.csv",
            "recovery_metrics.csv",
            "per_seed_metrics.csv",
            "pose_trace.csv",
            "shift_events.json",
            "scenario_config.json",
        )
        missing = [name for name in required if not (scenario_output / name).is_file()]
        if result.returncode != 0 or missing:
            raise RuntimeError(
                f"P6 scenario {scenario_id} failed "
                f"(returncode={result.returncode}, missing={missing}); "
                f"see {scenario_output / 'simulator.log'}"
            )
        summaries.append(json.loads((scenario_output / "summary.json").read_text(encoding="utf-8")))
    aggregate = evaluate_p6_summaries(config, summaries)
    aggregate["runtime"] = runtime
    (output / "summary.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "phase": "P6",
        "backend": "isaaclab_physx_go2_domain_shift",
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
