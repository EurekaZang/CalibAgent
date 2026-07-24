"""Independent evidence gates for P0-P5 publication-readiness claims."""

from __future__ import annotations

import json
import subprocess
import warnings
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from calibagent.backends.replay import OfflineReplayBackend
from calibagent.data.observations import load_observations
from calibagent.eval.capture_plan import CapturePlanConfig, generate_capture_plan
from calibagent.eval.p5_isaaclab import (
    P5BenchmarkConfig,
    evaluate_p5_summaries,
)
from calibagent.eval.real_replay import file_sha256
from calibagent.eval.synthetic import SyntheticDistortion, make_observation
from calibagent.interfaces.types import TrialPolicy
from calibagent.measurement.pipeline import MeasurementPipeline


@dataclass(frozen=True)
class AuditCheck:
    check_id: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class PublicationReadinessReport:
    schema_version: str
    verdict: str
    checks: tuple[AuditCheck, ...]

    @property
    def ready(self) -> bool:
        return self.verdict == "GO"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a mapping in {path}")
    return payload


def _git_check(workspace: Path) -> AuditCheck:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return AuditCheck("p0_versioned_commit", False, "workspace is not a Git worktree")
    return AuditCheck("p0_versioned_commit", True, result.stdout.strip())


def _manifest_check(workspace: Path, criteria: dict[str, Any]) -> AuditCheck:
    paths = [
        workspace / str(relative)
        for relative in criteria["required_versioned_manifests"]
    ]
    missing = [str(path.relative_to(workspace)) for path in paths if not path.is_file()]
    if missing:
        return AuditCheck("p0_versioned_manifests", False, f"missing manifests: {missing}")
    commits = [json.loads(path.read_text(encoding="utf-8"))["git_commit"] for path in paths]
    passed = all(commit not in {"", "UNVERSIONED_WORKTREE"} for commit in commits)
    for commit in commits:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=workspace,
            capture_output=True,
            check=False,
        )
        passed = passed and result.returncode == 0
    return AuditCheck("p0_versioned_manifests", passed, f"recorded commits: {commits}")


