from __future__ import annotations

import json

import numpy as np
import pytest
from tests.conftest import observation

from calibagent.interfaces.types import TrialObservation, VelocityCommand


def test_velocity_command_array_round_trip() -> None:
    command = VelocityCommand.from_array(np.asarray([0.2, -0.1, 0.4]), duration_s=1.5)
    np.testing.assert_allclose(command.as_array(), [0.2, -0.1, 0.4])
    assert command.duration_s == 1.5


def test_trial_observation_json_round_trip(context) -> None:
    original = observation(np.asarray([0.1, 0.2, 0.3]), np.asarray([0.08, 0.18, 0.25]), context)
    payload = json.loads(json.dumps(original.to_dict()))
    restored = TrialObservation.from_dict(payload)
    assert restored.command == original.command
    assert restored.context == original.context
    np.testing.assert_allclose(restored.mean_velocity, original.mean_velocity)
    np.testing.assert_allclose(restored.covariance, original.covariance)


def test_contract_rejects_wrong_shapes(context) -> None:
    with pytest.raises(ValueError, match="mean_velocity"):
        TrialObservation(
            VelocityCommand(0, 0, 0, 2), np.zeros(2), np.eye(3), (0, 1), context, {"valid": True}
        )
    with pytest.raises(ValueError, match="shape"):
        VelocityCommand.from_array(np.zeros(4))
