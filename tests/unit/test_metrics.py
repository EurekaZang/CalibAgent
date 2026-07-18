from __future__ import annotations

import numpy as np

from calibagent.eval.metrics import gaussian_nll, interval_coverage, task_weighted_rmse


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
