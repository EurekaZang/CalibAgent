"""Traceable raw-trial ingestion and P1 real replay evidence builder."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from calibagent.data.manifest import current_git_commit
from calibagent.data.observations import save_observations
from calibagent.eval.replay import run_passive_replay_baseline
from calibagent.interfaces.types import RawTrialData, RobotContext, TrialObservation
from calibagent.measurement.pipeline import MeasurementPipeline

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


def build_real_replay_evidence(
    source: Path,
    output_dir: Path,
    *,
    source_kind: str,
    robot_model: str,
    reference_sensor: str,
    capture_plan: Path | None = None,
    budget: int = 30,
    validation_fraction: float = 0.2,
    seed: int = 1701,
) -> dict[str, Any]:
    if source_kind not in {"real_robot", "synthetic_fixture"}:
        raise ValueError("source_kind must be real_robot or synthetic_fixture")
    if source_kind == "real_robot" and capture_plan is None:
        raise ValueError("real_robot evidence requires the frozen capture plan")
    source = source.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundled_source = output_dir / "raw_trials.csv"
    if source != bundled_source.resolve():
        shutil.copy2(source, bundled_source)
    frame = pd.read_csv(bundled_source)
    plan_match: float | None = None
    plan_completion: float | None = None
    bundled_plan: Path | None = None
    if capture_plan is not None:
        capture_plan = capture_plan.resolve()
        bundled_plan = output_dir / "capture_plan.csv"
        if capture_plan != bundled_plan.resolve():
            shutil.copy2(capture_plan, bundled_plan)
        plan_match, plan_completion = capture_plan_alignment(frame, pd.read_csv(bundled_plan))
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
    sessions = sorted({observation.context.session_id for observation in valid})
    manifest_path = output_dir / "manifest.json"
    run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        "artifacts": {
            **run_manifest["artifacts"],
            "raw_source": bundled_source.name,
            "dataset": dataset.name,
            **({"capture_plan": bundled_plan.name} if bundled_plan is not None else {}),
        },
        "baseline_summary": metrics.to_dict(orient="records"),
    }
    manifest_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence
