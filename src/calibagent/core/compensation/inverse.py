"""Discrete constrained inverse mapping used by the navigation layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.planning.candidates import CandidatePool
from calibagent.core.safety import HardSafetyFilter
from calibagent.interfaces.types import Candidate, RobotState, VelocityCommand


@dataclass(frozen=True)
class CompensationResult:
    command: NDArray[np.float64]
    predicted_velocity: NDArray[np.float64]
    prediction_variance: NDArray[np.float64]
    objective: float
    candidate_index: int


class ConstrainedInverseCompensator:
    """Select a safe command whose posterior prediction matches task velocity.

    The inverse is deliberately solved over a frozen candidate set.  This is
    robust to hinges, saturation and non-invertible cross-axis mappings, and it
    keeps the output inside the same hard envelope used during calibration.
    """

    def __init__(
        self,
        candidate_pool: CandidatePool,
        safety_filter: HardSafetyFilter,
        *,
        regularization: float = 0.02,
        risk_weight: float = 0.05,
        duration_s: float = 0.10,
        enforce_axis_signs: bool = False,
        sign_threshold: float = 0.02,
    ) -> None:
        if (
            regularization < 0.0
            or risk_weight < 0.0
            or duration_s <= 0.0
            or sign_threshold < 0.0
        ):
            raise ValueError("compensation costs/duration are invalid")
        self.candidate_pool = candidate_pool
        self.safety_filter = safety_filter
        self.regularization = float(regularization)
        self.risk_weight = float(risk_weight)
        self.duration_s = float(duration_s)
        self.enforce_axis_signs = bool(enforce_axis_signs)
        self.sign_threshold = float(sign_threshold)

    def solve(
        self,
        desired_velocity: NDArray[np.floating[Any]],
        model: BayesianBasisModel,
        state: RobotState,
        previous_command: NDArray[np.floating[Any]],
    ) -> CompensationResult:
        desired = np.asarray(desired_velocity, dtype=np.float64)
        previous = np.asarray(previous_command, dtype=np.float64)
        if desired.shape != (3,) or previous.shape != (3,):
            raise ValueError("desired and previous commands must have shape (3,)")
        if not np.all(np.isfinite(desired)) or not np.all(np.isfinite(previous)):
            raise ValueError("compensation inputs must be finite")
        commands = self.candidate_pool.commands
        means, variances = model.predict_batch(commands)
        objective = (
            np.sum((means - desired[None, :]) ** 2, axis=1)
            + self.regularization * np.sum((commands - desired[None, :]) ** 2, axis=1)
            + self.risk_weight * np.sum(variances, axis=1)
        )
        order = np.argsort(objective, kind="stable")
        if self.enforce_axis_signs:
            active_axes = np.abs(desired) >= self.sign_threshold
            if np.any(active_axes):
                consistent = np.all(
                    commands[:, active_axes] * desired[active_axes] >= 0.0,
                    axis=1,
                )
                order = order[consistent[order]]
        previous_velocity = VelocityCommand.from_array(
            previous,
            duration_s=self.duration_s,
        )
        for index in order:
            command = VelocityCommand.from_array(
                commands[index],
                duration_s=self.duration_s,
            )
            decision = self.safety_filter.evaluate(
                Candidate(
                    command=command,
                    score=-float(objective[index]),
                    information_gain=0.0,
                    cost=float(objective[index]),
                ),
                state,
                [previous_velocity],
            )
            if decision.accepted:
                return CompensationResult(
                    command=commands[index].copy(),
                    predicted_velocity=means[index].copy(),
                    prediction_variance=variances[index].copy(),
                    objective=float(objective[index]),
                    candidate_index=int(index),
                )
        raise RuntimeError("no safe inverse-compensation candidate remains")
