from __future__ import annotations

import pytest

from calibagent.core.stopping import (
    StopCriteria,
    StopMetrics,
    StopReason,
    StopRule,
)


def _criteria(**changes: object) -> StopCriteria:
    values: dict[str, object] = {
        "min_trials": 5,
        "max_trials": 20,
        "max_time_s": 100.0,
        "max_distance_m": 50.0,
        "min_battery_ratio": 0.1,
        "uncertainty_threshold": 0.01,
        "validation_rmse_threshold": 0.04,
        "min_marginal_gain": 1e-5,
        "target_confirmations": 3,
        "low_gain_patience": 5,
    }
    values.update(changes)
    return StopCriteria(**values)  # type: ignore[arg-type]


def _metrics(trial: int, **changes: object) -> StopMetrics:
    values: dict[str, object] = {
        "trial_count": trial,
        "elapsed_s": float(trial),
        "distance_m": float(trial) * 0.1,
        "battery_ratio": 0.8,
        "integrated_uncertainty": 0.005,
        "validation_rmse": 0.02,
        "coverage_complete": True,
    }
    values.update(changes)
    return StopMetrics(**values)  # type: ignore[arg-type]


def test_target_requires_minimum_trials_and_repeated_validation() -> None:
    rule = StopRule(_criteria())
    assert not rule.evaluate(_metrics(3)).stop
    assert not rule.evaluate(_metrics(5)).stop
    assert not rule.evaluate(_metrics(6)).stop
    decision = rule.evaluate(_metrics(7))
    assert decision.stop
    assert decision.reason is StopReason.TARGET_REACHED
    assert decision.target_streak == 3


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"trial_count": 20}, StopReason.TRIAL_BUDGET),
        ({"elapsed_s": 100.0}, StopReason.TIME_BUDGET),
        ({"distance_m": 50.0}, StopReason.DISTANCE_BUDGET),
        ({"battery_ratio": 0.1}, StopReason.BATTERY_BUDGET),
    ],
)
def test_hard_budgets_always_stop(changes: dict[str, object], reason: StopReason) -> None:
    decision = StopRule(_criteria()).evaluate(_metrics(1, **changes))
    assert decision.stop
    assert decision.reason is reason


def test_low_gain_requires_independent_validation() -> None:
    rule = StopRule(
        _criteria(
            uncertainty_threshold=1e-9,
            min_marginal_gain=0.001,
            low_gain_patience=2,
        )
    )
    assert not rule.evaluate(_metrics(5, integrated_uncertainty=0.02)).stop
    bad = rule.evaluate(
        _metrics(6, integrated_uncertainty=0.02, validation_rmse=0.10)
    )
    assert not bad.stop
    assert bad.low_gain_streak == 0
    assert not rule.evaluate(_metrics(7, integrated_uncertainty=0.02)).stop
    good = rule.evaluate(_metrics(8, integrated_uncertainty=0.02))
    assert good.stop
    assert good.reason is StopReason.LOW_GAIN_VALIDATED


def test_invalid_metrics_and_criteria_are_rejected() -> None:
    with pytest.raises(ValueError, match="trial limits"):
        _criteria(min_trials=5, max_trials=4)
    with pytest.raises(ValueError, match="finite"):
        StopRule(_criteria()).evaluate(_metrics(1, validation_rmse=float("nan")))
