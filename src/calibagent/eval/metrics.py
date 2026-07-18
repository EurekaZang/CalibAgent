"""Paper-facing forward-model accuracy and uncertainty metrics."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.planning.task import TaskDistribution


def task_weighted_rmse(
    prediction: NDArray[np.floating[Any]],
    target: NDArray[np.floating[Any]],
    weights: NDArray[np.floating[Any]],
) -> float:
    residual = np.asarray(prediction) - np.asarray(target)
    normalized_weights = np.asarray(weights, dtype=np.float64) / np.sum(weights)
    return float(np.sqrt(np.sum(normalized_weights[:, None] * residual**2) / residual.shape[1]))


def integrated_uncertainty(
    model: BayesianBasisModel, task: TaskDistribution, include_noise: bool = False
) -> float:
    _, variance = model.predict_batch(task.commands, include_noise=include_noise)
    return float(np.sum(task.weights[:, None] * variance))


def gaussian_nll(
    mean: NDArray[np.floating[Any]],
    variance: NDArray[np.floating[Any]],
    target: NDArray[np.floating[Any]],
    weights: NDArray[np.floating[Any]],
) -> float:
    variance_array = np.maximum(np.asarray(variance, dtype=np.float64), 1e-12)
    residual = np.asarray(target, dtype=np.float64) - np.asarray(mean, dtype=np.float64)
    per_point = 0.5 * np.sum(
        np.log(2 * np.pi * variance_array) + residual**2 / variance_array, axis=1
    )
    normalized_weights = np.asarray(weights, dtype=np.float64) / np.sum(weights)
    return float(normalized_weights @ per_point)


def interval_coverage(
    mean: NDArray[np.floating[Any]],
    variance: NDArray[np.floating[Any]],
    target: NDArray[np.floating[Any]],
    z_value: float = 1.959963984540054,
) -> tuple[float, float]:
    width = z_value * np.sqrt(np.maximum(variance, 0.0))
    inside = np.abs(np.asarray(target) - np.asarray(mean)) <= width
    return float(np.mean(inside)), float(np.mean(2.0 * width))
