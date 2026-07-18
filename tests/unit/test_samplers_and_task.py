from __future__ import annotations

import numpy as np

from calibagent.core.planning.samplers import latin_hypercube, random_uniform, regular_grid, sobol
from calibagent.core.planning.task import TaskDistribution


def test_all_passive_samplers_respect_bounds() -> None:
    bounds = np.asarray([[-1, 1], [-0.5, 0.5], [-1.5, 1.5]], dtype=float)
    samples = [
        random_uniform(20, bounds, 1),
        latin_hypercube(20, bounds, 1),
        sobol(20, bounds, 1),
        regular_grid(3, bounds),
    ]
    for sample in samples:
        assert np.all(sample >= bounds[:, 0])
        assert np.all(sample <= bounds[:, 1])


def test_lhs_is_deterministic_for_seed() -> None:
    bounds = np.asarray([[-1, 1], [-1, 1], [-1, 1]], dtype=float)
    np.testing.assert_allclose(latin_hypercube(10, bounds, 3), latin_hypercube(10, bounds, 3))


def test_task_weights_normalize() -> None:
    commands = np.zeros((3, 3))
    task = TaskDistribution(commands, np.asarray([1, 2, 3]))
    assert np.isclose(task.weights.sum(), 1.0)
    np.testing.assert_allclose(task.weights, [1 / 6, 2 / 6, 3 / 6])
