"""Frozen, balanced P1 Go2 command-plan generation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from numpy.typing import NDArray

from calibagent.core.planning.samplers import latin_hypercube
from calibagent.data.manifest import canonical_config_hash, current_git_commit
from calibagent.eval.real_replay import file_sha256


@dataclass(frozen=True)
class CapturePlanConfig:
    experiment_id: str
    session_ids: tuple[str, ...]
    trials_per_session: int
    session_seeds: tuple[int, ...]
    bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    max_linear_norm: float
    anchor_commands: tuple[tuple[float, float, float], ...]
    sentinel_commands: tuple[tuple[float, float, float], ...]
    sentinel_repeats: int
    ramp_in_s: float
    settle_s: float
    measure_s: float
    ramp_out_s: float
    sample_rate_hz: float

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CapturePlanConfig:
        bounds = tuple((float(row[0]), float(row[1])) for row in value["bounds"])
        anchors = tuple(
            (float(row[0]), float(row[1]), float(row[2])) for row in value["anchor_commands"]
        )
        sentinels = tuple(
            (float(row[0]), float(row[1]), float(row[2])) for row in value["sentinel_commands"]
        )
        if len(bounds) != 3:
            raise ValueError("capture bounds must contain three axis ranges")
        return cls(
            experiment_id=str(value["experiment_id"]),
            session_ids=tuple(str(item) for item in value["session_ids"]),
            trials_per_session=int(value["trials_per_session"]),
            session_seeds=tuple(int(item) for item in value["session_seeds"]),
            bounds=(bounds[0], bounds[1], bounds[2]),
            max_linear_norm=float(value["max_linear_norm"]),
            anchor_commands=anchors,
            sentinel_commands=sentinels,
            sentinel_repeats=int(value["sentinel_repeats"]),
            ramp_in_s=float(value["ramp_in_s"]),
            settle_s=float(value["settle_s"]),
            measure_s=float(value["measure_s"]),
            ramp_out_s=float(value["ramp_out_s"]),
            sample_rate_hz=float(value["sample_rate_hz"]),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> CapturePlanConfig:
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        if not isinstance(value, dict):
            raise ValueError("capture config must be a mapping")
        return cls.from_dict(value)


def _safe_lhs(config: CapturePlanConfig, count: int, seed: int) -> NDArray[np.float64]:
    bounds = np.asarray(config.bounds, dtype=np.float64)
    candidates = latin_hypercube(max(count * 4, 64), bounds, seed)
    candidates = candidates[np.linalg.norm(candidates[:, :2], axis=1) <= config.max_linear_norm]
    if len(candidates) < count:
        raise RuntimeError("not enough safe LHS commands for capture plan")
    return np.asarray(candidates[:count], dtype=np.float64)


def generate_capture_plan(config: CapturePlanConfig) -> pd.DataFrame:
    if len(config.session_ids) != len(config.session_seeds):
        raise ValueError("session IDs and seeds must have equal length")
    fixed_count = (
        len(config.anchor_commands) + len(config.sentinel_commands) * config.sentinel_repeats
    )
    lhs_count = config.trials_per_session - fixed_count
    if lhs_count < 1:
        raise ValueError("trials_per_session leaves no room for LHS commands")
    bounds = np.asarray(config.bounds, dtype=np.float64)
    fixed = np.asarray(config.anchor_commands, dtype=np.float64)
    sentinels = np.repeat(
        np.asarray(config.sentinel_commands, dtype=np.float64), config.sentinel_repeats, axis=0
    )
    rows: list[dict[str, Any]] = []
    for session_id, seed in zip(config.session_ids, config.session_seeds, strict=True):
        lhs = _safe_lhs(config, lhs_count, seed)
        commands = np.vstack([fixed, sentinels, lhs])
        sources = np.asarray(
            ["anchor"] * len(fixed) + ["sentinel"] * len(sentinels) + ["lhs"] * len(lhs),
            dtype=object,
        )
        order = np.random.default_rng(seed + 90_000).permutation(len(commands))
        commands, sources = commands[order], sources[order]
        if not np.all((commands >= bounds[:, 0]) & (commands <= bounds[:, 1])):
            raise ValueError("capture command exceeds configured bounds")
        if np.any(np.linalg.norm(commands[:, :2], axis=1) > config.max_linear_norm):
            raise ValueError("capture command exceeds linear norm")
        for trial_id, (command, source) in enumerate(zip(commands, sources, strict=True)):
            rows.append(
                {
                    "session_id": session_id,
                    "trial_id": trial_id,
                    "cmd_vx": command[0],
                    "cmd_vy": command[1],
                    "cmd_wz": command[2],
                    "design_source": source,
                    "ramp_in_s": config.ramp_in_s,
                    "settle_s": config.settle_s,
                    "measure_s": config.measure_s,
                    "ramp_out_s": config.ramp_out_s,
                    "sample_rate_hz": config.sample_rate_hz,
                }
            )
    return pd.DataFrame(rows)


def write_capture_plan(config: CapturePlanConfig, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    plan = generate_capture_plan(config)
    plan.to_csv(output, index=False)
    manifest = {
        "schema_version": "1.0",
        "experiment_id": config.experiment_id,
        "git_commit": current_git_commit(),
        "config_hash": canonical_config_hash(asdict(config)),
        "plan_sha256": file_sha256(output),
        "sessions": len(config.session_ids),
        "planned_trials": len(plan),
        "trials_per_session": config.trials_per_session,
        "axis_min": plan[["cmd_vx", "cmd_vy", "cmd_wz"]].min().tolist(),
        "axis_max": plan[["cmd_vx", "cmd_vy", "cmd_wz"]].max().tolist(),
    }
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest
