from __future__ import annotations

import pytest

from calibagent.core.runtime import RuntimeEvent, TrialStateMachine
from calibagent.interfaces.types import TrialPhase


def test_happy_path_is_complete_and_traceable() -> None:
    machine = TrialStateMachine()
    events = [
        RuntimeEvent.PRECHECK_PASSED,
        RuntimeEvent.RAMP_REACHED,
        RuntimeEvent.SETTLED,
        RuntimeEvent.MEASUREMENT_COMPLETE,
        RuntimeEvent.RAMPED_OUT,
        RuntimeEvent.OBSERVATION_VALID,
        RuntimeEvent.MODEL_UPDATED,
        RuntimeEvent.STOP,
    ]
    for event in events:
        machine.apply(event)
    assert machine.phase is TrialPhase.DONE
    assert machine.terminal
    assert len(machine.transitions) == len(events)
    assert machine.transitions[0].source is TrialPhase.PRECHECK
    assert machine.transitions[-1].target is TrialPhase.DONE


def test_safety_trigger_aborts_every_active_phase() -> None:
    machine = TrialStateMachine()
    machine.apply(RuntimeEvent.PRECHECK_PASSED)
    phase = machine.apply(RuntimeEvent.SAFETY_TRIGGER, "ROLL_LIMIT")
    assert phase is TrialPhase.ABORT
    assert machine.transitions[-1].reason == "ROLL_LIMIT"


def test_invalid_transitions_fail_closed() -> None:
    machine = TrialStateMachine()
    with pytest.raises(ValueError, match="illegal transition"):
        machine.apply(RuntimeEvent.MEASUREMENT_COMPLETE)
    machine.apply(RuntimeEvent.ERROR, "backend")
    with pytest.raises(RuntimeError, match="terminal"):
        machine.apply(RuntimeEvent.CONTINUE)
