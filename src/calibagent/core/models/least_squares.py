"""P1 passive M0/M1 least-squares baselines."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.interfaces.types import PredictiveDistribution, RobotContext, TrialObservation


class LeastSquaresVelocityModel:
    """M0 diagonal-affine or M1 full-coupling affine regression."""

    def __init__(self, model_id: str = "M1_full_affine", ridge: float = 1e-8) -> None:
        if model_id not in {"M0_diagonal_affine", "M1_full_affine"}:
            raise ValueError(f"unsupported least-squares model {model_id}")
        self.model_id = model_id
        self.ridge = ridge
        self.coefficients_: list[NDArray[np.float64]] = []
        self.residual_covariance_ = np.eye(3, dtype=np.float64)
        self.posterior_version = 0

    def fit(self, observations: Iterable[TrialObservation]) -> LeastSquaresVelocityModel:
        valid = [obs for obs in observations if obs.valid]
        if len(valid) < 2:
            raise ValueError("at least two valid observations are required")
        commands = np.vstack([obs.command.as_array() for obs in valid])
        targets = np.vstack([obs.mean_velocity for obs in valid])
        self.coefficients_ = []
        predictions = np.empty_like(targets)
        for axis in range(3):
            if self.model_id == "M0_diagonal_affine":
                design = np.column_stack([np.ones(len(commands)), commands[:, axis]])
            else:
                design = np.column_stack([np.ones(len(commands)), commands])
            regularizer = self.ridge * np.eye(design.shape[1])
            regularizer[0, 0] = 0.0
            coefficient = np.linalg.solve(
                design.T @ design + regularizer, design.T @ targets[:, axis]
            )
            self.coefficients_.append(coefficient)
            predictions[:, axis] = design @ coefficient
        residuals = targets - predictions
        if len(valid) > 3:
            covariance = np.cov(residuals, rowvar=False, ddof=1)
        else:
            covariance = np.diag(np.maximum(np.var(residuals, axis=0), 1e-8))
        self.residual_covariance_ = np.atleast_2d(covariance) + np.eye(3) * 1e-9
        self.posterior_version = len(valid)
        return self

    def predict(
        self, command: NDArray[np.floating[Any]], context: RobotContext | None = None
    ) -> PredictiveDistribution:
        del context
        if len(self.coefficients_) != 3:
            raise RuntimeError("model must be fitted before predict")
        u = np.asarray(command, dtype=np.float64)
        if u.shape != (3,):
            raise ValueError("command must have shape (3,)")
        mean = np.empty(3)
        for axis, coefficient in enumerate(self.coefficients_):
            design = np.asarray([1.0, u[axis]]) if self.model_id.startswith("M0") else np.r_[1.0, u]
            mean[axis] = design @ coefficient
        return PredictiveDistribution(
            mean, self.residual_covariance_, self.model_id, self.posterior_version
        )
