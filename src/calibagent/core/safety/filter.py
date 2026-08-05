"""Deterministic hard safety rules applied after planning and during execution."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.interfaces.types import (
    Candidate,
    RobotState,
    SafetyDecision,
    VelocityCommand,
)


@dataclass(frozen=True)
class SafetyEnvelope:
    """Configuration for the non-learned safety boundary.

    The planner may rank commands, but it cannot modify or bypass these limits.
    Bounds are expressed in the robot body frame and the workspace in the world
    frame.
    """

    command_bounds: tuple[tuple[float, float], ...] = (
        (-0.75, 0.75),
        (-0.45, 0.45),
        (-1.20, 1.20),
    )
    max_linear_norm: float = 0.80
    max_coupled_load: float = 1.45
    max_delta_linear: float = 0.45
    max_delta_angular: float = 0.80
    workspace_bounds: tuple[tuple[float, float], ...] = ((-5.0, 5.0), (-5.0, 5.0))
    boundary_margin: float = 0.35
    max_roll: float = 0.45
    max_pitch: float = 0.45
    min_base_height: float = 0.20
    max_base_height: float = 0.65
    max_abs_yaw_rate: float = 2.0
    min_battery_ratio: float = 0.15

    def __post_init__(self) -> None:
        if len(self.command_bounds) != 3 or len(self.workspace_bounds) != 2:
            raise ValueError("command/workspace bounds must have three/two axes")
        if any(low >= high for low, high in (*self.command_bounds, *self.workspace_bounds)):
            raise ValueError("safety bounds require low < high")
        positive = (
            self.max_linear_norm,
            self.max_coupled_load,
            self.max_delta_linear,
            self.max_delta_angular,
            self.boundary_margin,
            self.max_roll,
            self.max_pitch,
            self.min_base_height,
            self.max_base_height,
            self.max_abs_yaw_rate,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("safety magnitudes must be positive")
        if self.min_base_height >= self.max_base_height:
            raise ValueError("base-height limits are inverted")
        if not 0.0 <= self.min_battery_ratio <= 1.0:
            raise ValueError("min_battery_ratio must be within [0, 1]")


def _command_array(value: Any) -> NDArray[np.float64] | None:
    if isinstance(value, Candidate):
        return value.command.as_array()
    if isinstance(value, VelocityCommand):
        return value.as_array()
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    return array if array.shape == (3,) else None


class HardSafetyFilter:
    """Fail-closed hard filter with stable, machine-auditable reason codes."""

    def __init__(self, envelope: SafetyEnvelope | None = None) -> None:
        self.envelope = envelope or SafetyEnvelope()

    def _state_reasons(self, state: RobotState) -> list[str]:
        values = np.asarray(
            [
                state.timestamp,
                *state.position_xy,
                state.yaw,
                state.roll,
                state.pitch,
                state.base_height,
                *state.velocity,
                state.battery_ratio,
            ],
            dtype=np.float64,
        )
        if not np.all(np.isfinite(values)):
            return ["STATE_NONFINITE"]
        reasons: list[str] = []
        if abs(state.roll) > self.envelope.max_roll:
            reasons.append("ROLL_LIMIT")
        if abs(state.pitch) > self.envelope.max_pitch:
            reasons.append("PITCH_LIMIT")
        if not self.envelope.min_base_height <= state.base_height <= self.envelope.max_base_height:
            reasons.append("BASE_HEIGHT_LIMIT")
        if abs(state.velocity[2]) > self.envelope.max_abs_yaw_rate:
            reasons.append("YAW_RATE_LIMIT")
        if state.battery_ratio < self.envelope.min_battery_ratio:
            reasons.append("LOW_BATTERY")
        if not state.localization_valid:
            reasons.append("LOCALIZATION_INVALID")
        for axis, (position, bounds) in enumerate(
            zip(state.position_xy, self.envelope.workspace_bounds, strict=True)
        ):
            low, high = bounds
            if (
                not low + self.envelope.boundary_margin
                <= position
                <= high - self.envelope.boundary_margin
            ):
                reasons.append(f"WORKSPACE_STATE_AXIS_{axis}")
        return reasons

    def monitor(self, state: RobotState) -> SafetyDecision:
        """Evaluate execution-time state without a new candidate."""

        reasons = self._state_reasons(state)
        return SafetyDecision(not reasons, tuple(reasons), None)

    def evaluate(
        self,
        candidate: Candidate,
        state: RobotState,
        history: Sequence[Any],
    ) -> SafetyDecision:
        """Evaluate a proposed command after planning and before execution."""

        command = candidate.command
        values = command.as_array()
        reasons = self._state_reasons(state)
        if not np.all(np.isfinite(values)) or not np.isfinite(command.duration_s):
            reasons.append("COMMAND_NONFINITE")
            return SafetyDecision(False, tuple(dict.fromkeys(reasons)), None)
        if command.frame != "base":
            reasons.append("COMMAND_FRAME")
        if command.duration_s <= 0:
            reasons.append("COMMAND_DURATION")
        for axis, (value, bounds) in enumerate(
            zip(values, self.envelope.command_bounds, strict=True)
        ):
            if not bounds[0] <= value <= bounds[1]:
                reasons.append(f"COMMAND_AXIS_{axis}")
        linear_norm = float(np.linalg.norm(values[:2]))
        if linear_norm > self.envelope.max_linear_norm:
            reasons.append("LINEAR_NORM")
        angular_scale = max(abs(bound) for bound in self.envelope.command_bounds[2])
        coupled_load = linear_norm / self.envelope.max_linear_norm + abs(values[2]) / angular_scale
        if coupled_load > self.envelope.max_coupled_load:
            reasons.append("LINEAR_ANGULAR_COUPLING")

        last = next(
            (
                array
                for array in (_command_array(item) for item in reversed(history))
                if array is not None
            ),
            np.zeros(3, dtype=np.float64),
        )
        if float(np.linalg.norm(values[:2] - last[:2])) > self.envelope.max_delta_linear:
            reasons.append("LINEAR_SLEW")
        if abs(float(values[2] - last[2])) > self.envelope.max_delta_angular:
            reasons.append("ANGULAR_SLEW")

        cosine, sine = np.cos(state.yaw), np.sin(state.yaw)
        world_velocity = np.asarray(
            [
                cosine * values[0] - sine * values[1],
                sine * values[0] + cosine * values[1],
            ]
        )
        projected = np.asarray(state.position_xy) + world_velocity * command.duration_s
        for axis, (position, bounds) in enumerate(
            zip(projected, self.envelope.workspace_bounds, strict=True)
        ):
            low, high = bounds
            if (
                not low + self.envelope.boundary_margin
                <= position
                <= high - self.envelope.boundary_margin
            ):
                reasons.append(f"WORKSPACE_PROJECTED_AXIS_{axis}")

        unique = tuple(dict.fromkeys(reasons))
        return SafetyDecision(not unique, unique, command if not unique else None)

    def select_first_safe(
        self,
        candidates: Sequence[Candidate],
        state: RobotState,
        history: Sequence[Any],
    ) -> SafetyDecision:
        """Return the first accepted ranked candidate or a fail-closed decision."""

        collected: list[str] = []
        for candidate in candidates:
            decision = self.evaluate(candidate, state, history)
            if decision.accepted:
                return decision
            collected.extend(decision.reason_codes)
        return SafetyDecision(
            False,
            ("NO_SAFE_CANDIDATE", *tuple(dict.fromkeys(collected))),
            None,
        )


def filter_candidates_by_forward_cap(
    candidates: Sequence[Candidate],
    maximum_forward_velocity: float,
) -> list[Candidate]:
    """Apply an empirical forward cap while preserving candidate ranking.

    This filter is activated only after an execution-time base-height abort.
    Reverse and lateral candidates retain their scores and relative order.
    """

    cap = float(maximum_forward_velocity)
    if not np.isfinite(cap) or cap <= 0.0:
        raise ValueError("contextual forward cap must be positive and finite")
    return [candidate for candidate in candidates if candidate.command.vx <= cap]


def height_rate_guarded_command(
    command: NDArray[np.floating[Any]] | Sequence[float],
    *,
    base_height_m: float,
    previous_base_height_m: float,
    activation_height_m: float,
    minimum_drop_m: float,
    maximum_linear_norm: float,
    force_active: bool = False,
) -> tuple[NDArray[np.float64], bool]:
    """Derate a command when a low base is descending faster than a fixed margin."""

    output = np.asarray(command, dtype=np.float64).copy()
    scalars = np.asarray(
        [
            base_height_m,
            previous_base_height_m,
            activation_height_m,
            minimum_drop_m,
            maximum_linear_norm,
        ],
        dtype=np.float64,
    )
    if (
        output.shape != (3,)
        or not np.all(np.isfinite(output))
        or not np.all(np.isfinite(scalars))
        or activation_height_m <= 0.0
        or minimum_drop_m <= 0.0
        or maximum_linear_norm <= 0.0
    ):
        raise ValueError("height-rate guard inputs are invalid")
    active = bool(
        force_active
        or (
            base_height_m <= activation_height_m
            and previous_base_height_m - base_height_m >= minimum_drop_m
        )
    )
    linear_norm = float(np.linalg.norm(output[:2]))
    if active and linear_norm > maximum_linear_norm:
        output[:2] *= maximum_linear_norm / linear_norm
    return output, active


def predictive_height_interlock(
    *,
    base_height_m: float,
    previous_base_height_m: float,
    activation_height_m: float,
    release_height_m: float,
    minimum_projected_height_m: float,
    prediction_steps: int,
    previously_active: bool = False,
) -> tuple[bool, float]:
    """Latch a high-rate zero-command interlock before the hard height limit.

    The planner-rate guard cannot react to a base-height drop that crosses the
    hard envelope between planner ticks.  This helper extrapolates the latest
    per-sample drop over a short frozen horizon and uses hysteresis to prevent
    rapid command chatter while the robot is standing back up.
    """

    scalars = np.asarray(
        [
            base_height_m,
            previous_base_height_m,
            activation_height_m,
            release_height_m,
            minimum_projected_height_m,
        ],
        dtype=np.float64,
    )
    if (
        not np.all(np.isfinite(scalars))
        or minimum_projected_height_m <= 0.0
        or activation_height_m <= minimum_projected_height_m
        or release_height_m <= activation_height_m
        or prediction_steps < 1
    ):
        raise ValueError("predictive height interlock inputs are invalid")
    drop = max(previous_base_height_m - base_height_m, 0.0)
    projected_height = base_height_m - float(prediction_steps) * drop
    trigger = bool(
        base_height_m <= activation_height_m or projected_height <= minimum_projected_height_m
    )
    recovered = bool(base_height_m >= release_height_m and base_height_m >= previous_base_height_m)
    active = bool(trigger or (previously_active and not recovered))
    return active, projected_height
