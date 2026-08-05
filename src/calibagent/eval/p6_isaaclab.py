"""Pinned Isaac Lab P6 domain-shift and adaptation benchmark."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray
from scipy import stats

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
        required_methods = {"frozen", "passive", "full"}
        if not required_methods <= set(self.methods) or len(self.methods) != len(
            set(self.methods)
        ):
            raise ValueError(
                "P6 requires unique frozen/passive/full controls"
            )
        if self.experiment_role == "main" and self.methods != (
            "frozen",
            "passive",
            "full",
        ):
            raise ValueError("P6 main evidence requires only frozen/passive/full controls")
        allowed_supplemental = required_methods | {
            "recovery_no_task",
            "recovery_d_opt",
            "recovery_lhs",
            "recovery_random",
        }
        if not set(self.methods) <= allowed_supplemental:
            raise ValueError("P6 contains an unsupported recovery selector")
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("P6 scenario ids must be unique")
        if int(self.trial["recovery_budget_trials"]) > 0.40 * int(
            self.trial["dense_budget_trials"]
        ):
            raise ValueError("P6 recovery budget exceeds 40% of dense")
        minimum_evidence = int(self.detector["minimum_positive_evidence"])
        evidence_window = int(self.detector["evidence_window_trials"])
        if minimum_evidence < 3:
            raise ValueError("P6 detector must reject isolated/two-sample outliers")
        if evidence_window < minimum_evidence:
            raise ValueError("P6 detector evidence window is too short")
        primary_horizon = int(
            self.trial.get(
                "primary_recovery_horizon_trials",
                self.trial["recovery_budget_trials"],
            )
        )
        if not int(self.trial["validation_window"]) <= primary_horizon <= int(
            self.trial["recovery_budget_trials"]
        ):
            raise ValueError("P6 primary recovery horizon must contain a complete window")
        if self.adaptation.get("stop_updates_after_recovery", False) not in {True, False}:
            raise ValueError("P6 stop_updates_after_recovery must be boolean")
        invalid_penalty = float(
            self.adaptation.get("invalid_window_rmse_penalty", 1.0)
        )
        if not np.isfinite(invalid_penalty) or invalid_penalty <= float(
            self.adaptation["target_rmse_ceiling"]
        ):
            raise ValueError("P6 invalid-window penalty must exceed the recovery ceiling")
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
            float(item["median_detection_delay_trials"])
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
    if "minimum_detection_rate_ci95_lower" in gates:
        checks["rate_confidence_bounds"] = all(
            float(item["no_shift_false_alarm_rate_ci95"][1])
            <= float(gates["maximum_no_shift_false_alarm_rate_ci95_upper"])
            and float(item["detection_rate_ci95"][0])
            >= float(gates["minimum_detection_rate_ci95_lower"])
            and float(item["full_recovery_rate_ci95"][0])
            >= float(gates["minimum_full_recovery_rate_ci95_lower"])
            for item in summaries
        )
    if "minimum_full_vs_passive_early_rmse_improvement_ci95_lower" in gates:
        checks["active_over_passive_early_recovery"] = all(
            float(item["full_vs_passive_early_rmse_improvement_ci95"][0])
            > float(gates["minimum_full_vs_passive_early_rmse_improvement_ci95_lower"])
            and float(item["full_vs_passive_early_rmse_wilcoxon_one_sided_p"])
            <= float(gates["maximum_full_vs_passive_early_rmse_p"])
            for item in summaries
        )
    if "maximum_full_minus_passive_final_rmse_ci95_upper" in gates:
        checks["active_terminal_noninferiority"] = all(
            float(item["full_minus_passive_final_rmse_ci95"][1])
            <= float(gates["maximum_full_minus_passive_final_rmse_ci95_upper"])
            for item in summaries
        )
    if "maximum_full_final_rmse_ci95_upper" in gates:
        checks["active_terminal_accuracy"] = all(
            float(item["full_final_rmse_ci95"][1])
            <= float(gates["maximum_full_final_rmse_ci95_upper"])
            for item in summaries
        )
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
    method: str,
) -> dict[str, Any]:
    return {
        **scenario,
        "seeds": [int(item) for item in config.vectorization["seeds"]],
        "methods": [method],
        "trial": config.trial,
        "detector": config.detector,
        "adaptation": config.adaptation,
        "safety": config.safety,
        "simulator_seed": int(config.vectorization["simulator_seed"]) + index,
    }


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty aggregate: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _as_bool(value: str) -> bool:
    if value not in {"True", "False"}:
        raise ValueError(f"invalid serialized boolean: {value}")
    return value == "True"


def _bootstrap_mean_ci(values: NDArray[np.float64], seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    samples = np.mean(
        rng.choice(values, size=(4000, len(values)), replace=True),
        axis=1,
    )
    return [
        float(np.quantile(samples, 0.025)),
        float(np.quantile(samples, 0.975)),
    ]


def _paired_wilcoxon_less(left: NDArray[np.float64], right: NDArray[np.float64]) -> float:
    """Test the preregistered alternative ``left < right`` without warning noise."""

    difference = left - right
    if np.allclose(difference, 0.0):
        return 1.0
    return float(stats.wilcoxon(left, right, alternative="less").pvalue)


def _aggregate_method_outputs(
    scenario: dict[str, Any],
    scenario_output: Path,
    methods: tuple[str, ...],
    simulator_seed: int,
) -> dict[str, Any]:
    summaries = {
        method: json.loads((scenario_output / method / "summary.json").read_text(encoding="utf-8"))
        for method in methods
    }
    rows = [
        row
        for method in methods
        for row in _read_csv_rows(scenario_output / method / "per_seed_metrics.csv")
    ]
    _write_csv_rows(scenario_output / "per_seed_metrics.csv", rows)
    for filename in (
        "monitor_metrics.csv",
        "recovery_metrics.csv",
        "recovery_curve.csv",
    ):
        combined = [
            row for method in methods for row in _read_csv_rows(scenario_output / method / filename)
        ]
        _write_csv_rows(scenario_output / filename, combined)
    indexed = {(str(row["method"]), int(row["seed"])): row for row in rows}
    seeds = sorted(int(row["seed"]) for row in rows if row["method"] == "full")
    improvements = np.asarray(
        [
            float(indexed[("frozen", seed)]["final_rmse"])
            - float(indexed[("full", seed)]["final_rmse"])
            for seed in seeds
        ],
        dtype=np.float64,
    )
    passive_improvements = np.asarray(
        [
            float(indexed[("passive", seed)]["final_rmse"])
            - float(indexed[("full", seed)]["final_rmse"])
            for seed in seeds
        ],
        dtype=np.float64,
    )
    curves = _read_csv_rows(scenario_output / "recovery_curve.csv")
    curve_indexed = {
        (str(row["method"]), int(row["seed"]), int(row["recovery_trial"])): float(
            row["rolling_rmse"]
        )
        for row in curves
    }
    start_trial = int(
        summaries["full"].get(
            "validation_window_trials",
            min(
                int(row["recovery_trial"])
                for row in curves
                if str(row["method"]) == "full"
                and np.isfinite(float(row["rolling_rmse"]))
            ),
        )
    )
    primary_horizon = int(
        summaries["full"].get(
            "primary_recovery_horizon_trials",
            max(int(row["recovery_trial"]) for row in curves),
        )
    )
    primary_trials = tuple(range(start_trial, primary_horizon + 1))
    invalid_window_penalty = float(
        summaries["full"].get("invalid_window_rmse_penalty", 1.0)
    )
    full_early = np.asarray(
        [
            np.mean(
                [
                    curve_indexed.get(
                        ("full", seed, trial),
                        invalid_window_penalty,
                    )
                    for trial in primary_trials
                ]
            )
            for seed in seeds
        ],
        dtype=np.float64,
    )
    passive_early = np.asarray(
        [
            np.mean(
                [
                    curve_indexed.get(
                        ("passive", seed, trial),
                        invalid_window_penalty,
                    )
                    for trial in primary_trials
                ]
            )
            for seed in seeds
        ],
        dtype=np.float64,
    )
    early_improvements = passive_early - full_early
    selector_comparisons: dict[str, dict[str, Any]] = {}
    for offset, method in enumerate(
        item for item in methods if item not in {"frozen", "passive", "full"}
    ):
        selector_early = np.asarray(
            [
                np.mean(
                    [
                        curve_indexed.get(
                            (method, seed, trial),
                            invalid_window_penalty,
                        )
                        for trial in primary_trials
                    ]
                )
                for seed in seeds
            ],
            dtype=np.float64,
        )
        full_improvement = selector_early - full_early
        selector_rows = [indexed[(method, seed)] for seed in seeds]
        selector_comparisons[method] = {
            "selector_minus_full_early_rmse_mean": float(
                np.mean(full_improvement)
            ),
            "selector_minus_full_early_rmse_ci95": _bootstrap_mean_ci(
                full_improvement,
                simulator_seed + 1201 + 20 * offset,
            ),
            "full_early_win_rate": float(np.mean(full_improvement > 0.0)),
            "full_vs_selector_early_wilcoxon_one_sided_p": _paired_wilcoxon_less(
                full_early,
                selector_early,
            ),
            "selector_recovery_rate": float(
                np.mean([_as_bool(row["recovered"]) for row in selector_rows])
            ),
            "selector_final_rmse_mean": float(
                np.mean([float(row["final_rmse"]) for row in selector_rows])
            ),
        }
    full_rows = [indexed[("full", seed)] for seed in seeds]
    full_final_rmse = np.asarray(
        [float(row["final_rmse"]) for row in full_rows],
        dtype=np.float64,
    )
    full_recovered = [
        float(row["recovery_trials"]) for row in full_rows if _as_bool(row["recovered"])
    ]
    full_summary = summaries["full"]
    false_alarm_count = sum(_as_bool(row["false_alarm"]) for row in full_rows)
    detection_count = sum(_as_bool(row["detected"]) for row in full_rows)
    recovery_count = sum(_as_bool(row["recovered"]) for row in full_rows)
    paired_rows = [
        {
            "scenario": str(scenario["id"]),
            "seed": seed,
            "passive_early_mean_rmse": passive_early[index],
            "full_early_mean_rmse": full_early[index],
            "passive_minus_full_early_rmse": early_improvements[index],
            "passive_final_rmse": float(indexed[("passive", seed)]["final_rmse"]),
            "full_final_rmse": float(indexed[("full", seed)]["final_rmse"]),
            "full_minus_passive_final_rmse": -passive_improvements[index],
            "passive_recovery_trials": float(
                indexed[("passive", seed)]["recovery_trials"]
            ),
            "full_recovery_trials": float(indexed[("full", seed)]["recovery_trials"]),
        }
        for index, seed in enumerate(seeds)
    ]
    _write_csv_rows(scenario_output / "paired_recovery_effects.csv", paired_rows)
    aggregate = {
        "schema_version": "1.0",
        "scenario": str(scenario["id"]),
        "num_seeds": len(seeds),
        "methods": list(methods),
        "no_shift_false_alarm_rate": float(full_summary["no_shift_false_alarm_rate"]),
        "no_shift_false_alarm_rate_ci95": list(
            clopper_pearson_interval(false_alarm_count, len(seeds))
        ),
        "detection_rate": float(full_summary["detection_rate"]),
        "detection_rate_ci95": list(
            clopper_pearson_interval(detection_count, len(seeds))
        ),
        "median_detection_delay_trials": float(full_summary["median_detection_delay_trials"]),
        "p95_detection_delay_trials": float(full_summary["p95_detection_delay_trials"]),
        "full_recovery_rate": float(np.mean([_as_bool(row["recovered"]) for row in full_rows])),
        "full_recovery_rate_ci95": list(
            clopper_pearson_interval(recovery_count, len(seeds))
        ),
        "median_full_recovery_trials": (
            float(np.median(full_recovered)) if full_recovered else float("inf")
        ),
        "p95_full_recovery_trials": (
            float(np.quantile(full_recovered, 0.95)) if full_recovered else float("inf")
        ),
        "recovery_to_dense_budget_ratio": float(full_summary["recovery_to_dense_budget_ratio"]),
        "full_vs_frozen_final_improvement_mean": float(np.mean(improvements)),
        "full_vs_frozen_final_improvement_ci95": _bootstrap_mean_ci(
            improvements,
            simulator_seed + 311,
        ),
        "full_vs_frozen_win_rate": float(np.mean(improvements > 0.0)),
        "primary_recovery_horizon_trials": primary_horizon,
        "full_vs_passive_early_rmse_improvement_mean": float(
            np.mean(early_improvements)
        ),
        "full_vs_passive_early_rmse_improvement_ci95": _bootstrap_mean_ci(
            early_improvements,
            simulator_seed + 313,
        ),
        "full_vs_passive_early_rmse_win_rate": float(
            np.mean(early_improvements > 0.0)
        ),
        "full_vs_passive_early_rmse_wilcoxon_one_sided_p": _paired_wilcoxon_less(
            full_early,
            passive_early,
        ),
        "recovery_selector_comparisons": selector_comparisons,
        "full_minus_passive_final_rmse_mean": float(
            np.mean(-passive_improvements)
        ),
        "full_minus_passive_final_rmse_ci95": _bootstrap_mean_ci(
            -passive_improvements,
            simulator_seed + 317,
        ),
        "full_final_rmse_mean": float(np.mean(full_final_rmse)),
        "full_final_rmse_ci95": _bootstrap_mean_ci(
            full_final_rmse,
            simulator_seed + 319,
        ),
        "valid_observation_ratio": min(
            float(item["valid_observation_ratio"]) for item in summaries.values()
        ),
        "safety_aborts": sum(int(item["safety_aborts"]) for item in summaries.values()),
        "maximum_abort_latency_s": max(
            float(item["maximum_abort_latency_s"]) for item in summaries.values()
        ),
        "serious_safety_events": sum(
            int(item["serious_safety_events"]) for item in summaries.values()
        ),
        "finite": bool(
            np.all(np.isfinite(improvements))
            and np.all(np.isfinite(early_improvements))
            and np.all(np.isfinite(passive_improvements))
            and all(bool(item["finite"]) for item in summaries.values())
        ),
        "method_summaries": summaries,
    }
    (scenario_output / "summary.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return aggregate


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
    environment.pop("VIRTUAL_ENV", None)
    environment["TERM"] = "xterm-256color"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in source_paths)
    summaries: list[dict[str, Any]] = []
    for index, scenario in enumerate(config.scenarios):
        scenario_id = str(scenario["id"])
        scenario_output = output / "scenarios" / scenario_id
        scenario_output.mkdir(parents=True)
        for method in config.methods:
            method_output = scenario_output / method
            method_output.mkdir()
            payload_path = method_output / "launch_config.json"
            payload_path.write_text(
                json.dumps(
                    _scenario_payload(config, scenario, index, method),
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
                json.dumps(command, indent=2),
                encoding="utf-8",
            )
            result = _run(command, cwd=root, env=environment, check=False)
            (method_output / "simulator.log").write_text(
                result.stdout + result.stderr,
                encoding="utf-8",
            )
            required = (
                "summary.json",
                "monitor_metrics.csv",
                "recovery_metrics.csv",
                "per_seed_metrics.csv",
                "recovery_curve.csv",
                "pose_trace.csv.gz",
                "shift_events.json",
                "scenario_config.json",
            )
            missing = [name for name in required if not (method_output / name).is_file()]
            if result.returncode != 0 or missing:
                raise RuntimeError(
                    f"P6 scenario {scenario_id}/{method} failed "
                    f"(returncode={result.returncode}, missing={missing}); "
                    f"see {method_output / 'simulator.log'}"
                )
        summaries.append(
            _aggregate_method_outputs(
                scenario,
                scenario_output,
                config.methods,
                int(config.vectorization["simulator_seed"]) + index,
            )
        )
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
