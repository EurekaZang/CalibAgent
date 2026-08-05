"""Sequential predictive-residual domain-shift detector."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class DomainShiftConfig:
    """Frozen one-sided CUSUM settings for normalized innovation energy.

    Under a calibrated three-dimensional Gaussian predictive distribution,
    ``normalized_nis`` has expectation one.  The allowance suppresses ordinary
    variation while the rolling-evidence and dwell gates prevent one or two
    bad localization samples from triggering adaptation.  A bounded rolling
    window tolerates an intervening nominal sample caused by a safety abort
    without retaining evidence indefinitely.
    """

    reference_nis: float = 1.0
    allowance: float = 0.50
    alarm_threshold: float = 4.0
    minimum_positive_evidence: int = 3
    evidence_window_trials: int = 5
    minimum_dwell_trials: int = 3
    covariance_jitter: float = 1e-9

    def __post_init__(self) -> None:
        if self.reference_nis <= 0.0:
            raise ValueError("reference_nis must be positive")
        if self.allowance < 0.0 or self.alarm_threshold <= 0.0:
            raise ValueError("CUSUM allowance/threshold are invalid")
        if self.minimum_positive_evidence < 1 or self.minimum_dwell_trials < 1:
            raise ValueError("CUSUM trial gates must be positive")
        if self.evidence_window_trials < self.minimum_positive_evidence:
            raise ValueError("evidence window must contain the required evidence")
        if self.covariance_jitter <= 0.0:
            raise ValueError("covariance_jitter must be positive")


@dataclass(frozen=True)
class ShiftDetection:
    trial: int
    normalized_nis: float
    statistic: float
    positive_evidence: int
    alarm: bool
    latched: bool


class DomainShiftDetector:
    """Fail-closed residual CUSUM with hysteretic alarm latching."""

    def __init__(self, config: DomainShiftConfig | None = None) -> None:
        self.config = config or DomainShiftConfig()
        self._statistic = 0.0
        self._positive_window: deque[bool] = deque(maxlen=self.config.evidence_window_trials)
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
        self._positive_window.clear()
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
        self._positive_window.append(increment > 0.0)
        positive_evidence = sum(self._positive_window)
        alarm = bool(
            not self._latched
            and trial >= self.config.minimum_dwell_trials
            and positive_evidence >= self.config.minimum_positive_evidence
            and self._statistic >= self.config.alarm_threshold
        )
        if alarm:
            self._latched = True
        self._last_trial = trial
        return ShiftDetection(
            trial=trial,
            normalized_nis=normalized_nis,
            statistic=self._statistic,
            positive_evidence=positive_evidence,
            alarm=alarm,
            latched=self._latched,
        )


@dataclass(frozen=True)
class PairedSignatureConfig:
    """Frozen detector settings for repeated command-response signatures.

    A commissioning pass records one residual vector for every validation
    command.  Operational observations are compared only with the matching
    command, so stationary context-dependent residual bias cannot accumulate
    without bound.  Component scales make the distance dimensionless.
    """

    component_scales: tuple[float, ...] = (0.14, 0.08, 0.18)
    distance_threshold: float = 0.70
    minimum_positive_evidence: int = 2
    evidence_window_trials: int = 4
    minimum_dwell_trials: int = 2

    def __post_init__(self) -> None:
        scales = np.asarray(self.component_scales, dtype=np.float64)
        if scales.ndim != 1 or len(scales) < 1 or not np.all(np.isfinite(scales)):
            raise ValueError("paired-signature component scales must be finite")
        if np.any(scales <= 0.0):
            raise ValueError("paired-signature component scales must be positive")
        if not np.isfinite(self.distance_threshold) or self.distance_threshold <= 0.0:
            raise ValueError("paired-signature distance threshold must be positive")
        if self.minimum_positive_evidence < 2:
            raise ValueError("paired-signature detector must reject isolated changes")
        if self.evidence_window_trials < self.minimum_positive_evidence:
            raise ValueError("paired-signature evidence window is too short")
        if self.minimum_dwell_trials < self.minimum_positive_evidence:
            raise ValueError("paired-signature dwell must contain the required evidence")


@dataclass(frozen=True)
class PairedSignatureDetection:
    trial: int
    signature_id: int
    distance: float
    positive_evidence: int
    alarm: bool
    latched: bool


class PairedSignatureDetector:
    """Latched change detector against frozen, command-matched signatures."""

    def __init__(self, config: PairedSignatureConfig | None = None) -> None:
        self.config = config or PairedSignatureConfig()
        self._references: dict[int, NDArray[np.float64]] = {}
        self._positive_window: deque[bool] = deque(maxlen=self.config.evidence_window_trials)
        self._latched = False
        self._last_trial = 0

    @property
    def latched(self) -> bool:
        return self._latched

    @property
    def reference_count(self) -> int:
        return len(self._references)

    def prime(
        self,
        signature_id: int,
        residual: NDArray[np.floating[Any]],
    ) -> None:
        signature = int(signature_id)
        vector = self._validated_residual(residual)
        if signature in self._references:
            raise ValueError(f"paired signature {signature} was primed more than once")
        self._references[signature] = vector.copy()

    def update(
        self,
        signature_id: int,
        residual: NDArray[np.floating[Any]],
        *,
        trial: int,
    ) -> PairedSignatureDetection:
        signature = int(signature_id)
        vector = self._validated_residual(residual)
        if signature not in self._references:
            raise ValueError(f"paired signature {signature} has no commissioning reference")
        if trial <= self._last_trial:
            raise ValueError("paired-signature trials must increase strictly")
        scales = np.asarray(self.config.component_scales, dtype=np.float64)
        distance = float(np.linalg.norm((vector - self._references[signature]) / scales))
        self._positive_window.append(distance > self.config.distance_threshold)
        positive_evidence = sum(self._positive_window)
        alarm = bool(
            not self._latched
            and trial >= self.config.minimum_dwell_trials
            and positive_evidence >= self.config.minimum_positive_evidence
        )
        if alarm:
            self._latched = True
        self._last_trial = trial
        return PairedSignatureDetection(
            trial=trial,
            signature_id=signature,
            distance=distance,
            positive_evidence=positive_evidence,
            alarm=alarm,
            latched=self._latched,
        )

    def _validated_residual(
        self,
        residual: NDArray[np.floating[Any]],
    ) -> NDArray[np.float64]:
        vector = np.asarray(residual, dtype=np.float64)
        if vector.shape != (len(self.config.component_scales),):
            raise ValueError("paired-signature residual shape does not match component scales")
        if not np.all(np.isfinite(vector)):
            raise ValueError("paired-signature residual must be finite")
        return vector
