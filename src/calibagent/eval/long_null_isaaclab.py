"""Long-horizon no-shift detector exposure in pinned Isaac Lab contexts."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from calibagent.eval.metrics import clopper_pearson_interval
from calibagent.eval.p5_isaaclab import (
    _artifact_manifest,
    _checkpoint_path,
    _git_value,
    _require_clean_repository,
    _run,
    _runtime_metadata,
)
from calibagent.eval.p6_isaaclab import (
    P6BenchmarkConfig,
    _method_artifacts_complete,
    _scenario_payload,
)
from calibagent.eval.real_replay import file_sha256


def _strict_bool(value: str) -> bool:
    if value not in {"True", "False"}:
        raise ValueError(f"invalid serialized boolean: {value!r}")
    return value == "True"


def _read_monitor(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return [row for row in csv.DictReader(stream) if row["context_stage"] == "pre_shift"]


def _sequence_rows(
    scenario: str,
    rows: list[dict[str, str]],
    expected_trials: int,
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(int(row["seed"]), []).append(row)
    summaries: list[dict[str, Any]] = []
    for seed, seed_rows in sorted(grouped.items()):
        ordered = sorted(seed_rows, key=lambda row: int(row["monitor_trial"]))
        trials = [int(row["monitor_trial"]) for row in ordered]
        if trials != list(range(1, expected_trials + 1)):
            raise ValueError(f"incomplete null-monitor sequence for {scenario}/{seed}")
        alarms = [int(row["monitor_trial"]) for row in ordered if _strict_bool(row["alarm"])]
        summaries.append(
            {
                "scenario": scenario,
                "seed": seed,
                "monitor_trials": len(ordered),
                "false_alarm": bool(alarms),
                "first_alarm_trial": alarms[0] if alarms else 0,
                "maximum_cusum": max(float(row["cusum"]) for row in ordered),
                "mean_normalized_nis": float(
                    np.mean([float(row["normalized_nis"]) for row in ordered])
                ),
                "valid_observation_ratio": float(
                    np.mean([_strict_bool(row["valid"]) for row in ordered])
                ),
                "monitor_safety_event_count": sum(bool(row["safety_events"]) for row in ordered),
            }
        )
    return summaries


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("refusing to write empty null-monitor summary")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_long_null_suite(
    config_path: Path,
    workspace: Path,
    isaaclab_root: Path,
    checkpoint_cache: Path,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    root = workspace.resolve()
    isaaclab = isaaclab_root.resolve()
    config = P6BenchmarkConfig.from_yaml(config_path.resolve())
    if config.experiment_role != "supplemental_null":
        raise ValueError("long-null suite requires experiment_role=supplemental_null")
    output = (root / config.output_dir).resolve()
    if output.exists() and any(output.iterdir()) and not resume:
        raise FileExistsError(f"refusing to overwrite non-empty output: {output}")
    _require_clean_repository(root, "CalibAgent")
    _require_clean_repository(isaaclab, "Isaac Lab")
    runtime = _runtime_metadata(isaaclab, root)
    if runtime["isaaclab_commit"] != str(config.isaaclab["commit"]):
        raise RuntimeError("Isaac Lab commit does not match the frozen config")
    if not runtime["isaac_sim_version"].startswith(
        str(config.isaaclab["isaac_sim_version_prefix"])
    ):
        raise RuntimeError("Isaac Sim version does not match the frozen config")
    checkpoints = {
        alias: _checkpoint_path(alias, specification, checkpoint_cache.resolve())
        for alias, specification in config.checkpoints.items()
    }
    output.mkdir(parents=True, exist_ok=True)
    resolved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    (output / "resolved_config.json").write_text(
        json.dumps(resolved, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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

    expected_trials = int(config.trial["pre_monitor_trials"])
    all_sequences: list[dict[str, Any]] = []
    context_summaries: list[dict[str, Any]] = []
    reused: list[str] = []
    for index, scenario in enumerate(config.scenarios):
        scenario_id = str(scenario["id"])
        method_output = output / "scenarios" / scenario_id / "full"
        if resume and _method_artifacts_complete(method_output):
            reused.append(scenario_id)
        else:
            method_output.mkdir(parents=True, exist_ok=resume)
            payload_path = method_output / "launch_config.json"
            payload_path.write_text(
                json.dumps(
                    _scenario_payload(config, scenario, index, "full"),
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
                str(method_output),
                "--headless",
                "--kit_args=--portable-root=/tmp/calibagent_kit_p6",
            ]
            (method_output / "launch_command.json").write_text(
                json.dumps(command, indent=2), encoding="utf-8"
            )
            result = _run(command, cwd=root, env=environment, check=False)
            (method_output / "simulator.log").write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
            if result.returncode != 0 or not _method_artifacts_complete(method_output):
                raise RuntimeError(
                    f"long-null scenario {scenario_id} failed; see "
                    f"{method_output / 'simulator.log'}"
                )
        monitor_rows = _read_monitor(method_output / "monitor_metrics.csv")
        sequences = _sequence_rows(scenario_id, monitor_rows, expected_trials)
        expected_seeds = int(config.vectorization["num_seeds"])
        if len(sequences) != expected_seeds:
            raise ValueError(f"seed coverage mismatch for {scenario_id}")
        all_sequences.extend(sequences)
        alarm_count = sum(bool(row["false_alarm"]) for row in sequences)
        method_summary = json.loads(
            (method_output / "summary.json").read_text(encoding="utf-8")
        )
        context_summaries.append(
            {
                "scenario": scenario_id,
                "sequences": len(sequences),
                "monitor_trials": len(monitor_rows),
                "false_alarm_sequences": alarm_count,
                "false_alarm_sequence_rate": alarm_count / len(sequences),
                "false_alarm_sequence_rate_ci95": list(
                    clopper_pearson_interval(alarm_count, len(sequences))
                ),
                "minimum_valid_observation_ratio": min(
                    float(row["valid_observation_ratio"]) for row in sequences
                ),
                "maximum_cusum": max(float(row["maximum_cusum"]) for row in sequences),
                "mean_normalized_nis": float(
                    np.mean([float(row["mean_normalized_nis"]) for row in sequences])
                ),
                "serious_safety_events": int(method_summary["serious_safety_events"]),
                "maximum_abort_latency_s": float(method_summary["maximum_abort_latency_s"]),
            }
        )
    _write_csv(output / "per_sequence.csv", all_sequences)

    alarm_count = sum(bool(row["false_alarm"]) for row in all_sequences)
    sequence_count = len(all_sequences)
    interval = list(clopper_pearson_interval(alarm_count, sequence_count))
    gates = config.publication_gates
    minimum_valid = min(float(row["valid_observation_ratio"]) for row in all_sequences)
    serious = sum(int(row["serious_safety_events"]) for row in context_summaries)
    maximum_abort = max(float(row["maximum_abort_latency_s"]) for row in context_summaries)
    checks = {
        "context_coverage": len(context_summaries) >= int(gates["minimum_contexts"]),
        "seed_coverage": all(
            int(row["sequences"]) >= int(gates["minimum_seeds_per_context"])
            for row in context_summaries
        ),
        "exposure_length": all(
            int(row["monitor_trials"])
            >= int(gates["minimum_monitor_trials_per_sequence"])
            * int(gates["minimum_seeds_per_context"])
            for row in context_summaries
        ),
        "false_alarm_rate": alarm_count / sequence_count
        <= float(gates["maximum_false_alarm_sequence_rate"]),
        "false_alarm_confidence_bound": interval[1]
        <= float(gates["maximum_false_alarm_sequence_rate_ci95_upper"]),
        "valid_observations": minimum_valid
        >= float(gates["minimum_valid_observation_ratio"]),
        "safety": serious <= int(gates["maximum_serious_safety_events"])
        and maximum_abort <= float(gates["maximum_abort_latency_s"]),
    }
    trial_duration = sum(
        float(config.trial[key])
        for key in ("warmup_s", "ramp_in_s", "settle_s", "measure_s", "ramp_out_s")
    )
    summary = {
        "schema_version": "1.0",
        "verdict": "GO" if all(checks.values()) else "NO_GO",
        "checks": checks,
        "context_count": len(context_summaries),
        "sequence_count": sequence_count,
        "monitor_trials_per_sequence": expected_trials,
        "total_monitor_trials": sum(int(row["monitor_trials"]) for row in context_summaries),
        "total_monitor_command_time_s": expected_trials * sequence_count * trial_duration,
        "false_alarm_sequences": alarm_count,
        "false_alarm_sequence_rate": alarm_count / sequence_count,
        "false_alarm_sequence_rate_ci95": interval,
        "minimum_valid_observation_ratio": minimum_valid,
        "total_serious_safety_events": serious,
        "maximum_abort_latency_s": maximum_abort,
        "contexts": context_summaries,
        "runtime": runtime,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "1.0",
        "backend": "isaaclab_physx_go2_long_null_monitor",
        "git_commit": _git_value(root, "rev-parse", "HEAD"),
        "config_path": str(config_path.resolve().relative_to(root)),
        "config_sha256": file_sha256(config_path),
        "resumed": resume,
        "reused_complete_contexts": reused,
        "runtime": runtime,
        "checkpoints": {
            alias: {"url": specification["url"], "sha256": file_sha256(checkpoints[alias])}
            for alias, specification in config.checkpoints.items()
        },
        "artifacts": _artifact_manifest(output),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
