"""Known-ground-truth distortion families for P1-P3 verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.interfaces.types import RobotContext, TrialObservation, VelocityCommand


@dataclass(frozen=True)
class SyntheticDistortion:
    family: str
    matrix: NDArray[np.float64]
    bias: NDArray[np.float64]
    deadzone: NDArray[np.float64]
    saturation: NDArray[np.float64]
    base_noise_std: NDArray[np.float64]
    heteroscedastic_scale: float = 0.0

    @classmethod
    def from_seed(cls, family: str, seed: int) -> SyntheticDistortion:
        if family not in {"affine", "deadzone", "heteroscedastic"}:
            raise ValueError(f"unknown distortion family {family}")
        rng = np.random.default_rng(seed)
        diagonal = rng.uniform(0.72, 1.08, size=3)
        matrix = np.asarray(
            np.diag(diagonal)
            + rng.uniform(-0.12, 0.12, size=(3, 3)) * (1.0 - np.eye(3, dtype=np.float64)),
            dtype=np.float64,
        )
        bias = rng.uniform([-0.04, -0.025, -0.06], [0.04, 0.025, 0.06])
        deadzone = np.zeros(3) if family == "affine" else np.asarray([0.12, 0.08, 0.20])
        saturation = (
            np.asarray([0.82, 0.42, 1.20], dtype=np.float64)
            if family == "deadzone"
            else np.asarray([2.0, 1.0, 3.0], dtype=np.float64)
        )
        base_noise = np.asarray([0.025, 0.018, 0.035])
        hetero = 0.7 if family == "heteroscedastic" else 0.0
        return cls(family, matrix, bias, deadzone, saturation, base_noise, hetero)

    def noiseless(self, commands: NDArray[np.floating[Any]]) -> NDArray[np.float64]:
        u = np.asarray(commands, dtype=np.float64)
        one_dimensional = u.ndim == 1
        if one_dimensional:
            u = u[None, :]
        after_deadzone = np.sign(u) * np.maximum(np.abs(u) - self.deadzone, 0.0)
        coupled = after_deadzone @ self.matrix.T + self.bias
        output = np.asarray(np.clip(coupled, -self.saturation, self.saturation), dtype=np.float64)
        return np.asarray(output[0] if one_dimensional else output, dtype=np.float64)

    def noise_std(self, commands: NDArray[np.floating[Any]]) -> NDArray[np.float64]:
        u = np.asarray(commands, dtype=np.float64)
        return self.base_noise_std * (1.0 + self.heteroscedastic_scale * np.abs(u))

    def sample(
        self, commands: NDArray[np.floating[Any]], rng: np.random.Generator
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        u = np.asarray(commands, dtype=np.float64)
        mean = self.noiseless(u)
        std = self.noise_std(u)
        return mean + rng.normal(size=np.shape(mean)) * std, std**2


DEFAULT_CONTEXT = RobotContext("synthetic", 0.0, 1.0, "nominal", "synthetic-session")


def make_observation(
    distortion: SyntheticDistortion,
    command: NDArray[np.floating[Any]],
    rng: np.random.Generator,
    trial_id: int,
) -> TrialObservation:
    u = np.asarray(command, dtype=np.float64)
    target, variance = distortion.sample(u, rng)
    # The model's configured base variance represents irreducible process
    # noise. Observation covariance carries only command-dependent excess
    # variance, so the likelihood charges each source exactly once.
    excess_variance = np.maximum(variance - distortion.base_noise_std**2, 0.0)
    return TrialObservation(
        VelocityCommand.from_array(u),
        target,
        np.diag(np.asarray(excess_variance, dtype=np.float64)),
        (float(trial_id * 4), float(trial_id * 4 + 2)),
        DEFAULT_CONTEXT,
        {"valid": True, "source": "synthetic_ground_truth"},
    )
