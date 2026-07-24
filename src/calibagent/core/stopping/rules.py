"""Conservative, stateful stopping rule with mandatory hard budgets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class StopReason(str, Enum):
    CONTINUE = "continue"
    TARGET_REACHED = "target_reached"
    LOW_GAIN_VALIDATED = "low_gain_validated"
    TRIAL_BUDGET = "trial_budget"
    TIME_BUDGET = "time_budget"
    DISTANCE_BUDGET = "distance_budget"
    BATTERY_BUDGET = "battery_budget"


@dataclass(frozen=True)
class StopCriteria:
    min_trials: int
    max_trials: int
    max_time_s: float
    max_distance_m: float
    min_battery_ratio: float
    uncertainty_threshold: float
    validation_rmse_threshold: float
    min_marginal_gain: float
    target_confirmations: int = 3
    low_gain_patience: int = 5

    def __post_init__(self) -> None:
        if self.min_trials < 1 or self.max_trials < self.min_trials:
            raise ValueError("trial limits are invalid")
        positive = (
            self.max_time_s,
            self.max_distance_m,
            self.uncertainty_threshold,
            self.validation_rmse_threshold,
            self.target_confirmations,
            self.low_gain_patience,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("stop limits and patience must be positive")
        if self.min_marginal_gain < 0:
            raise ValueError("min_marginal_gain must be nonnegative")
        if not 0 <= self.min_battery_ratio <= 1:
            raise ValueError("min_battery_ratio must be within [0, 1]")


@dataclass(frozen=True)
class StopMetrics:
    trial_count: int
    elapsed_s: float
    distance_m: float
    battery_ratio: float
    integrated_uncertainty: float
    validation_rmse: float
    coverage_complete: bool


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: StopReason
    target_streak: int
    low_gain_streak: int


class StopRule:
    """Stop only after independent validation or an explicit hard budget."""

    def __init__(self, criteria: StopCriteria) -> None:
        self.criteria = criteria
        self._target_streak = 0
        self._low_gain_streak = 0
        self._previous_uncertainty: float | None = None

    def reset(self) -> None:
        self._target_streak = 0
        self._low_gain_streak = 0
        self._previous_uncertainty = None

    def _decision(self, stop: bool, reason: StopReason) -> StopDecision:
        return StopDecision(stop, reason, self._target_streak, self._low_gain_streak)

    def evaluate(self, metrics: StopMetrics) -> StopDecision:
        values = np.asarray(
            [
                metrics.elapsed_s,
                metrics.distance_m,
                metrics.battery_ratio,
                metrics.integrated_uncertainty,
                metrics.validation_rmse,
            ]
        )
        if metrics.trial_count < 0 or not np.all(np.isfinite(values)):
            raise ValueError("stop metrics must be finite and trial_count nonnegative")

        if metrics.battery_ratio <= self.criteria.min_battery_ratio:
            return self._decision(True, StopReason.BATTERY_BUDGET)
        if metrics.elapsed_s >= self.criteria.max_time_s:
            return self._decision(True, StopReason.TIME_BUDGET)
        if metrics.distance_m >= self.criteria.max_distance_m:
            return self._decision(True, StopReason.DISTANCE_BUDGET)
        if metrics.trial_count >= self.criteria.max_trials:
            return self._decision(True, StopReason.TRIAL_BUDGET)

        if self._previous_uncertainty is None:
            marginal_gain = np.inf
        else:
            marginal_gain = max(
                0.0,
                self._previous_uncertainty - metrics.integrated_uncertainty,
            )
        self._previous_uncertainty = metrics.integrated_uncertainty

        eligible = metrics.trial_count >= self.criteria.min_trials and metrics.coverage_complete
        validated = metrics.validation_rmse <= self.criteria.validation_rmse_threshold
        target = validated and (
            metrics.integrated_uncertainty <= self.criteria.uncertainty_threshold
        )
        self._target_streak = self._target_streak + 1 if eligible and target else 0
        low_gain = (
            eligible
            and validated
            and marginal_gain <= self.criteria.min_marginal_gain
        )
        self._low_gain_streak = self._low_gain_streak + 1 if low_gain else 0

        if self._target_streak >= self.criteria.target_confirmations:
            return self._decision(True, StopReason.TARGET_REACHED)
        if self._low_gain_streak >= self.criteria.low_gain_patience:
            return self._decision(True, StopReason.LOW_GAIN_VALIDATED)
        return self._decision(False, StopReason.CONTINUE)
