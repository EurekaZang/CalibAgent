from __future__ import annotations

import numpy as np
import pytest

from calibagent.core.safety import HardSafetyFilter, SafetyEnvelope
from calibagent.interfaces.types import Candidate, RobotState, VelocityCommand


def _state(**changes: object) -> RobotState:
    values: dict[str, object] = {
        "timestamp": 0.0,
        "position_xy": (0.0, 0.0),
        "yaw": 0.0,
        "roll": 0.0,
        "pitch": 0.0,
        "base_height": 0.32,
        "velocity": (0.0, 0.0, 0.0),
        "battery_ratio": 0.8,
        "localization_valid": True,
    }
    values.update(changes)
    return RobotState(**values)  # type: ignore[arg-type]


def _candidate(command: tuple[float, float, float], duration: float = 2.0) -> Candidate:
    return Candidate(VelocityCommand(*command, duration), 1.0, 1.0, 0.0)


def test_safe_candidate_is_accepted() -> None:
    decision = HardSafetyFilter().evaluate(_candidate((0.25, 0.0, 0.2)), _state(), [])
    assert decision.accepted
    assert decision.command is not None
    assert decision.reason_codes == ()


@pytest.mark.parametrize(
    ("candidate", "state", "history", "reason"),
    [
        (_candidate((0.8, 0.0, 0.0)), _state(), [], "COMMAND_AXIS_0"),
        (_candidate((0.6, 0.6, 0.0)), _state(), [], "COMMAND_AXIS_1"),
        (_candidate((0.6, 0.0, 1.0)), _state(), [_candidate((0.4, 0.0, 0.5))], "LINEAR_ANGULAR_COUPLING"),
        (_candidate((0.5, 0.0, 0.0)), _state(), [], "LINEAR_SLEW"),
        (_candidate((0.0, 0.0, 0.9)), _state(), [], "ANGULAR_SLEW"),
        (_candidate((0.3, 0.0, 0.0)), _state(position_xy=(4.5, 0.0)), [], "WORKSPACE_PROJECTED_AXIS_0"),
        (_candidate((0.1, 0.0, 0.0)), _state(roll=0.5), [], "ROLL_LIMIT"),
        (_candidate((0.1, 0.0, 0.0)), _state(pitch=-0.5), [], "PITCH_LIMIT"),
        (_candidate((0.1, 0.0, 0.0)), _state(base_height=0.1), [], "BASE_HEIGHT_LIMIT"),
        (_candidate((0.1, 0.0, 0.0)), _state(velocity=(0.0, 0.0, 2.1)), [], "YAW_RATE_LIMIT"),
        (_candidate((0.1, 0.0, 0.0)), _state(battery_ratio=0.1), [], "LOW_BATTERY"),
        (_candidate((0.1, 0.0, 0.0)), _state(localization_valid=False), [], "LOCALIZATION_INVALID"),
    ],
)
def test_hazard_reason_codes_are_stable(
    candidate: Candidate,
    state: RobotState,
    history: list[Candidate],
    reason: str,
) -> None:
    decision = HardSafetyFilter().evaluate(candidate, state, history)
    assert not decision.accepted
    assert reason in decision.reason_codes
    assert decision.command is None


def test_nonfinite_and_no_safe_candidate_fail_closed() -> None:
    unsafe = _candidate((float("nan"), 0.0, 0.0))
    filter_ = HardSafetyFilter()
    assert filter_.evaluate(unsafe, _state(), []).reason_codes == ("COMMAND_NONFINITE",)
    selection = filter_.select_first_safe([unsafe], _state(), [])
    assert not selection.accepted
    assert selection.reason_codes[:2] == ("NO_SAFE_CANDIDATE", "COMMAND_NONFINITE")


def test_invalid_envelope_is_rejected() -> None:
    with pytest.raises(ValueError, match="low < high"):
        SafetyEnvelope(command_bounds=((0.0, 0.0), (-1.0, 1.0), (-1.0, 1.0)))
    state = _state(position_xy=(float("nan"), 0.0))
    assert HardSafetyFilter().monitor(state).reason_codes == ("STATE_NONFINITE",)
    assert np.isfinite(_candidate((0.1, 0.0, 0.0)).command.as_array()).all()
