"""Isaac Lab backend adapter with dependency injection across AppLauncher."""

from __future__ import annotations

from typing import Protocol

from calibagent.interfaces.types import (
    RawTrialData,
    RobotContext,
    RobotState,
    TrialPolicy,
    VelocityCommand,
)


class IsaacLabDriver(Protocol):
    """Driver implemented by the external Isaac Lab project after app startup."""

    def reset(self, context: RobotContext) -> None: ...
    def get_state(self) -> RobotState: ...
    def execute_trial(self, command: VelocityCommand, policy: TrialPolicy) -> RawTrialData: ...
    def emergency_stop(self, reason: str) -> None: ...


class IsaacLabBackend:
    """Adapt a live Isaac Lab driver to the simulator-agnostic backend port.

    Isaac Sim requires the application to be launched before importing most of
    its modules. The external P5 runner therefore constructs the driver and
    injects it here; constructing this adapter without a driver fails closed.
    """

    def __init__(self, driver: IsaacLabDriver | None = None) -> None:
        if driver is None:
            raise RuntimeError(
                "IsaacLabBackend requires a driver created after Isaac Lab AppLauncher startup"
            )
        self._driver = driver

    def reset(self, context: RobotContext) -> None:
        self._driver.reset(context)

    def get_state(self) -> RobotState:
        return self._driver.get_state()

    def execute_trial(self, command: VelocityCommand, policy: TrialPolicy) -> RawTrialData:
        return self._driver.execute_trial(command, policy)

    def emergency_stop(self, reason: str) -> None:
        self._driver.emergency_stop(reason)
