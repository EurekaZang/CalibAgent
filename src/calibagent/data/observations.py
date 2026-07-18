"""Lossless flattened Parquet representation of TrialObservation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from calibagent.interfaces.types import RobotContext, TrialObservation, VelocityCommand

SCHEMA_VERSION = "1.0"


def observations_to_frame(observations: Sequence[TrialObservation]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for observation in observations:
        row: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "cmd_vx": observation.command.vx,
            "cmd_vy": observation.command.vy,
            "cmd_wz": observation.command.wz,
            "duration_s": observation.command.duration_s,
            "frame": observation.command.frame,
            "mean_vx": observation.mean_velocity[0],
            "mean_vy": observation.mean_velocity[1],
            "mean_wz": observation.mean_velocity[2],
            "timestamp_start": observation.timestamps[0],
            "timestamp_end": observation.timestamps[1],
            "terrain_id": observation.context.terrain_id,
            "payload_kg": observation.context.payload_kg,
            "battery_ratio": observation.context.battery_ratio,
            "gait_id": observation.context.gait_id,
            "session_id": observation.context.session_id,
            "quality_json": json.dumps(observation.quality, sort_keys=True),
            "safety_events_json": json.dumps(observation.safety_events),
            "raw_ref": observation.raw_ref,
        }
        for row_index in range(3):
            for column_index in range(3):
                row[f"cov_{row_index}{column_index}"] = observation.covariance[
                    row_index, column_index
                ]
        rows.append(row)
    return pd.DataFrame(rows)


def frame_to_observations(frame: pd.DataFrame) -> list[TrialObservation]:
    if not set(frame.get("schema_version", [])) <= {SCHEMA_VERSION}:
        raise ValueError("unsupported observation schema version")
    observations: list[TrialObservation] = []
    for row in frame.to_dict(orient="records"):
        covariance = np.asarray(
            [[row[f"cov_{i}{j}"] for j in range(3)] for i in range(3)], dtype=np.float64
        )
        observations.append(
            TrialObservation(
                VelocityCommand(
                    float(row["cmd_vx"]),
                    float(row["cmd_vy"]),
                    float(row["cmd_wz"]),
                    float(row["duration_s"]),
                    str(row["frame"]),
                ),
                np.asarray([row["mean_vx"], row["mean_vy"], row["mean_wz"]], dtype=np.float64),
                covariance,
                (float(row["timestamp_start"]), float(row["timestamp_end"])),
                RobotContext(
                    str(row["terrain_id"]),
                    float(row["payload_kg"]),
                    float(row["battery_ratio"]),
                    str(row["gait_id"]),
                    str(row["session_id"]),
                ),
                json.loads(str(row["quality_json"])),
                json.loads(str(row["safety_events_json"])),
                None if pd.isna(row["raw_ref"]) else str(row["raw_ref"]),
            )
        )
    return observations


def save_observations(observations: Sequence[TrialObservation], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    observations_to_frame(observations).to_parquet(path, index=False)


def load_observations(path: Path) -> list[TrialObservation]:
    return frame_to_observations(pd.read_parquet(path))
