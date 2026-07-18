"""P8 extension seam; intentionally fails closed until the hardware gate."""

from __future__ import annotations

from calibagent.interfaces.types import (
    RawTrialData,
    RobotContext,
    RobotState,
    TrialPolicy,
    VelocityCommand,
)


class Go2RosBackend:
    def reset(self, context: RobotContext) -> None:
        raise NotImplementedError("Go2RosBackend is delivered in P8")

    def get_state(self) -> RobotState:
        raise NotImplementedError("Go2RosBackend is delivered in P8")

    def execute_trial(self, command: VelocityCommand, policy: TrialPolicy) -> RawTrialData:
        raise NotImplementedError("Go2RosBackend is delivered in P8")

    def emergency_stop(self, reason: str) -> None:
        raise NotImplementedError("Go2RosBackend is delivered in P8")