def _reproducible_environment_check(workspace: Path) -> AuditCheck:
    workflow = (workspace / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    action_refs = [
        line.split("@", maxsplit=1)[1].split()[0]
        for line in workflow.splitlines()
        if "uses: actions/" in line and "@" in line
    ]
    actions_pinned = bool(action_refs) and all(
        len(reference) == 40 and all(char in "0123456789abcdef" for char in reference)
        for reference in action_refs
    )
    lock_paths = [
        workspace / "env/analysis/requirements.lock.txt",
        workspace / "env/analysis/requirements-dev.lock.txt",
    ]
    locks_complete = all(path.is_file() for path in lock_paths)
    passed = actions_pinned and locks_complete
    return AuditCheck(
        "p0_reproducible_environment",
        passed,
        f"actions_pinned={actions_pinned}, lockfiles={locks_complete}",
    )


def _real_data_checks(workspace: Path, criteria: dict[str, Any]) -> list[AuditCheck]:
    relative = Path(str(criteria["required_real_data_manifest"]))
    path = workspace / relative
    if not path.is_file():
        missing = f"missing {relative}"
        return [
            AuditCheck("p1_real_data_evidence", False, missing),
            AuditCheck("p1_real_data_scale_coverage", False, missing),
            AuditCheck("p1_real_baseline_improvement", False, missing),
            AuditCheck("p1_real_sampling_sensitivity", False, missing),
        ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    real_criteria = criteria["real_data"]
    backend = str(payload.get("backend", ""))
    synthetic = bool(payload.get("synthetic", True))
    robot_model = str(payload.get("robot_model", ""))
    reference_sensor = str(payload.get("reference_sensor", ""))
    artifacts = payload.get("artifacts", {})
    raw_path = path.parent / str(artifacts.get("raw_source", "missing"))
    dataset_path = path.parent / str(artifacts.get("dataset", "missing"))
    plan_path = path.parent / str(artifacts.get("capture_plan", "missing"))
    hashes_valid = (
        raw_path.is_file()
        and dataset_path.is_file()
        and file_sha256(raw_path) == payload.get("source_sha256")
        and file_sha256(dataset_path) == payload.get("dataset_sha256")
        and plan_path.is_file()
        and file_sha256(plan_path) == payload.get("capture_plan_sha256")
    )
    plan_match = float(payload.get("capture_plan_command_match") or 0.0)
    plan_completion = float(payload.get("capture_plan_completion") or 0.0)
    plan_valid = plan_match >= float(
        real_criteria["min_capture_plan_command_match"]
    ) and plan_completion >= float(real_criteria["min_capture_plan_completion"])
    delivery_required = bool(real_criteria.get("require_delivery_verification", False))
    delivery_verified = bool(payload.get("delivery_verified", False))
    traceability = float(payload.get("native_traceability_ratio") or 0.0)
    verification_path = path.parent / str(
        artifacts.get("delivery_verification", "missing")
    )
    archive_path = path.parent / str(artifacts.get("source_archive", "missing"))
    delivery_hashes_valid = bool(
        verification_path.is_file()
        and file_sha256(verification_path) == payload.get("delivery_verification_sha256")
        and archive_path.is_file()
        and file_sha256(archive_path) == payload.get("source_archive_sha256")
    )
    delivery_valid = bool(
        not delivery_required
        or (delivery_verified and traceability == 1.0 and delivery_hashes_valid)
    )
    commit = str(payload.get("git_commit", ""))
    commit_result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=workspace,
        capture_output=True,
        check=False,
    )
    authenticity_passed = (
        backend == "offline_replay"
        and not synthetic
        and robot_model == str(real_criteria["robot_model"])
        and reference_sensor not in {"", "onboard_state", "synthetic"}
        and hashes_valid
        and plan_valid
        and delivery_valid
        and commit_result.returncode == 0
    )
    authenticity = AuditCheck(
        "p1_real_data_evidence",
        authenticity_passed,
        (
            f"backend={backend!r}, synthetic={synthetic}, robot={robot_model!r}, "
            f"reference={reference_sensor!r}, hashes={hashes_valid}, plan={plan_valid}, "
            f"delivery={delivery_valid}, traceability={traceability:.3f}, "
            f"commit={commit[:12]}"
        ),
    )

    if not dataset_path.is_file():
        return [
            authenticity,
            AuditCheck("p1_real_data_scale_coverage", False, "dataset artifact missing"),
            AuditCheck("p1_real_baseline_improvement", False, "dataset artifact missing"),
            AuditCheck("p1_real_sampling_sensitivity", False, "dataset artifact missing"),
        ]
    observations = load_observations(dataset_path)
    valid = [observation for observation in observations if observation.valid]
    sessions = {observation.context.session_id for observation in valid}
    commands = (
        np.vstack([observation.command.as_array() for observation in valid])
        if valid
        else np.empty((0, 3))
    )
    magnitude = float(real_criteria["min_axis_command_magnitude"])
    axis_coverage = bool(
        len(commands)
        and np.all(np.min(commands, axis=0) <= -magnitude)
        and np.all(np.max(commands, axis=0) >= magnitude)
    )
    scale_passed = (
        len(valid) >= int(real_criteria["min_valid_observations"])
        and len(sessions) >= int(real_criteria["min_sessions"])
        and axis_coverage
        and all(observation.raw_ref for observation in valid)
    )
    scale = AuditCheck(
        "p1_real_data_scale_coverage",
        scale_passed,
        (
            f"valid={len(valid)}, sessions={len(sessions)}, axis_coverage={axis_coverage}, "
            f"required_valid={real_criteria['min_valid_observations']}"
        ),
    )

    metrics_path = path.parent / str(artifacts.get("metrics", "missing"))
    if not metrics_path.is_file():
        improvement = AuditCheck(
            "p1_real_baseline_improvement", False, "baseline metrics artifact missing"
        )
    else:
        metrics = pd.read_csv(metrics_path)
        raw_rmse = float(metrics.loc[metrics["model"] == "B0_raw", "validation_rmse"].iloc[0])
        lhs_m0 = float(
            metrics.loc[
                (metrics["sampler"] == "lhs") & (metrics["model"] == "M0_diagonal_affine"),
                "validation_rmse",
            ].iloc[0]
        )
        lhs_m1 = float(
            metrics.loc[
                (metrics["sampler"] == "lhs") & (metrics["model"] == "M1_full_affine"),
                "validation_rmse",
            ].iloc[0]
        )
        raw_reduction = 1.0 - lhs_m1 / raw_rmse
        m0_reduction = 1.0 - lhs_m1 / lhs_m0
        fold_detail = ""
        fold_passed = True
        if bool(real_criteria.get("require_all_session_folds", False)):
            fold_metrics_path = path.parent / str(
                artifacts.get("fold_metrics", "missing")
            )
            if not fold_metrics_path.is_file():
                fold_passed = False
                fold_detail = ", fold_metrics=missing"
            else:
                fold_metrics = pd.read_csv(fold_metrics_path)
                raw_folds = (
                    fold_metrics.loc[
                        fold_metrics["model"] == "B0_raw",
                        ["validation_session", "validation_rmse"],
                    ]
                    .rename(columns={"validation_rmse": "raw_rmse"})
                    .set_index("validation_session")
                )
                m0_folds = (
                    fold_metrics.loc[
                        (fold_metrics["sampler"] == "lhs")
                        & (fold_metrics["model"] == "M0_diagonal_affine"),
                        ["validation_session", "validation_rmse"],
                    ]
                    .rename(columns={"validation_rmse": "m0_rmse"})
                    .set_index("validation_session")
                )
                m1_folds = (
                    fold_metrics.loc[
                        (fold_metrics["sampler"] == "lhs")
                        & (fold_metrics["model"] == "M1_full_affine"),
                        ["validation_session", "validation_rmse"],
                    ]
                    .rename(columns={"validation_rmse": "m1_rmse"})
                    .set_index("validation_session")
                )
                folds = raw_folds.join(m0_folds, how="inner").join(m1_folds, how="inner")
                fold_raw_reduction = 1.0 - folds["m1_rmse"] / folds["raw_rmse"]
                fold_m0_reduction = 1.0 - folds["m1_rmse"] / folds["m0_rmse"]
                enough_folds = len(folds) >= int(real_criteria["min_sessions"])
                fold_passed = bool(
                    enough_folds
                    and np.all(
                        fold_raw_reduction
                        >= float(real_criteria["min_m1_vs_raw_rmse_reduction"])
                    )
                    and np.all(
                        fold_m0_reduction
                        >= float(real_criteria["min_m1_vs_m0_rmse_reduction"])
                    )
                )
                fold_detail = (
                    f", folds={len(folds)}, "
                    f"fold_min_raw={float(fold_raw_reduction.min()):.6f}, "
                    f"fold_min_M0={float(fold_m0_reduction.min()):.6f}"
                    if len(folds)
                    else ", folds=0"
                )
        improvement = AuditCheck(
            "p1_real_baseline_improvement",
            (
                raw_reduction >= float(real_criteria["min_m1_vs_raw_rmse_reduction"])
                and m0_reduction >= float(real_criteria["min_m1_vs_m0_rmse_reduction"])
                and fold_passed
            ),
            (
                f"M1_vs_raw={raw_reduction:.6f}, M1_vs_M0={m0_reduction:.6f}, "
                f"required={real_criteria['min_m1_vs_raw_rmse_reduction']:.2f}/"
                f"{real_criteria['min_m1_vs_m0_rmse_reduction']:.2f}"
                f"{fold_detail}"
            ),
        )
    sensitivity_required = bool(real_criteria.get("require_sampling_sensitivity", False))
    sensitivity_path = path.parent / str(
        artifacts.get("sampling_sensitivity", "missing")
    )
    if not sensitivity_required:
        sensitivity_check = AuditCheck(
            "p1_real_sampling_sensitivity", True, "not required by criteria"
        )
    elif not sensitivity_path.is_file():
        sensitivity_check = AuditCheck(
            "p1_real_sampling_sensitivity",
            False,
            "sampling sensitivity artifact missing",
        )
    elif file_sha256(sensitivity_path) != payload.get("sampling_sensitivity_sha256"):
        sensitivity_check = AuditCheck(
            "p1_real_sampling_sensitivity",
            False,
            "sampling sensitivity hash mismatch",
        )
    else:
        sensitivity = json.loads(sensitivity_path.read_text(encoding="utf-8"))
        decimations = sensitivity.get("decimations", [])
        min_valid = min(
            (int(item.get("valid_observations", 0)) for item in decimations),
            default=0,
        )
        max_velocity_rmse = max(
            (float(item.get("velocity_rmse_to_full", np.inf)) for item in decimations),
            default=float("inf"),
        )
        min_raw_reduction = min(
            (float(item.get("m1_vs_raw_reduction", -np.inf)) for item in decimations),
            default=float("-inf"),
        )
        min_m0_reduction = min(
            (float(item.get("m1_vs_m0_reduction", -np.inf)) for item in decimations),
            default=float("-inf"),
        )
        sensitivity_passed = bool(
            len(decimations) == 2
            and min_valid >= int(real_criteria["min_valid_observations"])
            and max_velocity_rmse <= float(real_criteria["max_decimated_velocity_rmse"])
            and min_raw_reduction
            >= float(real_criteria["min_m1_vs_raw_rmse_reduction"])
            and min_m0_reduction
            >= float(real_criteria["min_m1_vs_m0_rmse_reduction"])
        )
        sensitivity_check = AuditCheck(
            "p1_real_sampling_sensitivity",
            sensitivity_passed,
            (
                f"decimations={len(decimations)}, min_valid={min_valid}, "
                f"max_velocity_rmse={max_velocity_rmse:.6f}, "
                f"min_M1_vs_raw={min_raw_reduction:.6f}, "
                f"min_M1_vs_M0={min_m0_reduction:.6f}"
            ),
        )
    return [authenticity, scale, improvement, sensitivity_check]


def _capture_design_check(workspace: Path, criteria: dict[str, Any]) -> AuditCheck:
    config_path = workspace / str(criteria["required_capture_config"])
    config = CapturePlanConfig.from_yaml(config_path)
    plan = generate_capture_plan(config)
    commands = plan[["cmd_vx", "cmd_vy", "cmd_wz"]].to_numpy(dtype=float)
    real_criteria = criteria["real_data"]
    magnitude = float(real_criteria["min_axis_command_magnitude"])
    signed_coverage = bool(
        np.all(np.min(commands, axis=0) <= -magnitude)
        and np.all(np.max(commands, axis=0) >= magnitude)
    )
    required_planned = int(
        np.ceil(
            int(real_criteria["min_valid_observations"])
            / float(real_criteria["min_capture_plan_completion"])
        )
    )
    passed = (
        plan["session_id"].nunique() >= int(real_criteria["min_sessions"])
        and len(plan) >= required_planned
        and signed_coverage
        and bool(np.all(np.linalg.norm(commands[:, :2], axis=1) <= config.max_linear_norm))
    )
    return AuditCheck(
        "p1_frozen_capture_design",
        passed,
        (
            f"sessions={plan['session_id'].nunique()}, planned={len(plan)}/{required_planned}, "
            f"signed_axes={signed_coverage}, max_linear_norm={config.max_linear_norm:.2f}"
        ),
    )


def _replay_vertical_slice_check(
    workspace: Path, criteria: dict[str, Any]
) -> AuditCheck:
    dataset = workspace / str(criteria["p1_vertical_slice_dataset"])
    if not dataset.is_file():
        return AuditCheck("p1_replay_measurement_vertical_slice", False, "baseline dataset missing")
    observations = load_observations(dataset)
    if not observations:
        return AuditCheck(
            "p1_replay_measurement_vertical_slice", False, "baseline dataset is empty"
        )
    backend = OfflineReplayBackend([observations[0]])
    raw = backend.execute_trial(observations[0].command, TrialPolicy())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        processed = MeasurementPipeline().process(raw)
    return AuditCheck(
        "p1_replay_measurement_vertical_slice",
        processed.valid,
        (
            f"samples={len(raw.timestamps)}, "
            f"reconstructed={raw.metadata.get('reconstructed_from_aggregate', False)}, "
            f"quality={processed.quality.get('reason_codes', '')}"
        ),
    )


def _noise_contract_check(workspace: Path) -> AuditCheck:
    config = _load_yaml(workspace / "configs/experiments/p3_synthetic_pilot.yaml")
    configured = np.asarray(config["assumed_noise_variance"], dtype=np.float64)
    distortion = SyntheticDistortion.from_seed("affine", 1011)
    command = np.asarray([0.2, 0.0, 0.1], dtype=np.float64)
    observation = make_observation(distortion, command, np.random.default_rng(1), 0)
    generative = distortion.noise_std(command) ** 2
    update_variance = configured + np.diag(observation.covariance)
    passed = bool(np.allclose(update_variance, generative, rtol=1e-8, atol=1e-12))
    return AuditCheck(
        "p2_synthetic_noise_contract",
        passed,
        f"generative={generative.tolist()}, update={update_variance.tolist()}",
    )


def _coverage_check(metrics: pd.DataFrame, uncertainty_criteria: dict[str, Any]) -> AuditCheck:
    active = metrics[metrics["method"] == "active"]
    coverage = float(active["final_coverage_95"].mean())
    low = float(uncertainty_criteria["coverage_95_min"])
    high = float(uncertainty_criteria["coverage_95_max"])
    return AuditCheck(
        "p2_synthetic_coverage",
        low <= coverage <= high,
        f"mean={coverage:.6f}, target=[{low:.2f}, {high:.2f}]",
    )


def _stratified_coverage_check(
    metrics: pd.DataFrame, uncertainty_criteria: dict[str, Any]
) -> AuditCheck:
    active = metrics[metrics["method"] == "active"]
    grouped = active.groupby("family")["final_coverage_95"].mean()
    low = float(uncertainty_criteria["coverage_95_min"])
    high = float(uncertainty_criteria["coverage_95_max"])
    passed = bool(len(grouped) > 0 and np.all((grouped >= low) & (grouped <= high)))
    evidence = ", ".join(f"{name}={value:.6f}" for name, value in grouped.items())
    return AuditCheck(
        "p2_stratified_synthetic_coverage",
        passed,
        f"family_means=[{evidence}], target=[{low:.2f}, {high:.2f}]",
    )


def _p3_checks(
    metrics: pd.DataFrame, pilot_config: dict[str, Any], criteria: dict[str, Any]
) -> list[AuditCheck]:
    statistical = criteria["statistics"]
    methods = set(str(method) for method in pilot_config["methods"])
    required = set(str(method) for method in criteria["required_p3_methods"])
    method_check = AuditCheck(
        "p3_required_baselines",
        required <= methods,
        f"missing={sorted(required - methods)}",
    )

    families = set(str(family) for family in pilot_config["families"])
    expected_rows = len(methods) * len(families) * len(pilot_config["seeds"])
    key_columns = ["family", "method", "seed"]
    complete_keys = not metrics.duplicated(key_columns).any()
    actual_keys = set(map(tuple, metrics[key_columns].itertuples(index=False, name=None)))
    expected_keys = {
        (family, method, int(seed))
        for family in families
        for method in methods
        for seed in pilot_config["seeds"]
    }
    finite_columns = [
        "trials_to_target",
        "final_rmse",
        "final_uncertainty",
        "final_coverage_95",
    ]
    finite = bool(np.all(np.isfinite(metrics[finite_columns].to_numpy(dtype=float))))
    completeness_check = AuditCheck(
        "p3_main_artifact_completeness",
        len(metrics) == expected_rows and actual_keys == expected_keys and complete_keys and finite,
        (
            f"rows={len(metrics)}/{expected_rows}, keys_complete={actual_keys == expected_keys}, "
            f"unique={complete_keys}, finite={finite}"
        ),
    )

    seeds = sorted(int(seed) for seed in pilot_config["seeds"])
    min_seeds = int(statistical["min_main_seeds_per_family"])
    seed_check = AuditCheck(
        "p3_main_seed_count",
        len(seeds) >= min_seeds,
        f"observed={len(seeds)}, required={min_seeds}",
    )

    # Families share latent parameters for a given seed, so seed—not
    # (family, seed)—is the conservative independent unit for this pilot.
    aggregated = metrics.groupby(["seed", "method"], as_index=False)["trials_to_target"].mean()
    baseline_name = str(statistical["primary_baseline"])
    active = aggregated[aggregated["method"] == "active"].set_index("seed")
    baseline = aggregated[aggregated["method"] == baseline_name].set_index("seed")
    common = active.index.intersection(baseline.index)
    active_trials = active.loc[common, "trials_to_target"].to_numpy(dtype=np.float64)
    baseline_trials = baseline.loc[common, "trials_to_target"].to_numpy(dtype=np.float64)
    if len(common) and np.any(active_trials != baseline_trials):
        p_value = float(stats.wilcoxon(active_trials, baseline_trials, alternative="less").pvalue)
    else:
        p_value = 1.0
    alpha = float(statistical["alpha"])
    significance_check = AuditCheck(
        "p3_primary_independent_significance",
        p_value < alpha,
        f"unit=seed, n={len(common)}, p={p_value:.8f}, alpha={alpha:.3f}",
    )

    reduction = 1.0 - float(np.mean(active_trials) / np.mean(baseline_trials))
    required_reduction = float(statistical["min_relative_trials_reduction"])
    effect_check = AuditCheck(
        "p3_target_effect_size",
        reduction >= required_reduction,
        f"observed={reduction:.6f}, required={required_reduction:.2f}",
    )
    no_task = aggregated[aggregated["method"] == "active_no_task"].set_index("seed")
    no_task_common = active.index.intersection(no_task.index)
    no_task_active = active.loc[no_task_common, "trials_to_target"].to_numpy(dtype=np.float64)
    no_task_baseline = no_task.loc[no_task_common, "trials_to_target"].to_numpy(dtype=np.float64)
    if len(no_task_common) and np.any(no_task_active != no_task_baseline):
        no_task_p = float(
            stats.wilcoxon(no_task_active, no_task_baseline, alternative="less").pvalue
        )
    else:
        no_task_p = 1.0
    no_task_reduction = 1.0 - float(np.mean(no_task_active) / np.mean(no_task_baseline))
    required_no_task = float(statistical["min_task_ablation_reduction"])
    ablation_check = AuditCheck(
        "p3_task_weight_ablation",
        no_task_p < alpha and no_task_reduction >= required_no_task,
        (
            f"unit=seed, n={len(no_task_common)}, p={no_task_p:.8f}, "
            f"reduction={no_task_reduction:.6f}, required={required_no_task:.2f}"
        ),
    )

    active_final = metrics[metrics["method"] == "active"]["final_rmse"].to_numpy(dtype=float)
    dense_final = metrics[metrics["method"] == "dense"]["final_rmse"].to_numpy(dtype=float)
    dense_gap = float(np.mean(active_final) / np.mean(dense_final) - 1.0)
    max_dense_gap = float(statistical["max_dense_oracle_rmse_gap"])
    dense_check = AuditCheck(
        "p3_dense_oracle_gap",
        dense_gap <= max_dense_gap,
        f"observed={dense_gap:.6f}, maximum={max_dense_gap:.2f}",
    )
    return [
        method_check,
        completeness_check,
        seed_check,
        significance_check,
        effect_check,
        ablation_check,
        dense_check,
    ]


def _commit_exists(workspace: Path, commit: str) -> bool:
    if not commit:
        return False
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=workspace,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _phase_manifest_check(
    workspace: Path,
    manifest_path: Path,
    phase: str,
) -> AuditCheck:
    check_id = f"{phase.lower()}_manifest_integrity"
    if not manifest_path.is_file():
        return AuditCheck(check_id, False, f"missing {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence_root = manifest_path.parent
    artifact_records = payload.get("artifacts", {})
    artifact_hashes = []
    for record in artifact_records.values():
        path = evidence_root / str(record.get("path", "missing"))
        artifact_hashes.append(
            path.is_file() and file_sha256(path) == str(record.get("sha256", ""))
        )
    config_path = workspace / str(payload.get("config_path", "missing"))
    config_valid = bool(
        config_path.is_file()
        and file_sha256(config_path) == payload.get("config_sha256")
    )
    source_valid = True
    if "source_trace" in payload:
        source = workspace / str(payload["source_trace"])
        source_valid = bool(
            source.is_file()
            and file_sha256(source) == payload.get("source_trace_sha256")
        )
    commit = str(payload.get("git_commit", ""))
    passed = bool(
        payload.get("phase") == phase
        and artifact_records
        and all(artifact_hashes)
        and config_valid
        and source_valid
        and _commit_exists(workspace, commit)
    )
    return AuditCheck(
        check_id,
        passed,
        (
            f"artifacts={sum(artifact_hashes)}/{len(artifact_hashes)}, "
            f"config={config_valid}, source={source_valid}, commit={commit[:12]}"
        ),
    )


def _p4_checks(workspace: Path, criteria: dict[str, Any]) -> list[AuditCheck]:
    section = dict(criteria["p4"])
    evidence = workspace / str(section["evidence"])
    manifest_check = _phase_manifest_check(
        workspace,
        workspace / str(section["manifest"]),
        "P4",
    )
    config = _load_yaml(workspace / str(section["config"]))
    gates = config["publication_gates"]
    stop = pd.read_csv(evidence / "stop_results.csv")
    faults = pd.read_csv(evidence / "fault_injection.csv")
    runtime = pd.read_csv(evidence / "runtime_faults.csv")
    state_trace = pd.read_csv(evidence / "state_machine_trace.csv")
    summary = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))

    expected_stop_keys = {
        (str(family), int(seed))
        for family in config["expected_families"]
        for seed in config["expected_seeds"]
    }
    actual_stop_keys = set(
        stop[["family", "seed"]].itertuples(index=False, name=None)
    )
    premature_rate = float(stop["premature"].astype(bool).mean())
    median_extra = float(stop["extra_trials"].median())
    p95_extra = float(stop["extra_trials"].quantile(0.95))
    stopping_passed = bool(
        actual_stop_keys == expected_stop_keys
        and not stop.duplicated(["family", "seed"]).any()
        and premature_rate < float(gates["maximum_premature_stop_rate"])
        and median_extra <= float(gates["maximum_median_extra_trials"])
        and p95_extra <= float(gates["maximum_p95_extra_trials"])
        and np.isclose(premature_rate, summary["premature_stop_rate"])
        and np.isclose(median_extra, summary["median_extra_trials"])
        and np.isclose(p95_extra, summary["p95_extra_trials"])
    )
    stopping_check = AuditCheck(
        "p4_validation_gated_stopping",
        stopping_passed,
        (
            f"runs={len(stop)}/{len(expected_stop_keys)}, premature={premature_rate:.4f}, "
            f"median_extra={median_extra:.2f}, p95_extra={p95_extra:.2f}"
        ),
    )

    hazards = faults[faults["hazard"].astype(bool)]
    safe = faults[~faults["hazard"].astype(bool)]
    rejection = float((~hazards["accepted"].astype(bool)).mean())
    expected_reason = float(hazards["expected_reason_present"].astype(bool).mean())
    false_rejection = float((~safe["accepted"].astype(bool)).mean())
    maximum_latency = float(runtime["abort_latency_s"].max())
    serious = int(runtime["serious_event"].astype(bool).sum())
    safety_passed = bool(
        rejection >= float(gates["minimum_hazard_rejection_rate"])
        and expected_reason == 1.0
        and false_rejection <= float(gates["maximum_safe_false_rejection_rate"])
        and runtime["detected"].astype(bool).all()
        and maximum_latency
        <= float(config["fault_injection"]["maximum_abort_latency_s"])
        and serious <= int(gates["maximum_serious_events"])
        and np.isclose(rejection, summary["hazard_rejection_rate"])
        and np.isclose(false_rejection, summary["safe_false_rejection_rate"])
    )
    safety_check = AuditCheck(
        "p4_fault_injection_and_abort",
        safety_passed,
        (
            f"hazards={len(hazards)}, rejected={rejection:.4f}, "
            f"safe_false_rejection={false_rejection:.4f}, "
            f"max_abort_latency={maximum_latency:.3f}s, serious={serious}"
        ),
    )

    terminal = (
        state_trace.sort_values("index")
        .groupby("run_id", sort=True)
        .tail(1)
        .set_index("run_id")["target"]
        .to_dict()
    )
    state_passed = bool(
        terminal == {"fault": "abort", "happy": "done"}
        and summary.get("verdict") == "GO"
        and all(bool(value) for value in summary.get("gates", {}).values())
    )
    state_check = AuditCheck(
        "p4_runtime_state_machine",
        state_passed,
        f"terminal={terminal}, frozen_verdict={summary.get('verdict')}",
    )
    return [manifest_check, stopping_check, safety_check, state_check]


