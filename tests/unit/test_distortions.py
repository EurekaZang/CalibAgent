from __future__ import annotations

import numpy as np
import pytest

from calibagent.sim import (
    CommandDistortion,
    DistortionParameters,
    make_distortion_parameters,
)


def test_identity_distortion_is_exact() -> None:
    parameters = make_distortion_parameters("identity", [1, 2])
    distortion = CommandDistortion(parameters)
    commands = np.asarray([[0.2, -0.1, 0.3], [-0.2, 0.1, -0.3]])
    assert np.allclose(distortion.static_map(commands), commands)
    assert np.allclose(distortion.step(commands, 0.02), commands)


def test_seeded_mixed_distortion_is_deterministic_and_stateful() -> None:
    parameters_a = make_distortion_parameters("mixed", [11, 12])
    parameters_b = make_distortion_parameters("mixed", [11, 12])
    assert parameters_a.to_dict() == parameters_b.to_dict()
    commands = np.asarray([[0.6, 0.2, 0.8], [0.5, -0.2, -0.7]])
    first = CommandDistortion(parameters_a, seed=9)
    second = CommandDistortion(parameters_b, seed=9)
    outputs_a = [first.step(commands, 0.02) for _ in range(12)]
    outputs_b = [second.step(commands, 0.02) for _ in range(12)]
    assert np.allclose(outputs_a, outputs_b)
    assert not np.allclose(outputs_a[0], outputs_a[-1])
    first.reset()
    assert np.allclose(first.step(commands, 0.02, add_noise=False), 0.0)


def test_deadzone_and_saturation_are_enforced() -> None:
    parameters = make_distortion_parameters("deadzone", [23])
    distortion = CommandDistortion(parameters)
    low = parameters.deadzone * 0.5
    assert np.allclose(distortion.static_map(low), 0.0)
    high = np.asarray([[10.0, -10.0, 10.0]])
    mapped = distortion.static_map(high)
    assert np.all(np.abs(mapped) <= parameters.saturation + 1e-12)


def test_invalid_distortion_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        make_distortion_parameters("unknown", [1])
    parameters = make_distortion_parameters("identity", [1])
    distortion = CommandDistortion(parameters)
    with pytest.raises(ValueError, match="shape"):
        distortion.static_map(np.zeros((2, 3)))
    with pytest.raises(ValueError, match="positive"):
        distortion.step(np.zeros((1, 3)), 0.0)
    with pytest.raises(ValueError, match="deadzone"):
        DistortionParameters(
            np.eye(3)[None],
            np.zeros((1, 3)),
            -np.ones((1, 3)),
            np.ones((1, 3)),
            np.zeros(1, dtype=np.int64),
            np.zeros(1),
            np.zeros((1, 3)),
        )
