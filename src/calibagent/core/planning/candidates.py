"""Structured-axis plus low-discrepancy candidate pool generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.core.planning.samplers import sobol


@dataclass(frozen=True)
class CommandSpace:
    bounds: NDArray[np.float64]
    max_linear_norm: float = 1.0

    def __post_init__(self) -> None:
        bounds = np.asarray(self.bounds, dtype=np.float64)
        if bounds.shape != (3, 2) or np.any(bounds[:, 0] >= bounds[:, 1]):
            raise ValueError("bounds must have shape (3, 2) with low < high")
        if self.max_linear_norm <= 0:
            raise ValueError("max_linear_norm must be positive")
        object.__setattr__(self, "bounds", bounds)

    def valid_mask(self, commands: NDArray[np.floating[Any]]) -> NDArray[np.bool_]:
        u = np.asarray(commands, dtype=np.float64)
        within = np.all((u >= self.bounds[:, 0]) & (u <= self.bounds[:, 1]), axis=1)
        return np.asarray(
            within & (np.linalg.norm(u[:, :2], axis=1) <= self.max_linear_norm + 1e-12),
            dtype=np.bool_,
        )

    def normalized(self, commands: NDArray[np.floating[Any]]) -> NDArray[np.float64]:
        u = np.asarray(commands, dtype=np.float64)
        scale = np.maximum(np.abs(self.bounds).max(axis=1), 1e-12)
        return np.asarray(u / scale, dtype=np.float64)


@dataclass(frozen=True)
class CandidatePool:
    commands: NDArray[np.float64]
    command_space: CommandSpace

    def __post_init__(self) -> None:
        commands = np.asarray(self.commands, dtype=np.float64)
        if (
            commands.ndim != 2
            or commands.shape[1] != 3
            or not np.all(self.command_space.valid_mask(commands))
        ):
            raise ValueError("candidate commands must be safe and have shape (n, 3)")
        object.__setattr__(self, "commands", commands)

    @classmethod
    def generate(
        cls,
        command_space: CommandSpace,
        count: int = 2048,
        seed: int = 0,
        axis_levels: int = 5,
        min_distance: float = 1e-6,
    ) -> CandidatePool:
        if count < 12:
            raise ValueError("candidate count must be at least 12")
        values = []
        for axis in range(3):
            axis_values = np.linspace(
                command_space.bounds[axis, 0], command_space.bounds[axis, 1], axis_levels
            )
            for value in axis_values:
                command = np.zeros(3)
                command[axis] = value
                values.append(command)
        low_discrepancy = sobol(count * 2, command_space.bounds, seed)
        combined = np.vstack([np.asarray(values), low_discrepancy])
        combined = combined[command_space.valid_mask(combined)]
        # Stable rounded uniqueness prevents effectively duplicate fantasies.
        decimals = max(0, int(np.ceil(-np.log10(min_distance))))
        _, indices = np.unique(np.round(combined, decimals=decimals), axis=0, return_index=True)
        unique = combined[np.sort(indices)]
        if len(unique) < count:
            raise RuntimeError("not enough valid unique commands; increase oversampling")
        return cls(unique[:count], command_space)
