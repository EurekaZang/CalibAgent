"""Deterministic passive grid/random/LHS/Sobol baselines."""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import qmc


def _scale(unit: NDArray[np.float64], bounds: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(qmc.scale(unit, bounds[:, 0], bounds[:, 1]), dtype=np.float64)


def random_uniform(n: int, bounds: NDArray[np.floating[Any]], seed: int) -> NDArray[np.float64]:
    limits = np.asarray(bounds, dtype=np.float64)
    return np.random.default_rng(seed).uniform(limits[:, 0], limits[:, 1], size=(n, 3))


def latin_hypercube(n: int, bounds: NDArray[np.floating[Any]], seed: int) -> NDArray[np.float64]:
    return _scale(
        qmc.LatinHypercube(d=3, seed=seed).random(n), np.asarray(bounds, dtype=np.float64)
    )


def sobol(n: int, bounds: NDArray[np.floating[Any]], seed: int) -> NDArray[np.float64]:
    if n < 1:
        raise ValueError("n must be positive")
    power = int(np.ceil(np.log2(n)))
    unit = qmc.Sobol(d=3, scramble=True, seed=seed).random_base2(power)[:n]
    return _scale(unit, np.asarray(bounds, dtype=np.float64))


def regular_grid(levels: int, bounds: NDArray[np.floating[Any]]) -> NDArray[np.float64]:
    limits = np.asarray(bounds, dtype=np.float64)
    axes = [np.linspace(low, high, levels) for low, high in limits]
    return np.asarray(list(itertools.product(*axes)), dtype=np.float64)
