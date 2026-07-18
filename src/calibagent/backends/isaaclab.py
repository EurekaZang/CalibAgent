"""P5 extension seam; intentionally fails closed until Isaac Lab is integrated."""

from __future__ import annotations

from calibagent.interfaces.types import (
    RawTrialData,
    RobotContext,
    RobotState,
    TrialPolicy,
    VelocityCommand,
)


class IsaacLabBackend:
    def reset(self, context: RobotContext) -> None:
        raise NotImplementedError("IsaacLabBackend is delivered in P5")

    def get_state(self) -> RobotState:
        raise NotImplementedError("IsaacLabBackend is delivered in P5")

    def execute_trial(self, command: VelocityCommand, policy: TrialPolicy) -> RawTrialData:
        raise NotImplementedError("IsaacLabBackend is delivered in P5")

    def emergency_stop(self, reason: str) -> None:
        raise NotImplementedError("IsaacLabBackend is delivered in P5")
