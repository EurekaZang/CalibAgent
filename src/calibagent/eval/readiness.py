"""Independent evidence gates for P0-P3 publication-readiness claims."""

from __future__ import annotations

import json
import subprocess
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from calibagent.backends.replay import OfflineReplayBackend
from calibagent.data.observations import load_observations
from calibagent.eval.capture_plan import CapturePlanConfig, generate_capture_plan
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


def _manifest_check(workspace: Path) -> AuditCheck:
    paths = [
        workspace / "outputs/p1_baseline/manifest.json",
        workspace / "outputs/p3_main/manifest.json",
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
        and commit_result.returncode == 0
    )
    authenticity = AuditCheck(
        "p1_real_data_evidence",
        authenticity_passed,
        (
            f"backend={backend!r}, synthetic={synthetic}, robot={robot_model!r}, "
            f"reference={reference_sensor!r}, hashes={hashes_valid}, plan={plan_valid}, "
            f"commit={commit[:12]}"
        ),
    )

    if not dataset_path.is_file():
        return [
            authenticity,
            AuditCheck("p1_real_data_scale_coverage", False, "dataset artifact missing"),
            AuditCheck("p1_real_baseline_improvement", False, "dataset artifact missing"),
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
        improvement = AuditCheck(
            "p1_real_baseline_improvement",
            (
                raw_reduction >= float(real_criteria["min_m1_vs_raw_rmse_reduction"])
                and m0_reduction >= float(real_criteria["min_m1_vs_m0_rmse_reduction"])
            ),
            (
                f"M1_vs_raw={raw_reduction:.6f}, M1_vs_M0={m0_reduction:.6f}, "
                f"required={real_criteria['min_m1_vs_raw_rmse_reduction']:.2f}/"
                f"{real_criteria['min_m1_vs_m0_rmse_reduction']:.2f}"
            ),
        )
    return [authenticity, scale, improvement]


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


def _replay_vertical_slice_check(workspace: Path) -> AuditCheck:
    dataset = workspace / "outputs/p1_baseline/synthetic_dense.parquet"
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


def audit_publication_readiness(workspace: Path) -> PublicationReadinessReport:
    root = workspace.resolve()
    criteria = _load_yaml(root / "configs/audit/icra_p0_p3.yaml")
    pilot_config = _load_yaml(root / str(criteria["p3_main_config"]))
    metrics_path = root / str(criteria["p3_main_metrics"])
    if not metrics_path.is_file():
        raise FileNotFoundError(metrics_path)
    metrics = pd.read_csv(metrics_path)
    checks = [
        _git_check(root),
        _manifest_check(root),
        _reproducible_environment_check(root),
        _capture_design_check(root, criteria),
        *_real_data_checks(root, criteria),
        _replay_vertical_slice_check(root),
        _noise_contract_check(root),
        _coverage_check(metrics, criteria["uncertainty"]),
        _stratified_coverage_check(metrics, criteria["uncertainty"]),
        *_p3_checks(metrics, pilot_config, criteria),
    ]
    verdict = "GO" if all(check.passed for check in checks) else "NO_GO"
    return PublicationReadinessReport(str(criteria["schema_version"]), verdict, tuple(checks))
