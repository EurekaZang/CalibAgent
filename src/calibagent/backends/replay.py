"""Leakage-aware offline sequential replay backend."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from calibagent.interfaces.types import (
    RawTrialData,
    RobotContext,
    RobotState,
    TrialObservation,
    TrialPolicy,
    VelocityCommand,
)


class OfflineReplayBackend:
    """Returns recorded trials by index or nearest unused command.

    Observations are consumed at most once unless ``allow_reuse`` is explicit.
    The backend never exposes held-out targets to the planner.
    """

    def __init__(self, observations: Sequence[TrialObservation], allow_reuse: bool = False) -> None:
        if not observations:
            raise ValueError("replay backend requires observations")
        self._observations = list(observations)
        self._allow_reuse = allow_reuse
        self._consumed: set[int] = set()
        self._context = observations[0].context
        self._stopped_reason: str | None = None

    def reset(self, context: RobotContext) -> None:
        self._context = context
        self._consumed.clear()
        self._stopped_reason = None

    def get_state(self) -> RobotState:
        return RobotState(0.0, (0.0, 0.0), 0.0, 0.0, 0.0, 0.3, (0.0, 0.0, 0.0))

    def observation_at(self, index: int) -> TrialObservation:
        if index < 0 or index >= len(self._observations):
            raise IndexError(index)
        if index in self._consumed and not self._allow_reuse:
            raise RuntimeError(f"replay trial {index} already consumed")
        self._consumed.add(index)
        return self._observations[index]

    def nearest_observation(self, command: VelocityCommand) -> tuple[int, TrialObservation]:
        candidates = [
            index
            for index in range(len(self._observations))
            if self._allow_reuse or index not in self._consumed
        ]
        if not candidates:
            raise RuntimeError("replay dataset exhausted")
        target = command.as_array()
        index = min(
            candidates,
            key=lambda item: float(
                np.linalg.norm(self._observations[item].command.as_array() - target)
            ),
        )
        return index, self.observation_at(index)

    def execute_trial(self, command: VelocityCommand, policy: TrialPolicy) -> RawTrialData:
        _, observation = self.nearest_observation(command)
        start, end = observation.timestamps
        duration = end - start
        if duration <= 0:
            duration = policy.measure_s
            end = start + duration
        sample_count = max(2, int(np.ceil(duration * policy.sample_rate_hz)) + 1)
        timestamps = np.linspace(start, end, sample_count)
        elapsed = timestamps - timestamps[0]
        vx, vy, wz = observation.mean_velocity
        yaw = wz * elapsed
        if abs(wz) < 1e-10:
            x = vx * elapsed
            y = vy * elapsed
        else:
            x = (vx * np.sin(yaw) + vy * (np.cos(yaw) - 1.0)) / wz
            y = (vx * (1.0 - np.cos(yaw)) + vy * np.sin(yaw)) / wz
        pose = np.column_stack([x, y, yaw])
        commands = np.repeat(observation.command.as_array()[None, :], sample_count, axis=0)
        return RawTrialData(
            timestamps,
            commands,
            pose,
            observation.context,
            metadata={"reconstructed_from_aggregate": True},
            raw_ref=observation.raw_ref,
        )

    def emergency_stop(self, reason: str) -> None:
        self._stopped_reason = reason
