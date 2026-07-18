"""Structural interfaces that keep algorithms independent of simulator and robot SDKs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from calibagent.interfaces.types import (
    Candidate,
    PredictiveDistribution,
    PriorState,
    RawTrialData,
    RobotContext,
    RobotState,
    SafetyDecision,
    TrialObservation,
    TrialPolicy,
    VelocityCommand,
)


class CalibrationModel(Protocol):
    def initialize(self, prior: PriorState) -> None: ...
    def update(self, obs: TrialObservation) -> None: ...
    def predict(
        self, command: NDArray[np.floating[Any]], context: RobotContext
    ) -> PredictiveDistribution: ...
    def hypothetical_update(
        self, command: NDArray[np.floating[Any]], measurement_cov: NDArray[np.floating[Any]]
    ) -> CalibrationModel: ...
    def save_state(self, path: Path) -> None: ...


class RobotBackend(Protocol):
    def reset(self, context: RobotContext) -> None: ...
    def get_state(self) -> RobotState: ...
    def execute_trial(self, command: VelocityCommand, policy: TrialPolicy) -> RawTrialData: ...
    def emergency_stop(self, reason: str) -> None: ...


class CandidatePlanner(Protocol):
    def propose(
        self, posterior: Any, task_distribution: Any, history: Any, k: int = 1
    ) -> list[Candidate]: ...


class SafetyFilter(Protocol):
    def evaluate(self, candidate: Candidate, state: RobotState, history: Any) -> SafetyDecision: ...
