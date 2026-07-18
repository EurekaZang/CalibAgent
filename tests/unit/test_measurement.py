from __future__ import annotations

import numpy as np
import pytest

from calibagent.interfaces.types import RawTrialData
from calibagent.measurement.pipeline import MeasurementConfig, MeasurementPipeline


def test_se2_regression_recovers_body_velocity(context) -> None:
    time = np.linspace(0, 2, 101)
    yaw = np.full_like(time, np.pi / 4)
    body_velocity = np.asarray([0.4, -0.1])
    rotation = np.asarray([[np.cos(yaw[0]), -np.sin(yaw[0])], [np.sin(yaw[0]), np.cos(yaw[0])]])
    world_velocity = rotation @ body_velocity
    pose = np.column_stack([time * world_velocity[0], time * world_velocity[1], yaw])
    command = np.repeat(np.asarray([[0.5, -0.1, 0.0]]), len(time), axis=0)
    raw = RawTrialData(time, command, pose, context)
    pipeline = MeasurementPipeline(MeasurementConfig(min_steady_ratio=0.9))
    result = pipeline.process(raw)
    assert result.valid
    np.testing.assert_allclose(result.mean_velocity, [0.4, -0.1, 0.0], atol=1e-8)


def test_timestamp_gap_is_rejected(context) -> None:
    time = np.r_[np.linspace(0, 0.8, 41), np.linspace(1.2, 2, 41)]
    pose = np.column_stack([0.2 * time, np.zeros_like(time), np.zeros_like(time)])
    command = np.repeat(np.asarray([[0.2, 0.0, 0.0]]), len(time), axis=0)
    result = MeasurementPipeline().process(RawTrialData(time, command, pose, context))
    assert not result.valid
    assert "TIMESTAMP_GAP" in str(result.quality["reason_codes"])


def test_se2_log_recovers_body_velocity_during_turn(context) -> None:
    time = np.linspace(0.0, 2.0, 101)
    vx, vy, wz = 0.4, -0.1, 0.8
    yaw = wz * time
    x = (vx * np.sin(yaw) + vy * (np.cos(yaw) - 1.0)) / wz
    y = (vx * (1.0 - np.cos(yaw)) + vy * np.sin(yaw)) / wz
    pose = np.column_stack([x, y, yaw])
    command = np.repeat(np.asarray([[0.5, -0.1, 0.8]]), len(time), axis=0)
    result = MeasurementPipeline(MeasurementConfig(min_steady_ratio=0.9)).process(
        RawTrialData(time, command, pose, context)
    )
    assert result.valid
    np.testing.assert_allclose(result.mean_velocity, [vx, vy, wz], atol=1e-8)


def test_empty_raw_trial_has_explicit_validation_error(context) -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        MeasurementPipeline().process(
            RawTrialData(np.empty(0), np.empty((0, 3)), np.empty((0, 3)), context)
        )
