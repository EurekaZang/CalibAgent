"""Session-isolated passive calibration baselines on canonical replay data."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from calibagent.core.models.least_squares import LeastSquaresVelocityModel
from calibagent.core.planning.samplers import latin_hypercube, regular_grid, sobol
from calibagent.data.manifest import build_manifest
from calibagent.eval.metrics import task_weighted_rmse
from calibagent.interfaces.types import TrialObservation


def session_grouped_split(
    observations: Sequence[TrialObservation], validation_fraction: float, seed: int
) -> tuple[list[TrialObservation], list[TrialObservation], tuple[str, ...]]:
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between zero and one")
    sessions = sorted({observation.context.session_id for observation in observations})
    if len(sessions) < 2:
        raise ValueError("session-grouped evaluation requires at least two session IDs")
    rng = np.random.default_rng(seed)
    shuffled = np.asarray(sessions, dtype=object)
    rng.shuffle(shuffled)
    validation_count = max(1, int(np.ceil(len(sessions) * validation_fraction)))
    validation_sessions = tuple(str(value) for value in shuffled[:validation_count])
    validation_set = set(validation_sessions)
    training = [
        observation
        for observation in observations
        if observation.valid and observation.context.session_id not in validation_set
    ]
    validation = [
        observation
        for observation in observations
        if observation.valid and observation.context.session_id in validation_set
    ]
    if len(training) < 4 or not validation:
        raise ValueError("split does not contain enough valid training/validation observations")
    return training, validation, validation_sessions


def _nearest_unique_indices(
    available_commands: NDArray[np.float64], targets: NDArray[np.float64], budget: int
) -> NDArray[np.int64]:
    selected: list[int] = []
    scale = np.maximum(np.ptp(available_commands, axis=0), 1e-12)
    for target in targets:
        remaining = np.asarray(
            [index for index in range(len(available_commands)) if index not in selected],
            dtype=np.int64,
        )
        if not len(remaining) or len(selected) == budget:
            break
        distance = np.linalg.norm((available_commands[remaining] - target) / scale, axis=1)
        selected.append(int(remaining[int(np.argmin(distance))]))
    if len(selected) < budget:
        raise RuntimeError("could not construct a unique passive replay sequence")
    return np.asarray(selected, dtype=np.int64)


def _selection_indices(
    method: str, commands: NDArray[np.float64], budget: int, seed: int
) -> NDArray[np.int64]:
    if budget > len(commands):
        raise ValueError("budget exceeds available training observations")
    bounds = np.column_stack([np.min(commands, axis=0), np.max(commands, axis=0)])
    if method == "random":
        return np.random.default_rng(seed).permutation(len(commands))[:budget].astype(np.int64)
    if method == "lhs":
        targets = latin_hypercube(budget, bounds, seed)
    elif method == "sobol":
        targets = sobol(budget, bounds, seed)
    elif method == "grid":
        levels = max(2, int(np.ceil(budget ** (1 / 3))))
        targets = regular_grid(levels, bounds)
        if len(targets) < budget:
            targets = np.vstack([targets, latin_hypercube(budget - len(targets), bounds, seed)])
    else:
        raise ValueError(f"unknown passive sampler {method}")
    return _nearest_unique_indices(commands, targets, budget)


def run_passive_replay_baseline(
    observations: Sequence[TrialObservation],
    output_dir: Path,
    budget: int = 30,
    validation_fraction: float = 0.2,
    seed: int = 1701,
) -> pd.DataFrame:
    training, validation, validation_sessions = session_grouped_split(
        observations, validation_fraction, seed
    )
    training_commands = np.vstack([observation.command.as_array() for observation in training])
    validation_commands = np.vstack([observation.command.as_array() for observation in validation])
    validation_targets = np.vstack([observation.mean_velocity for observation in validation])
    weights = np.ones(len(validation))
    rows: list[dict[str, Any]] = [
        {
            "sampler": "raw_command",
            "model": "B0_raw",
            "budget": 0,
            "validation_rmse": task_weighted_rmse(validation_commands, validation_targets, weights),
        }
    ]
    for sampler in ("grid", "random", "lhs", "sobol"):
        indices = _selection_indices(sampler, training_commands, budget, seed)
        selected = [training[int(index)] for index in indices]
        for model_id in ("M0_diagonal_affine", "M1_full_affine"):
            model = LeastSquaresVelocityModel(model_id).fit(selected)
            prediction = np.vstack([model.predict(command).mean for command in validation_commands])
            rows.append(
                {
                    "sampler": sampler,
                    "model": model_id,
                    "budget": budget,
                    "validation_rmse": task_weighted_rmse(prediction, validation_targets, weights),
                }
            )
    for model_id in ("M0_diagonal_affine", "M1_full_affine"):
        model = LeastSquaresVelocityModel(model_id).fit(training)
        prediction = np.vstack([model.predict(command).mean for command in validation_commands])
        rows.append(
            {
                "sampler": "dense",
                "model": model_id,
                "budget": len(training),
                "validation_rmse": task_weighted_rmse(prediction, validation_targets, weights),
            }
        )
    metrics = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output_dir / "baseline_metrics.csv", index=False)
    split = {
        "seed": seed,
        "validation_fraction": validation_fraction,
        "validation_sessions": validation_sessions,
        "training_rows": len(training),
        "validation_rows": len(validation),
    }
    (output_dir / "split.json").write_text(
        json.dumps(split, indent=2, sort_keys=True), encoding="utf-8"
    )
    config = {"budget": budget, **split}
    manifest = build_manifest(
        config,
        {"global": seed, "split": seed},
        "offline_replay",
        "M0_M1",
        "grid_random_lhs_sobol",
    )
    manifest = type(manifest)(
        **{
            **manifest.to_dict(),
            "artifacts": {"metrics": "baseline_metrics.csv", "split": "split.json"},
        }
    )
    manifest.save_json(output_dir / "manifest.json")
    return metrics
