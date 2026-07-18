from __future__ import annotations

import numpy as np
from tests.conftest import observation

from calibagent.core.models.least_squares import LeastSquaresVelocityModel


def test_m1_captures_cross_axis_coupling_better_than_m0(context) -> None:
    rng = np.random.default_rng(4)
    commands = rng.uniform([-1, -0.5, -1.5], [1, 0.5, 1.5], size=(80, 3))
    matrix = np.asarray([[0.9, 0.25, 0.0], [-0.2, 0.8, 0.08], [0.1, 0.0, 0.75]])
    targets = commands @ matrix.T + np.asarray([0.02, -0.01, 0.03])
    observations = [observation(u, y, context) for u, y in zip(commands, targets, strict=True)]
    m0 = LeastSquaresVelocityModel("M0_diagonal_affine").fit(observations)
    m1 = LeastSquaresVelocityModel("M1_full_affine").fit(observations)
    evaluation = rng.uniform([-1, -0.5, -1.5], [1, 0.5, 1.5], size=(30, 3))
    truth = evaluation @ matrix.T + np.asarray([0.02, -0.01, 0.03])
    error_m0 = np.mean(
        [np.linalg.norm(m0.predict(u).mean - y) for u, y in zip(evaluation, truth, strict=True)]
    )
    error_m1 = np.mean(
        [np.linalg.norm(m1.predict(u).mean - y) for u, y in zip(evaluation, truth, strict=True)]
    )
    assert error_m1 < 1e-6
    assert error_m1 < error_m0 * 0.01
