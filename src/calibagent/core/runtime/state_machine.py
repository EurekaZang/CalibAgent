"""Explicit trial lifecycle with fail-closed illegal-transition handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from calibagent.interfaces.types import TrialPhase


class RuntimeEvent(str, Enum):
    PRECHECK_PASSED = "precheck_passed"
    RAMP_REACHED = "ramp_reached"
    SETTLED = "settled"
    MEASUREMENT_COMPLETE = "measurement_complete"
    RAMPED_OUT = "ramped_out"
    OBSERVATION_VALID = "observation_valid"
    OBSERVATION_INVALID = "observation_invalid"
    MODEL_UPDATED = "model_updated"
    CONTINUE = "continue"
    STOP = "stop"
    SAFETY_TRIGGER = "safety_trigger"
    ERROR = "error"


@dataclass(frozen=True)
class StateTransition:
    index: int
    source: TrialPhase
    target: TrialPhase
    event: RuntimeEvent
    reason: str


_NORMAL_TRANSITIONS: dict[tuple[TrialPhase, RuntimeEvent], TrialPhase] = {
    (TrialPhase.PRECHECK, RuntimeEvent.PRECHECK_PASSED): TrialPhase.RAMP_IN,
    (TrialPhase.RAMP_IN, RuntimeEvent.RAMP_REACHED): TrialPhase.EXCITE,
    (TrialPhase.EXCITE, RuntimeEvent.SETTLED): TrialPhase.MEASURE,
    (TrialPhase.MEASURE, RuntimeEvent.MEASUREMENT_COMPLETE): TrialPhase.RAMP_OUT,
    (TrialPhase.RAMP_OUT, RuntimeEvent.RAMPED_OUT): TrialPhase.VALIDATE,
    (TrialPhase.VALIDATE, RuntimeEvent.OBSERVATION_VALID): TrialPhase.UPDATE,
    (TrialPhase.VALIDATE, RuntimeEvent.OBSERVATION_INVALID): TrialPhase.ABORT,
    (TrialPhase.UPDATE, RuntimeEvent.MODEL_UPDATED): TrialPhase.DECIDE,
    (TrialPhase.DECIDE, RuntimeEvent.CONTINUE): TrialPhase.PRECHECK,
    (TrialPhase.DECIDE, RuntimeEvent.STOP): TrialPhase.DONE,
}
_TERMINAL = {TrialPhase.DONE, TrialPhase.ABORT}


class TrialStateMachine:
    """State machine whose transition trace is suitable for evidence logging."""

    def __init__(self) -> None:
        self.phase = TrialPhase.PRECHECK
        self.transitions: list[StateTransition] = []

    @property
    def terminal(self) -> bool:
        return self.phase in _TERMINAL

    def apply(self, event: RuntimeEvent, reason: str = "") -> TrialPhase:
        if self.terminal:
            raise RuntimeError(f"cannot transition terminal state {self.phase.value}")
        source = self.phase
        if event in {RuntimeEvent.SAFETY_TRIGGER, RuntimeEvent.ERROR}:
            target = TrialPhase.ABORT
        else:
            key = (source, event)
            if key not in _NORMAL_TRANSITIONS:
                raise ValueError(f"illegal transition: {source.value} + {event.value}")
            target = _NORMAL_TRANSITIONS[key]
        self.phase = target
        self.transitions.append(
            StateTransition(len(self.transitions), source, target, event, reason)
        )
        return target
