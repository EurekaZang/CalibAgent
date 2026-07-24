"""Vectorized, stateful command distortions with known ground truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class DistortionParameters:
    affine: FloatArray
    bias: FloatArray
    deadzone: FloatArray
    saturation: FloatArray
    delay_steps: NDArray[np.int64]
    time_constant_s: FloatArray
    noise_std: FloatArray

    def __post_init__(self) -> None:
        count = len(self.affine)
        expected = {
            "affine": (count, 3, 3),
            "bias": (count, 3),
            "deadzone": (count, 3),
            "saturation": (count, 3),
            "delay_steps": (count,),
            "time_constant_s": (count,),
            "noise_std": (count, 3),
        }
        for name, shape in expected.items():
            array = np.asarray(getattr(self, name))
            if array.shape != shape or not np.all(np.isfinite(array)):
                raise ValueError(f"{name} must be finite with shape {shape}")
        if np.any(self.deadzone < 0) or np.any(self.saturation <= 0):
            raise ValueError("deadzone/saturation parameters are invalid")
        if np.any(self.delay_steps < 0) or np.any(self.time_constant_s < 0):
            raise ValueError("delay and time constants must be nonnegative")
        if np.any(self.noise_std < 0):
            raise ValueError("noise standard deviation must be nonnegative")

    @property
    def num_envs(self) -> int:
        return len(self.affine)

    def to_dict(self) -> dict[str, Any]:
        return {
            "affine": self.affine.tolist(),
            "bias": self.bias.tolist(),
            "deadzone": self.deadzone.tolist(),
            "saturation": self.saturation.tolist(),
            "delay_steps": self.delay_steps.tolist(),
            "time_constant_s": self.time_constant_s.tolist(),
            "noise_std": self.noise_std.tolist(),
        }


def make_distortion_parameters(
    family: str,
    seeds: NDArray[np.integer[Any]] | list[int] | tuple[int, ...],
) -> DistortionParameters:
    """Create paired per-environment parameters from explicit seeds."""

    seed_values = np.asarray(seeds, dtype=np.int64)
    count = len(seed_values)
    affine = np.repeat(np.eye(3, dtype=np.float64)[None, :, :], count, axis=0)
    bias = np.zeros((count, 3), dtype=np.float64)
    deadzone = np.zeros((count, 3), dtype=np.float64)
    saturation = np.tile(np.asarray([0.75, 0.45, 1.20]), (count, 1))
    delay_steps = np.zeros(count, dtype=np.int64)
    time_constant = np.zeros(count, dtype=np.float64)
    noise_std = np.zeros((count, 3), dtype=np.float64)
    valid = {"identity", "affine", "deadzone", "dynamic", "mixed"}
    if family not in valid:
        raise ValueError(f"unsupported distortion family: {family}")
    for index, seed in enumerate(seed_values):
        rng = np.random.default_rng(int(seed))
        if family in {"affine", "mixed"}:
            gains = rng.uniform([0.72, 0.72, 0.72], [0.92, 0.92, 0.92])
            affine[index] = np.diag(gains)
            coupling = rng.uniform(-0.08, 0.08, size=(3, 3))
            np.fill_diagonal(coupling, 0.0)
            affine[index] += coupling
            bias[index] = rng.uniform(
                [-0.025, -0.020, -0.035],
                [0.025, 0.020, 0.035],
            )
        if family in {"deadzone", "mixed"}:
            deadzone[index] = rng.uniform(
                [0.035, 0.025, 0.060],
                [0.090, 0.070, 0.150],
            )
            saturation[index] = rng.uniform(
                [0.55, 0.30, 0.85],
                [0.72, 0.42, 1.15],
            )
        if family in {"dynamic", "mixed"}:
            delay_steps[index] = int(rng.integers(1, 6))
            time_constant[index] = float(rng.uniform(0.05, 0.22))
        if family == "mixed":
            noise_std[index] = rng.uniform(
                [0.002, 0.002, 0.004],
                [0.008, 0.008, 0.012],
            )
    return DistortionParameters(
        affine,
        bias,
        deadzone,
        saturation,
        delay_steps,
        time_constant,
        noise_std,
    )


class CommandDistortion:
    """Apply deadzone, affine coupling, saturation, delay and lag in order."""

    def __init__(self, parameters: DistortionParameters, seed: int = 0) -> None:
        self.parameters = parameters
        self._rng = np.random.default_rng(seed)
        self._max_delay = int(np.max(parameters.delay_steps, initial=0))
        self._delay_buffer = np.zeros(
            (self._max_delay + 1, parameters.num_envs, 3),
            dtype=np.float64,
        )
        self._delay_index = 0
        self._filtered = np.zeros((parameters.num_envs, 3), dtype=np.float64)

    def reset(self) -> None:
        self._delay_buffer.fill(0.0)
        self._filtered.fill(0.0)
        self._delay_index = 0

    def static_map(self, commands: NDArray[np.floating[Any]]) -> FloatArray:
        values = np.asarray(commands, dtype=np.float64)
        if values.shape != (self.parameters.num_envs, 3):
            raise ValueError("commands must have shape (num_envs, 3)")
        after_deadzone = np.sign(values) * np.maximum(
            np.abs(values) - self.parameters.deadzone,
            0.0,
        )
        affine = np.einsum(
            "nij,nj->ni",
            self.parameters.affine,
            after_deadzone,
        )
        biased = affine + self.parameters.bias
        return np.asarray(
            np.clip(
                biased,
                -self.parameters.saturation,
                self.parameters.saturation,
            ),
            dtype=np.float64,
        )

    def step(
        self,
        commands: NDArray[np.floating[Any]],
        dt: float,
        *,
        add_noise: bool = True,
    ) -> FloatArray:
        if dt <= 0 or not np.isfinite(dt):
            raise ValueError("dt must be finite and positive")
        static = self.static_map(commands)
        self._delay_buffer[self._delay_index] = static
        env_ids = np.arange(self.parameters.num_envs)
        read_indices = (
            self._delay_index - self.parameters.delay_steps
        ) % len(self._delay_buffer)
        delayed = self._delay_buffer[read_indices, env_ids]
        tau = self.parameters.time_constant_s[:, None]
        alpha = np.where(tau > 0, 1.0 - np.exp(-dt / np.maximum(tau, 1e-12)), 1.0)
        self._filtered += alpha * (delayed - self._filtered)
        self._delay_index = (self._delay_index + 1) % len(self._delay_buffer)
        if not add_noise or not np.any(self.parameters.noise_std):
            return self._filtered.copy()
        noise = self._rng.normal(size=self._filtered.shape) * self.parameters.noise_std
        return self._filtered + noise
