"""Discrete constrained inverse mapping used by the navigation layer."""

from __future__ import annotations

from collections.abc import Sequence
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


def bounded_velocity_feedback_target(
    desired_velocity: NDArray[np.floating[Any]],
    measured_velocity: NDArray[np.floating[Any]],
    *,
    gain: float,
    maximum_correction: NDArray[np.floating[Any]] | Sequence[float],
    activation_threshold: float = 0.02,
) -> NDArray[np.float64]:
    """Return a task-sign-preserving target with bounded velocity feedback."""

    desired = np.asarray(desired_velocity, dtype=np.float64)
    measured = np.asarray(measured_velocity, dtype=np.float64)
    limits = np.asarray(maximum_correction, dtype=np.float64)
    if (
        desired.shape != (3,)
        or measured.shape != (3,)
        or limits.shape != (3,)
        or not np.all(np.isfinite(desired))
        or not np.all(np.isfinite(measured))
        or not np.all(np.isfinite(limits))
        or gain < 0.0
        or np.any(limits < 0.0)
        or activation_threshold < 0.0
    ):
        raise ValueError("velocity feedback inputs are invalid")
    active_axes = np.abs(desired) >= activation_threshold
    correction = np.clip(float(gain) * (desired - measured), -limits, limits)
    correction[~active_axes] = 0.0
    target = desired + correction
    reversed_axes = active_axes & (target * desired < 0.0)
    target[reversed_axes] = 0.0
    return np.asarray(target, dtype=np.float64)


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
        undertracking_confidence_weights: (NDArray[np.floating[Any]] | Sequence[float]) = (
            0.0,
            0.0,
            0.0,
        ),
        inactive_axis_command_limits: (NDArray[np.floating[Any]] | Sequence[float]) = (
            np.inf,
            np.inf,
            np.inf,
        ),
        duration_s: float = 0.10,
        enforce_axis_signs: bool = False,
        sign_threshold: float = 0.02,
    ) -> None:
        confidence_weights = np.asarray(
            undertracking_confidence_weights,
            dtype=np.float64,
        )
        inactive_limits = np.asarray(
            inactive_axis_command_limits,
            dtype=np.float64,
        )
        if (
            regularization < 0.0
            or risk_weight < 0.0
            or confidence_weights.shape != (3,)
            or not np.all(np.isfinite(confidence_weights))
            or np.any(confidence_weights < 0.0)
            or inactive_limits.shape != (3,)
            or np.any(np.isnan(inactive_limits))
            or np.any(inactive_limits <= 0.0)
            or duration_s <= 0.0
            or sign_threshold < 0.0
        ):
            raise ValueError("compensation costs/duration are invalid")
        self.candidate_pool = candidate_pool
        self.safety_filter = safety_filter
        self.regularization = float(regularization)
        self.risk_weight = float(risk_weight)
        self.undertracking_confidence_weights = confidence_weights.copy()
        self.inactive_axis_command_limits = inactive_limits.copy()
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
        tracking_means = means.copy()
        active_axes = np.abs(desired) >= self.sign_threshold
        robust_axes = active_axes & (self.undertracking_confidence_weights > 0.0)
        if np.any(robust_axes):
            tracking_means[:, robust_axes] -= (
                np.sign(desired[robust_axes])[None, :]
                * self.undertracking_confidence_weights[robust_axes][None, :]
                * np.sqrt(variances[:, robust_axes])
            )
        objective = (
            np.sum((tracking_means - desired[None, :]) ** 2, axis=1)
            + self.regularization * np.sum((commands - desired[None, :]) ** 2, axis=1)
            + self.risk_weight * np.sum(variances, axis=1)
        )
        order = np.argsort(objective, kind="stable")
        inactive_axes = ~active_axes
        if np.any(inactive_axes):
            dormant_consistent = np.all(
                np.abs(commands[:, inactive_axes])
                <= self.inactive_axis_command_limits[inactive_axes],
                axis=1,
            )
            order = order[dormant_consistent[order]]
        if self.enforce_axis_signs and np.any(active_axes):
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
