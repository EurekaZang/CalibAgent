"""Frozen task command grid and normalized deployment weights."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class TaskDistribution:
    commands: NDArray[np.float64]
    weights: NDArray[np.float64]

    def __post_init__(self) -> None:
        commands = np.asarray(self.commands, dtype=np.float64)
        weights = np.asarray(self.weights, dtype=np.float64)
        if commands.ndim != 2 or commands.shape[1] != 3:
            raise ValueError("task commands must have shape (n, 3)")
        if weights.shape != (len(commands),) or np.any(weights < 0) or not np.any(weights > 0):
            raise ValueError("task weights must be nonnegative and match commands")
        object.__setattr__(self, "commands", commands)
        object.__setattr__(self, "weights", weights / np.sum(weights))

    @classmethod
    def uniform(cls, commands: NDArray[np.floating[Any]]) -> TaskDistribution:
        array = np.asarray(commands, dtype=np.float64)
        return cls(array, np.ones(len(array)))

    @classmethod
    def gaussian_mixture(
        cls,
        commands: NDArray[np.floating[Any]],
        centers: NDArray[np.floating[Any]],
        scales: NDArray[np.floating[Any]],
        mixture_weights: NDArray[np.floating[Any]] | None = None,
    ) -> TaskDistribution:
        u = np.asarray(commands, dtype=np.float64)
        centers_array = np.atleast_2d(np.asarray(centers, dtype=np.float64))
        scales_array = np.atleast_2d(np.asarray(scales, dtype=np.float64))
        if centers_array.shape != scales_array.shape or centers_array.shape[1] != 3:
            raise ValueError("centers and scales must have shape (mixtures, 3)")
        mixture = (
            np.ones(len(centers_array)) / len(centers_array)
            if mixture_weights is None
            else np.asarray(mixture_weights, dtype=np.float64)
        )
        mixture = mixture / np.sum(mixture)
        weights = np.zeros(len(u))
        for center, scale, mass in zip(centers_array, scales_array, mixture, strict=True):
            if np.any(scale <= 0):
                raise ValueError("scales must be positive")
            weights += mass * np.exp(-0.5 * np.sum(((u - center) / scale) ** 2, axis=1))
        return cls(u, weights + 1e-12)
