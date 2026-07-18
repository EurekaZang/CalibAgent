"""Serializable public data contracts frozen by ADR-001."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


class TrialPhase(str, Enum):
    PRECHECK = "precheck"
    RAMP_IN = "ramp_in"
    EXCITE = "excite"
    MEASURE = "measure"
    RAMP_OUT = "ramp_out"
    VALIDATE = "validate"
    UPDATE = "update"
    DECIDE = "decide"
    DONE = "done"
    ABORT = "abort"


@dataclass(frozen=True)
class VelocityCommand:
    vx: float
    vy: float
    wz: float
    duration_s: float
    frame: str = "base"

    def as_array(self) -> FloatArray:
        return np.asarray([self.vx, self.vy, self.wz], dtype=np.float64)

    @classmethod
    def from_array(
        cls, value: NDArray[np.floating[Any]], duration_s: float = 2.0, frame: str = "base"
    ) -> VelocityCommand:
        array = np.asarray(value, dtype=np.float64)
        if array.shape != (3,):
            raise ValueError(f"velocity command must have shape (3,), got {array.shape}")
        return cls(float(array[0]), float(array[1]), float(array[2]), duration_s, frame)


@dataclass(frozen=True)
class RobotContext:
    terrain_id: str
    payload_kg: float
    battery_ratio: float
    gait_id: str
    session_id: str


@dataclass
class TrialObservation:
    command: VelocityCommand
    mean_velocity: FloatArray
    covariance: FloatArray
    timestamps: tuple[float, float]
    context: RobotContext
    quality: dict[str, float | bool | str]
    safety_events: list[str] = field(default_factory=list)
    raw_ref: str | None = None

    def __post_init__(self) -> None:
        self.mean_velocity = np.asarray(self.mean_velocity, dtype=np.float64)
        self.covariance = np.asarray(self.covariance, dtype=np.float64)
        if self.mean_velocity.shape != (3,):
            raise ValueError("mean_velocity must have shape (3,)")
        if self.covariance.shape != (3, 3):
            raise ValueError("covariance must have shape (3, 3)")
        if self.timestamps[1] < self.timestamps[0]:
            raise ValueError("timestamps must be ordered")

    @property
    def valid(self) -> bool:
        return bool(self.quality.get("valid", False))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mean_velocity"] = self.mean_velocity.tolist()
        value["covariance"] = self.covariance.tolist()
        value["timestamps"] = list(self.timestamps)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrialObservation:
        command = VelocityCommand(**value["command"])
        context = RobotContext(**value["context"])
        return cls(
            command=command,
            mean_velocity=np.asarray(value["mean_velocity"], dtype=np.float64),
            covariance=np.asarray(value["covariance"], dtype=np.float64),
            timestamps=(float(value["timestamps"][0]), float(value["timestamps"][1])),
            context=context,
            quality=dict(value["quality"]),
            safety_events=list(value.get("safety_events", [])),
            raw_ref=value.get("raw_ref"),
        )


@dataclass(frozen=True)
class PredictiveDistribution:
    mean: FloatArray
    covariance: FloatArray
    model_id: str
    posterior_version: int

    def __post_init__(self) -> None:
        mean = np.asarray(self.mean, dtype=np.float64)
        covariance = np.asarray(self.covariance, dtype=np.float64)
        if mean.shape != (3,) or covariance.shape != (3, 3):
            raise ValueError("predictive distribution must be 3-dimensional")
        object.__setattr__(self, "mean", mean)
        object.__setattr__(self, "covariance", covariance)


@dataclass(frozen=True)
class PriorState:
    mean: FloatArray | None = None
    covariance: FloatArray | None = None


@dataclass(frozen=True)
class RobotState:
    timestamp: float
    position_xy: tuple[float, float]
    yaw: float
    roll: float
    pitch: float
    base_height: float
    velocity: tuple[float, float, float]
    battery_ratio: float = 1.0
    localization_valid: bool = True


@dataclass(frozen=True)
class TrialPolicy:
    ramp_in_s: float = 0.6
    settle_s: float = 0.8
    measure_s: float = 2.0
    ramp_out_s: float = 0.6
    sample_rate_hz: float = 50.0


@dataclass
class RawTrialData:
    timestamps: FloatArray
    command: FloatArray
    pose_se2: FloatArray
    context: RobotContext
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_ref: str | None = None


@dataclass(frozen=True)
class Candidate:
    command: VelocityCommand
    score: float
    information_gain: float
    cost: float
    rank: int = 0
    metadata: dict[str, float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyDecision:
    accepted: bool
    reason_codes: tuple[str, ...]
    command: VelocityCommand | None = None


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    git_commit: str
    config_hash: str
    random_seeds: dict[str, int]
    backend: str
    model_id: str
    planner_id: str
    artifacts: dict[str, str]
    isaaclab_commit: str = "UNSET-P5-NOT-INTEGRATED"
    stop_reason: str | None = None
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save_json(self, path: Path) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
