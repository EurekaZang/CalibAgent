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


def build_real_replay_evidence(
    source: Path,
    output_dir: Path,
    *,
    source_kind: str,
    robot_model: str,
    reference_sensor: str,
    budget: int = 30,
    validation_fraction: float = 0.2,
    seed: int = 1701,
) -> dict[str, Any]:
    if source_kind not in {"real_robot", "synthetic_fixture"}:
        raise ValueError("source_kind must be real_robot or synthetic_fixture")
    source = source.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundled_source = output_dir / "raw_trials.csv"
    if source != bundled_source.resolve():
        shutil.copy2(source, bundled_source)
    frame = pd.read_csv(bundled_source)
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
        "artifacts": {
            **run_manifest["artifacts"],
            "raw_source": bundled_source.name,
            "dataset": dataset.name,
        },
        "baseline_summary": metrics.to_dict(orient="records"),
    }
    manifest_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence
