#!/usr/bin/env python3
"""Pool two frozen P6 confirmation blocks into publication statistics."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from calibagent.eval.metrics import clopper_pearson_interval
from calibagent.eval.p6_isaaclab import (
    _as_bool,
    _bootstrap_mean_ci,
    _paired_wilcoxon_less,
)
from calibagent.eval.real_replay import file_sha256

_COPIED_SCENARIO_ARTIFACTS = (
    "summary.json",
    "per_seed_metrics.csv",
    "paired_recovery_effects.csv",
    "recovery_curve.csv",
    "monitor_metrics.csv",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON mapping: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _verify_output_manifest(output: Path) -> dict[str, Any]:
    manifest_path = output / "manifest.json"
    manifest = _read_json(manifest_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError(f"manifest has no artifacts: {manifest_path}")
    root = output.resolve()
    for record in artifacts.values():
        if not isinstance(record, dict):
            raise ValueError(f"invalid artifact record: {manifest_path}")
        source = (output / str(record["path"])).resolve()
        if source != root and root not in source.parents:
            raise ValueError(f"artifact escapes output root: {source}")
        if file_sha256(source) != str(record["sha256"]):
            raise RuntimeError(f"source artifact hash mismatch: {source}")
    return manifest


def _scenario_key(identifier: str) -> str:
    try:
        return identifier.split("_", 1)[1]
    except IndexError as error:
        raise ValueError(f"scenario id has no block prefix: {identifier}") from error


def _scenario_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("resolved config has no scenario list")
    result: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("invalid scenario record")
        key = _scenario_key(str(scenario["id"]))
        if key in result:
            raise ValueError(f"duplicate context key: {key}")
        result[key] = scenario
    return result


def _validate_blocks(configs: list[dict[str, Any]]) -> list[str]:
    if len(configs) != 2:
        raise ValueError("exactly two confirmation blocks are required")
    invariant_keys = (
        "experiment_role",
        "isaaclab",
        "methods",
        "trial",
        "detector",
        "adaptation",
        "safety",
        "checkpoints",
        "publication_gates",
    )
    for key in invariant_keys:
        if configs[0][key] != configs[1][key]:
            raise ValueError(f"confirmation blocks differ in frozen field: {key}")
    seeds = [set(int(item) for item in config["vectorization"]["seeds"]) for config in configs]
    if seeds[0] & seeds[1]:
        raise ValueError("confirmation seed blocks overlap")
    simulator_seeds = [int(config["vectorization"]["simulator_seed"]) for config in configs]
    if len(set(simulator_seeds)) != 2:
        raise ValueError("confirmation simulator seeds must be disjoint")

    maps = [_scenario_map(config) for config in configs]
    if set(maps[0]) != set(maps[1]):
        raise ValueError("confirmation blocks cover different contexts")
    for key in maps[0]:
        for field in (
            "task",
            "checkpoint",
            "pre_distortion",
            "post_distortion",
            "pre_physics",
            "post_physics",
        ):
            if maps[0][key][field] != maps[1][key][field]:
                raise ValueError(f"context {key} differs in frozen field: {field}")
        if int(maps[0][key]["post_seed_offset"]) == int(maps[1][key]["post_seed_offset"]):
            raise ValueError(f"context {key} reuses post-shift draws")
    return sorted(maps[0])


def _pool_context(
    outputs: list[Path],
    configs: list[dict[str, Any]],
    context: str,
    bootstrap_seed: int,
) -> dict[str, Any]:
    scenario_maps = [_scenario_map(config) for config in configs]
    scenario_ids = [str(mapping[context]["id"]) for mapping in scenario_maps]
    seed_rows: list[dict[str, str]] = []
    paired_rows: list[dict[str, str]] = []
    source_summaries: list[dict[str, Any]] = []
    for output, identifier in zip(outputs, scenario_ids, strict=True):
        scenario_dir = output / "scenarios" / identifier
        seed_rows.extend(_read_csv(scenario_dir / "per_seed_metrics.csv"))
        paired_rows.extend(_read_csv(scenario_dir / "paired_recovery_effects.csv"))
        source_summaries.append(_read_json(scenario_dir / "summary.json"))

    full_rows = [row for row in seed_rows if row["method"] == "full"]
    frozen_rows = [row for row in seed_rows if row["method"] == "frozen"]
    if len(full_rows) != len(frozen_rows) or len(full_rows) != len(paired_rows):
        raise ValueError(f"incomplete paired records for context {context}")
    full_index = {int(row["seed"]): row for row in full_rows}
    frozen_index = {int(row["seed"]): row for row in frozen_rows}
    if set(full_index) != set(frozen_index) or len(full_index) != len(full_rows):
        raise ValueError(f"non-unique or unpaired seeds for context {context}")
    paired_seed_ids = [int(row["seed"]) for row in paired_rows]
    if len(set(paired_seed_ids)) != len(paired_seed_ids) or set(paired_seed_ids) != set(full_index):
        raise ValueError(f"invalid active/passive pairing for context {context}")

    full_final = np.asarray([float(row["full_final_rmse"]) for row in paired_rows])
    full_early = np.asarray([float(row["full_early_mean_rmse"]) for row in paired_rows])
    passive_early = np.asarray([float(row["passive_early_mean_rmse"]) for row in paired_rows])
    early_improvement = passive_early - full_early
    full_minus_passive_final = np.asarray(
        [float(row["full_minus_passive_final_rmse"]) for row in paired_rows]
    )
    frozen_improvement = np.asarray(
        [
            float(frozen_index[seed]["final_rmse"]) - float(full_index[seed]["final_rmse"])
            for seed in sorted(full_index)
        ]
    )
    detected = [_as_bool(row["detected"]) for row in full_rows]
    recovered = [_as_bool(row["recovered"]) for row in full_rows]
    false_alarms = [_as_bool(row["false_alarm"]) for row in full_rows]
    detection_delays = [
        float(row["detection_delay_trials"]) for row in full_rows if _as_bool(row["detected"])
    ]
    recovery_trials = [
        float(row["recovery_trials"]) for row in full_rows if _as_bool(row["recovered"])
    ]
    n = len(full_rows)
    detection_count = int(sum(detected))
    recovery_count = int(sum(recovered))
    false_alarm_count = int(sum(false_alarms))
    return {
        "context": context,
        "source_scenarios": scenario_ids,
        "num_seeds": n,
        "false_alarm_count": false_alarm_count,
        "no_shift_false_alarm_rate": false_alarm_count / n,
        "no_shift_false_alarm_rate_ci95": list(clopper_pearson_interval(false_alarm_count, n)),
        "detection_count": detection_count,
        "detection_rate": detection_count / n,
        "detection_rate_ci95": list(clopper_pearson_interval(detection_count, n)),
        "median_detection_delay_trials": float(np.median(detection_delays)),
        "p95_detection_delay_trials": float(np.quantile(detection_delays, 0.95)),
        "full_recovery_count": recovery_count,
        "full_recovery_rate": recovery_count / n,
        "full_recovery_rate_ci95": list(clopper_pearson_interval(recovery_count, n)),
        "median_full_recovery_trials": float(np.median(recovery_trials)),
        "p95_full_recovery_trials": float(np.quantile(recovery_trials, 0.95)),
        "full_vs_frozen_final_improvement_mean": float(np.mean(frozen_improvement)),
        "full_vs_frozen_final_improvement_ci95": _bootstrap_mean_ci(
            frozen_improvement, bootstrap_seed + 11
        ),
        "full_vs_frozen_win_rate": float(np.mean(frozen_improvement > 0.0)),
        "full_vs_passive_early_rmse_improvement_mean": float(np.mean(early_improvement)),
        "full_vs_passive_early_rmse_improvement_ci95": _bootstrap_mean_ci(
            early_improvement, bootstrap_seed + 13
        ),
        "full_vs_passive_early_rmse_win_rate": float(np.mean(early_improvement > 0.0)),
        "full_vs_passive_early_rmse_wilcoxon_one_sided_p": _paired_wilcoxon_less(
            full_early, passive_early
        ),
        "full_minus_passive_final_rmse_mean": float(np.mean(full_minus_passive_final)),
        "full_minus_passive_final_rmse_ci95": _bootstrap_mean_ci(
            full_minus_passive_final, bootstrap_seed + 17
        ),
        "full_final_rmse_mean": float(np.mean(full_final)),
        "full_final_rmse_ci95": _bootstrap_mean_ci(full_final, bootstrap_seed + 19),
        "valid_observation_ratio": min(
            float(summary["valid_observation_ratio"]) for summary in source_summaries
        ),
        "safety_aborts": sum(int(summary["safety_aborts"]) for summary in source_summaries),
        "maximum_abort_latency_s": max(
            float(summary["maximum_abort_latency_s"]) for summary in source_summaries
        ),
        "serious_safety_events": sum(
            int(summary["serious_safety_events"]) for summary in source_summaries
        ),
        "finite": bool(
            np.all(np.isfinite(full_final))
            and np.all(np.isfinite(early_improvement))
            and np.all(np.isfinite(frozen_improvement))
        ),
    }


def _evaluate(contexts: list[dict[str, Any]], gates: dict[str, Any]) -> dict[str, bool]:
    return {
        "context_coverage": len(contexts) >= int(gates["minimum_scenarios"]),
        "seed_coverage": all(
            int(item["num_seeds"]) >= 2 * int(gates["minimum_seeds_per_scenario"])
            for item in contexts
        ),
        "false_alarm_control": all(
            float(item["no_shift_false_alarm_rate_ci95"][1])
            <= float(gates["maximum_no_shift_false_alarm_rate_ci95_upper"])
            for item in contexts
        ),
        "detection_rate": all(
            float(item["detection_rate"]) >= float(gates["minimum_detection_rate"])
            and float(item["detection_rate_ci95"][0])
            >= float(gates["minimum_detection_rate_ci95_lower"])
            for item in contexts
        ),
        "detection_delay": all(
            float(item["median_detection_delay_trials"])
            <= float(gates["maximum_median_detection_delay_trials"])
            and float(item["p95_detection_delay_trials"])
            <= float(gates["maximum_p95_detection_delay_trials"])
            for item in contexts
        ),
        "full_recovery": all(
            float(item["full_recovery_rate"]) >= float(gates["minimum_full_recovery_rate"])
            and float(item["full_recovery_rate_ci95"][0])
            >= float(gates["minimum_full_recovery_rate_ci95_lower"])
            and float(item["median_full_recovery_trials"])
            <= float(gates["maximum_median_recovery_trials"])
            and float(item["p95_full_recovery_trials"])
            <= float(gates["maximum_p95_recovery_trials"])
            for item in contexts
        ),
        "active_over_passive": all(
            float(item["full_vs_passive_early_rmse_improvement_ci95"][0])
            > float(gates["minimum_full_vs_passive_early_rmse_improvement_ci95_lower"])
            and float(item["full_vs_passive_early_rmse_wilcoxon_one_sided_p"])
            <= float(gates["maximum_full_vs_passive_early_rmse_p"])
            for item in contexts
        ),
        "active_terminal_accuracy": all(
            float(item["full_final_rmse_ci95"][1])
            <= float(gates["maximum_full_final_rmse_ci95_upper"])
            for item in contexts
        ),
        "active_over_frozen": all(
            float(item["full_vs_frozen_final_improvement_ci95"][0])
            > float(gates["minimum_full_vs_frozen_improvement_ci95_lower"])
            and float(item["full_vs_frozen_win_rate"]) >= float(gates["minimum_full_win_rate"])
            for item in contexts
        ),
        "valid_observations": all(
            float(item["valid_observation_ratio"])
            >= float(gates["minimum_valid_observation_ratio"])
            for item in contexts
        ),
        "safety": (
            sum(int(item["serious_safety_events"]) for item in contexts)
            <= int(gates["maximum_serious_safety_events"])
            and max(float(item["maximum_abort_latency_s"]) for item in contexts)
            <= float(gates["maximum_abort_latency_s"])
        ),
        "finite": all(bool(item["finite"]) for item in contexts),
    }


def _compact_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "context": item["context"],
        "n": item["num_seeds"],
        "detected": item["detection_count"],
        "detection_rate": item["detection_rate"],
        "detection_ci95_low": item["detection_rate_ci95"][0],
        "detection_ci95_high": item["detection_rate_ci95"][1],
        "recovered": item["full_recovery_count"],
        "recovery_rate": item["full_recovery_rate"],
        "recovery_ci95_low": item["full_recovery_rate_ci95"][0],
        "recovery_ci95_high": item["full_recovery_rate_ci95"][1],
        "median_detection_trials": item["median_detection_delay_trials"],
        "p95_detection_trials": item["p95_detection_delay_trials"],
        "median_recovery_trials": item["median_full_recovery_trials"],
        "p95_recovery_trials": item["p95_full_recovery_trials"],
        "active_minus_passive_early_gain": item["full_vs_passive_early_rmse_improvement_mean"],
        "active_minus_passive_early_ci95_low": item["full_vs_passive_early_rmse_improvement_ci95"][
            0
        ],
        "active_minus_passive_early_ci95_high": item["full_vs_passive_early_rmse_improvement_ci95"][
            1
        ],
        "active_vs_passive_p": item["full_vs_passive_early_rmse_wilcoxon_one_sided_p"],
        "full_final_rmse": item["full_final_rmse_mean"],
        "full_final_rmse_ci95_low": item["full_final_rmse_ci95"][0],
        "full_final_rmse_ci95_high": item["full_final_rmse_ci95"][1],
        "serious_safety_events": item["serious_safety_events"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    outputs = [path.resolve() for path in args.block]
    destination = args.output.resolve()
    if len(outputs) != 2:
        raise ValueError("pass exactly two --block arguments")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite pooled evidence: {destination}")

    source_manifests = [_verify_output_manifest(output) for output in outputs]
    configs = [_read_json(output / "resolved_config.json") for output in outputs]
    contexts = _validate_blocks(configs)
    pooled = [
        _pool_context(outputs, configs, context, bootstrap_seed=27000 + 100 * index)
        for index, context in enumerate(contexts)
    ]
    gates = _evaluate(pooled, dict(configs[0]["publication_gates"]))
    summary = {
        "schema_version": "1.0",
        "analysis": "two_block_disjoint_seed_pooling",
        "source_blocks": [str(output) for output in outputs],
        "contexts": pooled,
        "gates": gates,
        "verdict": "GO" if all(gates.values()) else "NO_GO",
    }

    destination.mkdir(parents=True)
    (destination / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(destination / "per_context.csv", [_compact_row(item) for item in pooled])
    for index, (output, manifest, config) in enumerate(
        zip(outputs, source_manifests, configs, strict=True), start=1
    ):
        block_name = f"block_{index}"
        (destination / f"{block_name}_source_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (destination / f"{block_name}_resolved_config.json").write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        scenario_map = _scenario_map(config)
        for context in contexts:
            source_dir = output / "scenarios" / str(scenario_map[context]["id"])
            target_dir = destination / "blocks" / block_name / context
            target_dir.mkdir(parents=True)
            for filename in _COPIED_SCENARIO_ARTIFACTS:
                shutil.copy2(source_dir / filename, target_dir / filename)

    (destination / "README.md").write_text(
        "# Pooled paired-signature confirmation\n\n"
        "This compact evidence tree pools two independently frozen 72-seed "
        "confirmation blocks for each of four shift contexts. The calibration "
        "method, detector, budgets, safety envelope, endpoints, and gates are "
        "identical across blocks; seed blocks, simulator RNG seeds, and post-shift "
        "draws are disjoint. `summary.json` contains the pooled 144-seed statistics "
        "and gate verdict. `per_context.csv` is the plotting table. Source manifests "
        "bind all original artifacts, including omitted full-resolution pose traces.\n",
        encoding="utf-8",
    )
    artifacts: dict[str, dict[str, str]] = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(destination).as_posix()
            artifacts[relative] = {"path": relative, "sha256": file_sha256(path)}
    compact_manifest = {
        "schema_version": "1.0",
        "packaging": "pooled_compact_confirmation",
        "source_output_manifests": [
            {
                "path": str(output / "manifest.json"),
                "sha256": file_sha256(output / "manifest.json"),
            }
            for output in outputs
        ],
        "artifacts": artifacts,
    }
    (destination / "manifest.json").write_text(
        json.dumps(compact_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
