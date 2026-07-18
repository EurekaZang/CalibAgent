"""Shared simulator/robot measurement processing without adjacent-pose differencing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from calibagent.interfaces.types import RawTrialData, TrialObservation, VelocityCommand


@dataclass(frozen=True)
class MeasurementConfig:
    min_samples: int = 30
    max_drop_ratio: float = 0.15
    max_timestamp_gap_s: float = 0.10
    huber_delta: float = 1.5
    min_steady_ratio: float = 0.65
    steady_acceleration_threshold: float = 0.25


class MeasurementPipeline:
    def __init__(self, config: MeasurementConfig | None = None) -> None:
        self.config = config if config is not None else MeasurementConfig()

    @staticmethod
    def _se2_body_twists(
        time: NDArray[np.float64], pose: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Estimate constant body twists from one reference to every later pose.

        Using the SE(2) logarithm avoids the chord/mean-yaw bias of fitting world
        coordinates during a turn. Each row is an estimate over a different
        horizon, rather than a noisy adjacent-pose difference.
        """
        if len(time) < 2:
            return np.empty((0, 3), dtype=np.float64)
        elapsed = time[1:] - time[0]
        yaw = np.unwrap(pose[:, 2])
        delta_yaw = yaw[1:] - yaw[0]
        cosine = float(np.cos(yaw[0]))
        sine = float(np.sin(yaw[0]))
        displacement = pose[1:, :2] - pose[0, :2]
        relative = np.column_stack(
            [
                cosine * displacement[:, 0] + sine * displacement[:, 1],
                -sine * displacement[:, 0] + cosine * displacement[:, 1],
            ]
        )
        a = np.ones_like(delta_yaw)
        b = np.zeros_like(delta_yaw)
        rotating = np.abs(delta_yaw) > 1e-8
        a[rotating] = np.sin(delta_yaw[rotating]) / delta_yaw[rotating]
        b[rotating] = (1.0 - np.cos(delta_yaw[rotating])) / delta_yaw[rotating]
        denominator = np.maximum(a * a + b * b, 1e-15)
        body_displacement = np.column_stack(
            [
                (a * relative[:, 0] + b * relative[:, 1]) / denominator,
                (-b * relative[:, 0] + a * relative[:, 1]) / denominator,
            ]
        )
        return np.column_stack([body_displacement / elapsed[:, None], delta_yaw / elapsed])

    def _robust_twist_mean(
        self, twists: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        if not len(twists):
            return np.full(3, np.nan), np.empty((0, 3), dtype=np.float64)
        location = np.median(twists, axis=0)
        weights = np.ones_like(twists)
        for _ in range(20):
            residual = twists - location
            scale = 1.4826 * np.median(np.abs(residual), axis=0) + 1e-12
            normalized = np.abs(residual) / scale
            weights = np.where(
                normalized <= self.config.huber_delta,
                1.0,
                self.config.huber_delta / np.maximum(normalized, 1e-12),
            )
            updated = np.sum(weights * twists, axis=0) / np.maximum(np.sum(weights, axis=0), 1e-12)
            if np.linalg.norm(updated - location) < 1e-10:
                location = updated
                break
            location = updated
        return np.asarray(location, dtype=np.float64), weights

    def process(self, raw: RawTrialData) -> TrialObservation:
        t = np.asarray(raw.timestamps, dtype=np.float64)
        pose = np.asarray(raw.pose_se2, dtype=np.float64)
        commands = np.asarray(raw.command, dtype=np.float64)
        reasons: list[str] = []
        if t.ndim != 1 or pose.shape != (len(t), 3) or commands.shape != (len(t), 3):
            raise ValueError("raw timestamps, pose_se2, and command shapes are inconsistent")
        if len(t) == 0:
            raise ValueError("raw trial must contain at least one sample")
        if len(t) < self.config.min_samples:
            reasons.append("INSUFFICIENT_SAMPLES")
        dt = np.diff(t)
        if np.any(dt <= 0):
            reasons.append("NON_MONOTONIC_TIMESTAMP")
        if len(dt) and np.max(dt) > self.config.max_timestamp_gap_s:
            reasons.append("TIMESTAMP_GAP")
        expected_samples = max(1, int(np.ceil((t[-1] - t[0]) / np.median(dt)))) if len(dt) else 1
        drop_ratio = max(0.0, 1.0 - len(t) / expected_samples)
        if drop_ratio > self.config.max_drop_ratio:
            reasons.append("EXCESSIVE_DROP_RATE")

        yaw = np.unwrap(pose[:, 2])
        twists = self._se2_body_twists(t, pose)
        mean_velocity, twist_weights = self._robust_twist_mean(twists)

        if len(dt) > 1:
            segment_world = np.diff(np.column_stack([pose[:, :2], yaw]), axis=0) / dt[:, None]
            segment_body = segment_world.copy()
            for index, angle in enumerate(yaw[:-1]):
                rotation = np.asarray(
                    [[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]]
                )
                segment_body[index, :2] = rotation @ segment_world[index, :2]
            covariance = np.atleast_2d(np.cov(segment_body, rowvar=False)) / max(
                len(segment_body), 1
            )
            acceleration = np.linalg.norm(np.diff(segment_body, axis=0), axis=1) / np.maximum(
                dt[1:], 1e-9
            )
            steady_ratio = float(np.mean(acceleration < self.config.steady_acceleration_threshold))
        else:
            covariance = np.eye(3) * np.inf
            steady_ratio = 0.0
        if steady_ratio < self.config.min_steady_ratio:
            reasons.append("INSUFFICIENT_STEADY_RATIO")
        outlier_ratio = float(1.0 - np.mean(twist_weights)) if twist_weights.size else 1.0
        finite = bool(np.all(np.isfinite(mean_velocity)) and np.all(np.isfinite(covariance)))
        if not finite:
            reasons.append("NONFINITE_ESTIMATE")
        command_mean = np.mean(commands, axis=0)
        command_constant = bool(np.max(np.linalg.norm(commands - command_mean, axis=1)) < 1e-3)
        if not command_constant:
            reasons.append("COMMAND_NOT_CONSTANT")
        quality: dict[str, float | bool | str] = {
            "valid": not reasons,
            "reason_codes": ",".join(reasons),
            "num_samples": float(len(t)),
            "drop_ratio": float(drop_ratio),
            "steady_ratio": steady_ratio,
            "outlier_ratio": outlier_ratio,
            "command_constant": command_constant,
        }
        command = VelocityCommand.from_array(command_mean, duration_s=float(t[-1] - t[0]))
        return TrialObservation(
            command,
            mean_velocity,
            np.asarray(covariance, dtype=np.float64),
            (float(t[0]), float(t[-1])),
            raw.context,
            quality,
            raw_ref=raw.raw_ref,
        )
