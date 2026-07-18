"""Convert a documented flat CSV into the canonical TrialObservation Parquet schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from calibagent.data.observations import save_observations
from calibagent.interfaces.types import RobotContext, TrialObservation, VelocityCommand

REQUIRED_COLUMNS = {
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "mean_vx",
    "mean_vy",
    "mean_wz",
    "var_vx",
    "var_vy",
    "var_wz",
}


def convert_csv(source: Path, destination: Path, session_id: str) -> None:
    frame = pd.read_csv(source)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"input CSV is missing required columns: {sorted(missing)}")
    context = RobotContext("unknown", 0.0, 1.0, "unknown", session_id)
    observations = []
    for row_number, (_, row) in enumerate(frame.iterrows()):
        valid = bool(row.get("valid", True))
        observations.append(
            TrialObservation(
                VelocityCommand(
                    float(row.cmd_vx),
                    float(row.cmd_vy),
                    float(row.cmd_wz),
                    float(row.get("duration_s", 2.0)),
                ),
                np.asarray([row.mean_vx, row.mean_vy, row.mean_wz], dtype=np.float64),
                np.diag([row.var_vx, row.var_vy, row.var_wz]),
                (
                    float(row.get("timestamp_start", row_number * 4.0)),
                    float(row.get("timestamp_end", row_number * 4.0 + 2.0)),
                ),
                context,
                {"valid": valid, "source": "csv_converter"},
                raw_ref=str(row.get("raw_ref", "")) or None,
            )
        )
    save_observations(observations, destination)
    destination.with_suffix(".manifest.json").write_text(
        json.dumps(
            {"source": str(source), "rows": len(observations), "schema_version": "1.0"}, indent=2
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--session-id", required=True)
    arguments = parser.parse_args()
    convert_csv(arguments.source, arguments.destination, arguments.session_id)


if __name__ == "__main__":
    main()
