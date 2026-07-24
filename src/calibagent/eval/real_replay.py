"""Traceable raw-trial ingestion and P1 real replay evidence builder."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from calibagent.data.manifest import current_git_commit
from calibagent.data.observations import save_observations
from calibagent.eval.real_delivery import verify_real_delivery
from calibagent.eval.replay import run_passive_replay_baseline
from calibagent.interfaces.types import RawTrialData, RobotContext, TrialObservation
from calibagent.measurement.pipeline import MeasurementConfig, MeasurementPipeline

RAW_REQUIRED_COLUMNS = {
    "trial_id",
    "session_id",
    "timestamp",
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "pose_x",
    "pose_y",
    "pose_yaw",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _context(group: pd.DataFrame) -> RobotContext:
    row = group.iloc[0]
    return RobotContext(
        str(row.get("terrain_id", "flat")),
        float(row.get("payload_kg", 0.0)),
        float(row.get("battery_ratio", 1.0)),
        str(row.get("gait_id", "trot")),
        str(row["session_id"]),
    )


def process_raw_trials(frame: pd.DataFrame) -> list[TrialObservation]:
    missing = RAW_REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"raw trial CSV is missing required columns: {sorted(missing)}")
    observations = []
    pipeline = MeasurementPipeline()
    for (session_id, trial_id), group in frame.groupby(["session_id", "trial_id"], sort=True):
        ordered = group.sort_values("timestamp")
        raw = RawTrialData(
            ordered["timestamp"].to_numpy(dtype=np.float64),
            ordered[["cmd_vx", "cmd_vy", "cmd_wz"]].to_numpy(dtype=np.float64),
            ordered[["pose_x", "pose_y", "pose_yaw"]].to_numpy(dtype=np.float64),
            _context(ordered),
            metadata={"session_id": str(session_id), "trial_id": str(trial_id)},
            raw_ref=f"raw_trials.csv#{session_id}/{trial_id}",
        )
        observations.append(pipeline.process(raw))
    return observations


def capture_plan_alignment(raw: pd.DataFrame, plan: pd.DataFrame) -> tuple[float, float]:
    required = {"session_id", "trial_id", "cmd_vx", "cmd_vy", "cmd_wz"}
    if not required <= set(plan.columns):
        raise ValueError("capture plan is missing command identity columns")
    raw_commands = (
        raw.groupby(["session_id", "trial_id"], as_index=False)[["cmd_vx", "cmd_vy", "cmd_wz"]]
        .mean()
        .copy()
    )
    planned = plan[list(required)].copy()
    for frame in (raw_commands, planned):
        frame["session_id"] = frame["session_id"].astype(str)
        frame["trial_id"] = frame["trial_id"].astype(str)
    joined = raw_commands.merge(
        planned,
        on=["session_id", "trial_id"],
        how="left",
        suffixes=("_raw", "_plan"),
        indicator=True,
    )
    matched_identity = joined["_merge"] == "both"
    command_match = np.ones(len(joined), dtype=bool)
    for axis in ("vx", "vy", "wz"):
        command_match &= np.isclose(
            joined[f"cmd_{axis}_raw"], joined[f"cmd_{axis}_plan"], atol=1e-3
        )
    matched = matched_identity.to_numpy() & command_match
    match_ratio = float(np.mean(matched)) if len(matched) else 0.0
    completion = float(len(raw_commands) / len(planned)) if len(planned) else 0.0
    return match_ratio, min(completion, 1.0)


def evaluate_sampling_sensitivity(
    frame: pd.DataFrame,
    full_observations: list[TrialObservation],
    *,
    budget: int,
    seed: int,
) -> dict[str, Any]:
    """Check that conclusions survive two independent half-rate decimations."""

    groups = list(frame.groupby(["session_id", "trial_id"], sort=True))
    if len(groups) != len(full_observations):
        raise ValueError("raw groups and full-rate observations are inconsistent")
    full_velocity = np.vstack(
        [observation.mean_velocity for observation in full_observations]
    )
    decimations: list[dict[str, Any]] = []
    for offset in (0, 1):
        pipeline = MeasurementPipeline(
            MeasurementConfig(min_samples=15, max_timestamp_gap_s=0.15)
        )
        observations: list[TrialObservation] = []
        rates: list[float] = []
        for (_, _), group in groups:
            ordered = group.sort_values("timestamp").iloc[offset::2]
            timestamps = ordered["timestamp"].to_numpy(dtype=np.float64)
            delta = np.diff(timestamps)
            rates.append(float(1.0 / np.median(delta)))
            raw = RawTrialData(
                timestamps,
                ordered[["cmd_vx", "cmd_vy", "cmd_wz"]].to_numpy(dtype=np.float64),
                ordered[["pose_x", "pose_y", "pose_yaw"]].to_numpy(dtype=np.float64),
                _context(ordered),
                metadata={"decimation_offset": offset},
                raw_ref=f"raw_trials.csv#decimation/{offset}",
            )
            observations.append(pipeline.process(raw))
        decimated_velocity = np.vstack(
            [observation.mean_velocity for observation in observations]
        )
        difference = decimated_velocity - full_velocity
        with tempfile.TemporaryDirectory(prefix="calibagent_sampling_sensitivity_") as temp:
            metrics = run_passive_replay_baseline(
                observations,
                Path(temp),
                budget=budget,
                seed=seed,
            )
        raw_rmse = float(
            metrics.loc[metrics["model"] == "B0_raw", "validation_rmse"].iloc[0]
        )
        lhs_m0 = float(
            metrics.loc[
                (metrics["sampler"] == "lhs")
                & (metrics["model"] == "M0_diagonal_affine"),
                "validation_rmse",
            ].iloc[0]
        )
        lhs_m1 = float(
            metrics.loc[
                (metrics["sampler"] == "lhs")
                & (metrics["model"] == "M1_full_affine"),
                "validation_rmse",
            ].iloc[0]
        )
        decimations.append(
            {
                "offset": offset,
                "median_hz": float(np.median(rates)),
                "valid_observations": sum(
                    int(observation.valid) for observation in observations
                ),
                "velocity_rmse_to_full": float(np.sqrt(np.mean(difference * difference))),
                "velocity_axis_rmse_to_full": np.sqrt(
                    np.mean(difference * difference, axis=0)
                ).tolist(),
                "raw_validation_rmse": raw_rmse,
                "lhs_m0_validation_rmse": lhs_m0,
                "lhs_m1_validation_rmse": lhs_m1,
                "m1_vs_raw_reduction": 1.0 - lhs_m1 / raw_rmse,
                "m1_vs_m0_reduction": 1.0 - lhs_m1 / lhs_m0,
            }
        )
    return {
        "schema_version": "1.0",
        "method": "even_odd_half_rate_decimation",
        "full_observations": len(full_observations),
        "decimations": decimations,
    }


def build_real_replay_evidence(
    source: Path,
    output_dir: Path,
    *,
    source_kind: str,
    robot_model: str,
    reference_sensor: str,
    capture_plan: Path | None = None,
    delivery_root: Path | None = None,
    source_archive: Path | None = None,
    budget: int = 30,
    validation_fraction: float = 0.2,
    seed: int = 1701,
) -> dict[str, Any]:
    if source_kind not in {"real_robot", "synthetic_fixture"}:
        raise ValueError("source_kind must be real_robot or synthetic_fixture")
    if source_kind == "real_robot" and capture_plan is None:
        raise ValueError("real_robot evidence requires the frozen capture plan")
    if source_kind == "real_robot" and delivery_root is None:
        raise ValueError("real_robot evidence requires the traceable delivery root")
    if source_kind == "real_robot" and source_archive is None:
        raise ValueError("real_robot evidence requires the immutable source archive")
    source = source.resolve()
    delivery_verification: dict[str, Any] | None = None
    if delivery_root is not None:
        if capture_plan is None:
            raise ValueError("delivery verification requires a capture plan")
        delivery_verification = verify_real_delivery(delivery_root, source, capture_plan)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundled_source = output_dir / "raw_trials.csv"
    if source != bundled_source.resolve():
        shutil.copy2(source, bundled_source)
    frame = pd.read_csv(bundled_source)
    plan_match: float | None = None
    plan_completion: float | None = None
    bundled_plan: Path | None = None
    bundled_archive: Path | None = None
    if capture_plan is not None:
        capture_plan = capture_plan.resolve()
        bundled_plan = output_dir / "capture_plan.csv"
        if capture_plan != bundled_plan.resolve():
            shutil.copy2(capture_plan, bundled_plan)
        plan_match, plan_completion = capture_plan_alignment(frame, pd.read_csv(bundled_plan))
    if source_archive is not None:
        source_archive = source_archive.resolve()
        bundled_archive = output_dir / "source_archive.zip"
        if source_archive != bundled_archive.resolve():
            shutil.copy2(source_archive, bundled_archive)
    observations = process_raw_trials(frame)
    valid = [observation for observation in observations if observation.valid]
    dataset = output_dir / "observations.parquet"
    save_observations(observations, dataset)
    metrics = run_passive_replay_baseline(
        valid,
        output_dir,
        budget=budget,
        validation_fraction=validation_fraction,
        seed=seed,
    )
    sensitivity = evaluate_sampling_sensitivity(
        frame,
        observations,
        budget=budget,
        seed=seed,
    )
    sensitivity_path = output_dir / "sampling_sensitivity.json"
    sensitivity_path.write_text(
        json.dumps(sensitivity, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    sessions = sorted({observation.context.session_id for observation in valid})
    manifest_path = output_dir / "manifest.json"
    run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verification_path: Path | None = None
    if delivery_verification is not None:
        verification_path = output_dir / "delivery_verification.json"
        verification_path.write_text(
            json.dumps(delivery_verification, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    evidence: dict[str, Any] = {
        **run_manifest,
        "backend": "offline_replay",
        "synthetic": source_kind != "real_robot",
        "source_kind": source_kind,
        "robot_model": robot_model,
        "reference_sensor": reference_sensor,
        "git_commit": current_git_commit(),
        "sessions": sessions,
        "total_observations": len(observations),
        "valid_observations": len(valid),
        "source_sha256": file_sha256(bundled_source),
        "dataset_sha256": file_sha256(dataset),
        "capture_plan_sha256": (file_sha256(bundled_plan) if bundled_plan is not None else None),
        "capture_plan_command_match": plan_match,
        "capture_plan_completion": plan_completion,
        "delivery_verified": bool(
            delivery_verification is not None and delivery_verification["verified"]
        ),
        "native_traceability_ratio": (
            float(delivery_verification["native_traceability_ratio"])
            if delivery_verification is not None
            else None
        ),
        "source_archive_sha256": (
            file_sha256(bundled_archive) if bundled_archive is not None else None
        ),
        "delivery_verification_sha256": (
            file_sha256(verification_path) if verification_path is not None else None
        ),
        "sampling_sensitivity_sha256": file_sha256(sensitivity_path),
        "protocol_limitations": (
            delivery_verification["limitations"] if delivery_verification is not None else []
        ),
        "artifacts": {
            **run_manifest["artifacts"],
            "raw_source": bundled_source.name,
            "dataset": dataset.name,
            **({"capture_plan": bundled_plan.name} if bundled_plan is not None else {}),
            **({"source_archive": bundled_archive.name} if bundled_archive is not None else {}),
            **(
                {"delivery_verification": verification_path.name}
                if verification_path is not None
                else {}
            ),
            "sampling_sensitivity": sensitivity_path.name,
        },
        "baseline_summary": metrics.to_dict(orient="records"),
    }
    manifest_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence
