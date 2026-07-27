"""Independent strong-confirmatory readiness audit for P6 and P7."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from calibagent.eval.p6_isaaclab import P6BenchmarkConfig
from calibagent.eval.p7_isaaclab import P7BenchmarkConfig
from calibagent.eval.readiness import (
    AuditCheck,
    PublicationReadinessReport,
    _p6_abort_response_check,
    _p6_checks,
    _p7_checks,
    _trace_table_check,
)
from calibagent.eval.real_replay import file_sha256


def _load_criteria(workspace: Path) -> dict[str, Any]:
    path = workspace / "configs/audit/icra_p6_p7_strong.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a mapping in {path}")
    return payload


def _git_commit_exists(workspace: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=workspace,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _failed_confirmatory_check(
    workspace: Path,
    criteria: dict[str, Any],
) -> AuditCheck:
    section = dict(criteria["p7_failed_confirmatory"])
    evidence = workspace / str(section["evidence"])
    manifest_path = workspace / str(section["source_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))
    selected = [
        path
        for path in evidence.rglob("*")
        if path.is_file()
        and path.name
        in {
            "summary.json",
            "episode_metrics.csv",
            "calibration_validation.csv",
            "resolved_config.json",
        }
    ]
    hashes_match = True
    for path in selected:
        relative = path.relative_to(evidence).as_posix()
        record = dict(manifest.get("artifacts", {}).get(relative, {}))
        hashes_match = bool(
            hashes_match
            and record.get("path") == relative
            and record.get("sha256") == file_sha256(path)
        )
    commit = str(manifest.get("git_commit", ""))
    passed = bool(
        summary.get("verdict") == "NO_GO"
        and len(selected) == int(section["expected_selected_artifacts"])
        and hashes_match
        and file_sha256(workspace / str(section["config"]))
        == manifest.get("config_sha256")
        and _git_commit_exists(workspace, commit)
    )
    return AuditCheck(
        "p7_failed_confirmation_retained",
        passed,
        (
            f"verdict={summary.get('verdict')}, selected_hashes="
            f"{len(selected) if hashes_match else 0}/{section['expected_selected_artifacts']}, "
            f"commit={commit[:12]}"
        ),
    )


def _prospective_replication_check(
    workspace: Path,
    criteria: dict[str, Any],
    *,
    raw: bool = False,
) -> AuditCheck:
    failed_section = dict(criteria["p7_failed_confirmatory"])
    successful_section = dict(criteria["p7_raw" if raw else "p7"])
    failed = P7BenchmarkConfig.from_yaml(workspace / str(failed_section["config"]))
    successful = P7BenchmarkConfig.from_yaml(workspace / str(successful_section["config"]))
    failed_manifest = json.loads(
        (workspace / str(failed_section["source_manifest"])).read_text(encoding="utf-8")
    )
    successful_manifest = json.loads(
        (workspace / str(successful_section["manifest"])).read_text(encoding="utf-8")
    )
    failed_seeds = {int(seed) for seed in failed.vectorization["seeds"]}
    successful_seeds = {int(seed) for seed in successful.vectorization["seeds"]}
    failed_maps = {str(item["id"]) for item in failed.maps}
    successful_maps = {str(item["id"]) for item in successful.maps}
    failed_commit = str(failed_manifest.get("git_commit", ""))
    successful_commit = str(successful_manifest.get("git_commit", ""))
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", failed_commit, successful_commit],
        cwd=workspace,
        capture_output=True,
        check=False,
    )
    passed = bool(
        failed.experiment_role == "confirmatory"
        and successful.experiment_role == "confirmatory"
        and failed_seeds.isdisjoint(successful_seeds)
        and failed_maps.isdisjoint(successful_maps)
        and failed_commit != successful_commit
        and ancestry.returncode == 0
    )
    return AuditCheck(
        "p7_prospective_disjoint_replication",
        passed,
        (
            f"seed_overlap={len(failed_seeds & successful_seeds)}, "
            f"map_overlap={len(failed_maps & successful_maps)}, "
            f"failed_commit={failed_commit[:12]}, success_commit={successful_commit[:12]}, "
            f"commit_ancestry={ancestry.returncode == 0}"
        ),
    )


def build_p6_trace_receipt(workspace: Path, section: dict[str, Any]) -> dict[str, Any]:
    """Audit every full-resolution P6 trace and return a hash-bound receipt."""

    output = workspace / str(section["evidence"])
    config = P6BenchmarkConfig.from_yaml(workspace / str(section["config"]))
    manifest_path = workspace / str(section["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_seeds = {int(seed) for seed in config.vectorization["seeds"]}
    profile_samples = sum(
        [
            max(1, round(float(config.trial["warmup_s"]) * 50.0)),
            max(1, round(float(config.trial["ramp_in_s"]) * 50.0)),
            max(1, round(float(config.trial["settle_s"]) * 50.0)),
            max(30, round(float(config.trial["measure_s"]) * 50.0)),
            max(1, round(float(config.trial["ramp_out_s"]) * 50.0)),
        ]
    )
    trial_count = (
        int(config.trial["pre_calibration_trials"])
        + int(config.trial["pre_monitor_trials"])
        + int(config.trial["shift_monitor_trials"])
        + 2 * int(config.trial["recovery_budget_trials"])
    )
    expected_rows = len(expected_seeds) * profile_samples * trial_count
    traces: dict[str, Any] = {}
    for scenario in config.scenarios:
        scenario_id = str(scenario["id"])
        for method in config.methods:
            relative = f"scenarios/{scenario_id}/{method}/pose_trace.csv.gz"
            path = output / relative
            passed, rows = _trace_table_check(
                path,
                key_columns=["seed", "phase", "trial", "sample"],
                identity={"scenario": scenario_id, "method": method},
                finite_columns=[
                    "timestamp_s",
                    "effective_vx",
                    "effective_vy",
                    "effective_wz",
                    "pose_x",
                    "pose_y",
                    "pose_yaw",
                    "base_height",
                    "roll",
                    "pitch",
                    "velocity_vx",
                    "velocity_vy",
                    "velocity_wz",
                ],
                expected_seeds=expected_seeds,
                expected_rows=expected_rows,
            )
            method_summary = json.loads(
                (path.parent / "summary.json").read_text(encoding="utf-8")
            )
            abort_passed = _p6_abort_response_check(
                path,
                int(method_summary["safety_aborts"]),
                float(config.safety["min_base_height_m"]),
                float(config.safety["max_base_height_m"]),
            )
            digest = file_sha256(path)
            source_record = dict(manifest["artifacts"][relative])
            traces[relative] = {
                "passed": bool(
                    passed
                    and abort_passed
                    and digest == source_record.get("sha256")
                ),
                "rows": rows,
                "seeds": sorted(expected_seeds),
                "sha256": digest,
                "abort_response_passed": abort_passed,
            }
    return {
        "schema_version": "1.0",
        "phase": "P6",
        "source_manifest_sha256": file_sha256(manifest_path),
        "trace_count": len(traces),
        "all_passed": all(bool(item["passed"]) for item in traces.values()),
        "traces": traces,
    }


def build_p7_trace_receipt(workspace: Path, section: dict[str, Any]) -> dict[str, Any]:
    """Audit every full-resolution P7 trace and return a hash-bound receipt."""

    output = workspace / str(section["evidence"])
    config = P7BenchmarkConfig.from_yaml(workspace / str(section["config"]))
    manifest_path = workspace / str(section["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_seeds = {int(seed) for seed in config.vectorization["seeds"]}
    traces: dict[str, Any] = {}
    for map_config in config.maps:
        map_id = str(map_config["id"])
        for method in config.methods:
            relative = f"maps/{map_id}/{method}/nav_trace.csv.gz"
            path = output / relative
            passed, rows = _trace_table_check(
                path,
                key_columns=["seed", "sample"],
                identity={"map": map_id, "method": method},
                finite_columns=[
                    "timestamp_s",
                    "target_x",
                    "target_y",
                    "desired_vx",
                    "desired_vy",
                    "desired_wz",
                    "compensated_vx",
                    "compensated_vy",
                    "compensated_wz",
                    "effective_vx",
                    "effective_vy",
                    "effective_wz",
                    "pose_x",
                    "pose_y",
                    "pose_yaw",
                    "base_height",
                    "roll",
                    "pitch",
                    "velocity_vx",
                    "velocity_vy",
                    "velocity_wz",
                ],
                expected_seeds=expected_seeds,
            )
            digest = file_sha256(path)
            source_record = dict(manifest["artifacts"][relative])
            traces[relative] = {
                "passed": bool(passed and digest == source_record.get("sha256")),
                "rows": rows,
                "seeds": sorted(expected_seeds),
                "sha256": digest,
            }
    return {
        "schema_version": "1.0",
        "phase": "P7",
        "source_manifest_sha256": file_sha256(manifest_path),
        "trace_count": len(traces),
        "all_passed": all(bool(item["passed"]) for item in traces.values()),
        "traces": traces,
    }


def audit_strong_readiness(
    workspace: Path,
    *,
    raw: bool = False,
) -> PublicationReadinessReport:
    """Audit strong P6/P7 evidence from compact or full-resolution trees."""

    root = workspace.resolve()
    criteria = _load_criteria(root)
    suffix = "_raw" if raw else ""
    p6 = dict(criteria[f"p6{suffix}"])
    p7 = dict(criteria[f"p7{suffix}"])
    checks = [
        _failed_confirmatory_check(root, criteria),
        _prospective_replication_check(root, criteria, raw=raw),
        *_p6_checks(
            root,
            {"p6": p6},
            require_versioned_artifacts=not raw,
        ),
        *_p7_checks(
            root,
            {"p7": p7},
            require_versioned_artifacts=not raw,
        ),
    ]
    verdict = "GO" if all(check.passed for check in checks) else "NO_GO"
    return PublicationReadinessReport(
        str(criteria["schema_version"]),
        verdict,
        tuple(checks),
    )
