"""Sequential predictive-residual domain-shift detector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class DomainShiftConfig:
    """Frozen one-sided CUSUM settings for normalized innovation energy.

    Under a calibrated three-dimensional Gaussian predictive distribution,
    ``normalized_nis`` has expectation one.  The allowance suppresses ordinary
    variation while the consecutive and dwell gates prevent a single bad
    localization sample from triggering adaptation.
    """

    reference_nis: float = 1.0
    allowance: float = 0.50
    alarm_threshold: float = 4.0
    minimum_consecutive: int = 3
    minimum_dwell_trials: int = 3
    covariance_jitter: float = 1e-9

    def __post_init__(self) -> None:
        if self.reference_nis <= 0.0:
            raise ValueError("reference_nis must be positive")
        if self.allowance < 0.0 or self.alarm_threshold <= 0.0:
            raise ValueError("CUSUM allowance/threshold are invalid")
        if self.minimum_consecutive < 1 or self.minimum_dwell_trials < 1:
            raise ValueError("CUSUM trial gates must be positive")
        if self.covariance_jitter <= 0.0:
            raise ValueError("covariance_jitter must be positive")


@dataclass(frozen=True)
class ShiftDetection:
    trial: int
    normalized_nis: float
    statistic: float
    positive_streak: int
    alarm: bool
    latched: bool


class DomainShiftDetector:
    """Fail-closed residual CUSUM with hysteretic alarm latching."""

    def __init__(self, config: DomainShiftConfig | None = None) -> None:
        self.config = config or DomainShiftConfig()
        self._statistic = 0.0
        self._positive_streak = 0
        self._latched = False
        self._last_trial = 0

    @property
    def statistic(self) -> float:
        return self._statistic

    @property
    def latched(self) -> bool:
        return self._latched

    def reset(self) -> None:
        self._statistic = 0.0
        self._positive_streak = 0
        self._latched = False
        self._last_trial = 0

    def update(
        self,
        residual: NDArray[np.floating[Any]],
        covariance: NDArray[np.floating[Any]],
        *,
        trial: int,
    ) -> ShiftDetection:
        error = np.asarray(residual, dtype=np.float64)
        innovation = np.asarray(covariance, dtype=np.float64)
        if error.ndim != 1 or len(error) < 1:
            raise ValueError("residual must be a non-empty vector")
        if innovation.shape != (len(error), len(error)):
            raise ValueError("covariance shape must match residual")
        if not np.all(np.isfinite(error)) or not np.all(np.isfinite(innovation)):
            raise ValueError("shift detector inputs must be finite")
        if trial <= self._last_trial:
            raise ValueError("shift detector trials must increase strictly")
        symmetric = 0.5 * (innovation + innovation.T)
        eigenvalues = np.linalg.eigvalsh(symmetric)
        if float(np.min(eigenvalues)) < -self.config.covariance_jitter:
            raise ValueError("innovation covariance must be positive semidefinite")
        regularized = symmetric + np.eye(len(error)) * self.config.covariance_jitter
        normalized_nis = float(error @ np.linalg.solve(regularized, error) / len(error))
        boundary = self.config.reference_nis + self.config.allowance
        increment = normalized_nis - boundary
        self._statistic = max(0.0, self._statistic + increment)
        if increment > 0.0:
            self._positive_streak += 1
        else:
            self._positive_streak = 0
        alarm = bool(
            not self._latched
            and trial >= self.config.minimum_dwell_trials
            and self._positive_streak >= self.config.minimum_consecutive
            and self._statistic >= self.config.alarm_threshold
        )
        if alarm:
            self._latched = True
        self._last_trial = trial
        return ShiftDetection(
            trial=trial,
            normalized_nis=normalized_nis,
            statistic=self._statistic,
            positive_streak=self._positive_streak,
            alarm=alarm,
            latched=self._latched,
        )
