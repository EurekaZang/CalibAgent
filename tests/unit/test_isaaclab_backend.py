from __future__ import annotations

import numpy as np
import pytest

from calibagent.backends.isaaclab import IsaacLabBackend
from calibagent.interfaces.types import (
    RawTrialData,
    RobotContext,
    RobotState,
    TrialPolicy,
    VelocityCommand,
)


class _Driver:
    def __init__(self) -> None:
        self.context: RobotContext | None = None
        self.stop_reason: str | None = None

    def reset(self, context: RobotContext) -> None:
        self.context = context

    def get_state(self) -> RobotState:
        return RobotState(0.0, (0.0, 0.0), 0.0, 0.0, 0.0, 0.3, (0.0, 0.0, 0.0))

    def execute_trial(self, command: VelocityCommand, policy: TrialPolicy) -> RawTrialData:
        assert self.context is not None
        timestamps = np.linspace(0.0, command.duration_s, 5)
        return RawTrialData(
            timestamps,
            np.tile(command.as_array(), (5, 1)),
            np.zeros((5, 3)),
            self.context,
        )

    def emergency_stop(self, reason: str) -> None:
        self.stop_reason = reason


def test_backend_delegates_to_live_driver() -> None:
    driver = _Driver()
    backend = IsaacLabBackend(driver)
    context = RobotContext("flat", 0.0, 1.0, "policy", "sim-1")
    backend.reset(context)
    command = VelocityCommand(0.2, 0.0, 0.0, 1.0)
    raw = backend.execute_trial(command, TrialPolicy())
    assert len(raw.timestamps) == 5
    assert backend.get_state().base_height == 0.3
    backend.emergency_stop("test")
    assert driver.stop_reason == "test"


def test_backend_without_app_driver_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="AppLauncher"):
        IsaacLabBackend()
