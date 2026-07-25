from __future__ import annotations

import numpy as np
import pytest

from calibagent.eval.metrics import (
    clopper_pearson_interval,
    gaussian_nll,
    interval_coverage,
    task_weighted_rmse,
)


def test_exact_binomial_interval_handles_boundary_rates() -> None:
    zero_lower, zero_upper = clopper_pearson_interval(0, 72)
    full_lower, full_upper = clopper_pearson_interval(72, 72)

    assert zero_lower == 0.0
    assert zero_upper < 0.05
    assert full_lower > 0.95
    assert full_upper == 1.0

    with pytest.raises(ValueError, match="non-empty"):
        clopper_pearson_interval(0, 0)


def test_weighted_rmse_uses_task_weights() -> None:
    prediction = np.asarray([[1.0, 0, 0], [0, 0, 0]])
    target = np.zeros((2, 3))
    assert task_weighted_rmse(prediction, target, np.asarray([0.0, 1.0])) == 0.0


def test_interval_coverage_and_nll_are_finite() -> None:
    mean = np.zeros((5, 3))
    variance = np.ones((5, 3)) * 0.04
    target = np.zeros((5, 3))
    coverage, width = interval_coverage(mean, variance, target)
    assert coverage == 1.0
    assert width > 0
    assert np.isfinite(gaussian_nll(mean, variance, target, np.ones(5)))