def _p5_recompute_scenario(
    scenario_dir: Path,
    scenario: dict[str, Any],
    config: P5BenchmarkConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = pd.read_csv(scenario_dir / "trial_metrics.csv")
    launch = json.loads(
        (scenario_dir / "launch_config.json").read_text(encoding="utf-8")
    )
    calibration = metrics[metrics["phase"] == "calibration"].copy()
    validation = metrics[metrics["phase"] == "validation"].copy()
    calibration_valid = calibration["valid"].astype(bool)
    validation_valid = validation["valid"].astype(bool)
    valid_validation = validation[validation_valid].copy()
    command_columns = ["cmd_vx", "cmd_vy", "cmd_wz"]
    measured_columns = ["measured_vx", "measured_vy", "measured_wz"]
    predicted_columns = ["predicted_vx", "predicted_vy", "predicted_wz"]
    predicted_std_columns = [
        "predicted_std_vx",
        "predicted_std_vy",
        "predicted_std_wz",
    ]
    command = valid_validation[command_columns].to_numpy(dtype=np.float64)
    measured = valid_validation[measured_columns].to_numpy(dtype=np.float64)
    predicted = valid_validation[predicted_columns].to_numpy(dtype=np.float64)
    predicted_std = valid_validation[predicted_std_columns].to_numpy(
        dtype=np.float64
    )
    raw_rmse = float(np.sqrt(np.mean((command - measured) ** 2)))
    calibrated_rmse = float(np.sqrt(np.mean((predicted - measured) ** 2)))
    nonzero = np.linalg.norm(command, axis=1) > 0.05
    actual_motion = np.linalg.norm(measured, axis=1) > 0.03

    improvements = []
    for seed in launch["seeds"]:
        seed_rows = valid_validation[valid_validation["seed"] == int(seed)]
        seed_command = seed_rows[command_columns].to_numpy(dtype=np.float64)
        seed_measured = seed_rows[measured_columns].to_numpy(dtype=np.float64)
        seed_predicted = seed_rows[predicted_columns].to_numpy(dtype=np.float64)
        seed_raw = float(np.sqrt(np.mean((seed_command - seed_measured) ** 2)))
        seed_calibrated = float(
            np.sqrt(np.mean((seed_predicted - seed_measured) ** 2))
        )
        improvements.append(seed_raw - seed_calibrated)
    improvement_array = np.asarray(improvements, dtype=np.float64)
    bootstrap_rng = np.random.default_rng(int(launch["simulator_seed"]) + 191)
    bootstrap = np.mean(
        bootstrap_rng.choice(
            improvement_array,
            size=(2000, len(improvement_array)),
            replace=True,
        ),
        axis=1,
    )
    safety_text = metrics["safety_events"].fillna("").astype(str)
    safety_aborts = int((safety_text != "").sum())
    simulator_terminations = int(
        safety_text.str.contains("SIM_TERMINATION", regex=False).sum()
    )
    recomputed = {
        "scenario": str(scenario["id"]),
        "tier": str(scenario["tier"]),
        "num_envs": len(launch["seeds"]),
        "valid_calibration_ratio": float(calibration_valid.mean()),
        "valid_validation_ratio": float(validation_valid.mean()),
        "actual_motion_ratio": float(np.mean(actual_motion[nonzero])),
        "raw_rmse": raw_rmse,
        "calibrated_rmse": calibrated_rmse,
        "calibrated_vs_raw_reduction": 1.0 - calibrated_rmse / raw_rmse,
        "paired_absolute_improvement_mean": float(np.mean(improvement_array)),
        "paired_absolute_improvement_ci95": [
            float(np.quantile(bootstrap, 0.025)),
            float(np.quantile(bootstrap, 0.975)),
        ],
        "calibrated_win_rate": float(np.mean(improvement_array > 0.0)),
        "predictive_coverage_95": float(
            np.mean(np.abs(measured - predicted) <= 1.96 * predicted_std)
        ),
        "safety_aborts": safety_aborts,
        "maximum_abort_latency_s": (
            1.0 / float(launch["sample_rate_hz"]) if safety_aborts else 0.0
        ),
        "simulator_terminations": simulator_terminations,
        "serious_safety_events": simulator_terminations,
        "finite": bool(
            np.all(np.isfinite(command))
            and np.all(np.isfinite(measured))
            and np.all(np.isfinite(predicted))
            and np.all(np.isfinite(predicted_std))
            and np.all(np.isfinite(improvement_array))
        ),
    }
    expected_seeds = {int(seed) for seed in config.vectorization["seeds"]}
    expected_calibration = len(expected_seeds) * int(
        config.trial["calibration_trials"]
    )
    expected_validation = len(expected_seeds) * 8
    launch_consistent = bool(
        set(int(seed) for seed in launch["seeds"]) == expected_seeds
        and launch["scenario_id"] == scenario["id"]
        and launch["tier"] == scenario["tier"]
        and launch["task"] == scenario["task"]
        and launch["distortion"] == scenario["distortion"]
        and np.isclose(
            launch["safety_max_coupled_load"],
            config.safety["max_coupled_load"],
        )
        and np.isclose(launch["model_prior_scale"], config.model["prior_scale"])
    )
    keys_unique = bool(
        not metrics.duplicated(["seed", "phase", "trial"]).any()
        and set(metrics["seed"].astype(int)) == expected_seeds
    )
    detail = {
        "rows_complete": len(calibration) == expected_calibration
        and len(validation) == expected_validation,
        "keys_unique": keys_unique,
        "launch_consistent": launch_consistent,
    }
    return recomputed, detail


def _p5_checks(workspace: Path, criteria: dict[str, Any]) -> list[AuditCheck]:
    section = dict(criteria["p5"])
    evidence = workspace / str(section["evidence"])
    manifest_path = workspace / str(section["manifest"])
    manifest_check = _phase_manifest_check(workspace, manifest_path, "P5")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config_path = workspace / str(section["config"])
    config = P5BenchmarkConfig.from_yaml(config_path)

    runtime = manifest.get("runtime", {})
    checkpoints = manifest.get("checkpoints", {})
    runtime_passed = bool(
        manifest.get("backend") == section["required_backend"]
        and runtime.get("isaaclab_commit") == config.isaaclab["commit"]
        and str(runtime.get("isaac_sim_version", "")).startswith(
            str(config.isaaclab["isaac_sim_version_prefix"])
        )
        and config.isaaclab["physics_backend"]
        == section["required_physics_backend"]
        and all(
            checkpoints.get(alias, {}).get("sha256") == specification["sha256"]
            for alias, specification in config.checkpoints.items()
        )
    )
    runtime_check = AuditCheck(
        "p5_pinned_isaac_runtime",
        runtime_passed,
        (
            f"IsaacLab={str(runtime.get('isaaclab_commit', ''))[:12]}, "
            f"IsaacSim={runtime.get('isaac_sim_version')}, "
            f"GPU={runtime.get('gpu_and_driver')}"
        ),
    )

    recomputed = []
    details = []
    summary_matches = []
    per_seed_matches = []
    trace_complete = []
    abort_responses = []
    physical_events = []
    for scenario in config.scenarios:
        scenario_dir = evidence / "scenarios" / str(scenario["id"])
        values, detail = _p5_recompute_scenario(
            scenario_dir,
            scenario,
            config,
        )
        recomputed.append(values)
        details.append(detail)
        frozen = json.loads(
            (scenario_dir / "summary.json").read_text(encoding="utf-8")
        )
        scalar_keys = [
            "valid_calibration_ratio",
            "valid_validation_ratio",
            "actual_motion_ratio",
            "raw_rmse",
            "calibrated_rmse",
            "calibrated_vs_raw_reduction",
            "paired_absolute_improvement_mean",
            "calibrated_win_rate",
            "predictive_coverage_95",
            "maximum_abort_latency_s",
        ]
        summary_matches.append(
            all(np.isclose(values[key], frozen[key]) for key in scalar_keys)
            and np.allclose(
                values["paired_absolute_improvement_ci95"],
                frozen["paired_absolute_improvement_ci95"],
            )
            and values["safety_aborts"] == frozen["safety_aborts"]
            and values["serious_safety_events"]
            == frozen["serious_safety_events"]
            and values["finite"] == frozen["finite"]
        )
        per_seed = pd.read_csv(scenario_dir / "per_seed_metrics.csv")
        per_seed_matches.append(
            len(per_seed) == len(config.vectorization["seeds"])
            and set(per_seed["seed"].astype(int))
            == set(int(seed) for seed in config.vectorization["seeds"])
            and np.isclose(
                float(per_seed["absolute_improvement"].mean()),
                values["paired_absolute_improvement_mean"],
            )
        )

        trace = pd.read_csv(scenario_dir / "pose_trace.csv")
        profile_samples = sum(
            [
                max(1, round(float(config.trial["warmup_s"]) * 50.0)),
                max(1, round(float(config.trial["ramp_in_s"]) * 50.0)),
                max(1, round(float(config.trial["settle_s"]) * 50.0)),
                max(30, round(float(config.trial["measure_s"]) * 50.0)),
                max(1, round(float(config.trial["ramp_out_s"]) * 50.0)),
            ]
        )
        expected_trace_rows = (
            len(config.vectorization["seeds"])
            * (int(config.trial["calibration_trials"]) + 8)
            * profile_samples
        )
        finite_trace_columns = [
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
        ]
        trace_complete.append(
            len(trace) == expected_trace_rows
            and not trace.duplicated(
                ["seed", "phase", "trial", "sample"]
            ).any()
            and np.all(
                np.isfinite(trace[finite_trace_columns].to_numpy(dtype=float))
            )
        )
        scenario_response = True
        for _, group in trace.groupby(
            ["seed", "phase", "trial"],
            sort=False,
        ):
            aborted = group["aborted"].astype(bool).to_numpy()
            if not np.any(aborted):
                continue
            first = int(np.flatnonzero(aborted)[0])
            if first + 1 < len(group):
                next_effective = group.iloc[first + 1][
                    ["effective_vx", "effective_vy", "effective_wz"]
                ].to_numpy(dtype=float)
                scenario_response = scenario_response and bool(
                    np.linalg.norm(next_effective) <= 1e-12
                )
        abort_responses.append(scenario_response)
        simulator_log = (scenario_dir / "simulator.log").read_text(
            encoding="utf-8"
        )
        physical_events.append(
            bool(
                float(scenario["com_offset_x_m"]) == 0.0
                or "base_com" in simulator_log
            )
        )

    aggregate = evaluate_p5_summaries(config, recomputed)
    frozen_aggregate = json.loads(
        (evidence / "summary.json").read_text(encoding="utf-8")
    )
    expected_ids = {str(item["id"]) for item in config.scenarios}
    actual_ids = {str(item["scenario"]) for item in recomputed}
    coverage_passed = bool(
        expected_ids == actual_ids
        and len([item for item in recomputed if item["tier"] == "A"]) >= 2
        and len([item for item in recomputed if item["tier"] == "B"]) >= 2
        and all(detail["rows_complete"] for detail in details)
        and all(detail["keys_unique"] for detail in details)
        and all(detail["launch_consistent"] for detail in details)
        and all(per_seed_matches)
    )
    coverage_check = AuditCheck(
        "p5_vectorized_scenario_coverage",
        coverage_passed,
        (
            f"scenarios={len(actual_ids)}/4, seeds_per_scenario="
            f"{aggregate['seeds_per_scenario']}, rows_and_keys={coverage_passed}"
        ),
    )
    metric_passed = bool(
        all(summary_matches)
        and aggregate["verdict"] == "GO"
        and frozen_aggregate.get("verdict") == "GO"
        and all(bool(value) for value in aggregate["gates"].values())
    )
    metric_check = AuditCheck(
        "p5_recomputed_calibration_statistics",
        metric_passed,
        (
            f"min_reduction={aggregate['minimum_calibrated_vs_raw_reduction']:.6f}, "
            f"min_CI_lower={aggregate['minimum_paired_improvement_ci95_lower']:.6f}, "
            f"summaries_match={all(summary_matches)}"
        ),
    )
    trace_check = AuditCheck(
        "p5_pose_trace_completeness",
        all(trace_complete),
        f"complete_finite_unique={sum(trace_complete)}/{len(trace_complete)}",
    )
    safety_passed = bool(
        all(abort_responses)
        and all(physical_events)
        and aggregate["gates"]["safety_abort_latency"]
        and aggregate["gates"]["serious_safety_events"]
    )
    safety_check = AuditCheck(
        "p5_physical_variation_and_safety",
        safety_passed,
        (
            f"COM_events={sum(physical_events)}/{len(physical_events)}, "
            f"abort_zero_next_cycle={sum(abort_responses)}/{len(abort_responses)}, "
            f"max_latency={aggregate['maximum_abort_latency_s']:.3f}s, "
            f"serious={aggregate['total_serious_safety_events']}"
        ),
    )
    return [
        manifest_check,
        runtime_check,
        coverage_check,
        metric_check,
        trace_check,
        safety_check,
    ]


@lru_cache(maxsize=4)
def audit_publication_readiness(workspace: Path) -> PublicationReadinessReport:
    root = workspace.resolve()
    criteria = _load_yaml(root / "configs/audit/icra_p0_p5.yaml")
    pilot_config = _load_yaml(root / str(criteria["p3_main_config"]))
    metrics_path = root / str(criteria["p3_main_metrics"])
    if not metrics_path.is_file():
        raise FileNotFoundError(metrics_path)
    metrics = pd.read_csv(metrics_path)
    checks = [
        _git_check(root),
        _manifest_check(root, criteria),
        _reproducible_environment_check(root),
        _capture_design_check(root, criteria),
        *_real_data_checks(root, criteria),
        _replay_vertical_slice_check(root, criteria),
        _noise_contract_check(root),
        _coverage_check(metrics, criteria["uncertainty"]),
        _stratified_coverage_check(metrics, criteria["uncertainty"]),
        *_p3_checks(metrics, pilot_config, criteria),
        *_p4_checks(root, criteria),
        *_p5_checks(root, criteria),
    ]
    verdict = "GO" if all(check.passed for check in checks) else "NO_GO"
    return PublicationReadinessReport(str(criteria["schema_version"]), verdict, tuple(checks))
