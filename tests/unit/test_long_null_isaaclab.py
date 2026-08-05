from __future__ import annotations

from calibagent.eval.long_null_isaaclab import _sequence_rows


def test_long_null_sequence_summary_uses_sequence_alarm_unit() -> None:
    rows = [
        {
            "seed": "3",
            "context_stage": "pre_shift",
            "monitor_trial": str(trial),
            "alarm": "True" if trial == 3 else "False",
            "cusum": str(float(trial)),
            "normalized_nis": "1.0",
            "valid": "True",
            "safety_events": "",
        }
        for trial in range(1, 5)
    ]
    summary = _sequence_rows("stationary", rows, 4)
    assert len(summary) == 1
    assert summary[0]["false_alarm"] is True
    assert summary[0]["first_alarm_trial"] == 3
    assert summary[0]["monitor_trials"] == 4
    assert summary[0]["maximum_cusum"] == 4.0


def test_long_null_sequence_rejects_missing_trial() -> None:
    rows = [
        {
            "seed": "3",
            "monitor_trial": "1",
            "alarm": "False",
            "cusum": "0.0",
            "normalized_nis": "1.0",
            "valid": "True",
            "safety_events": "",
        }
    ]
    try:
        _sequence_rows("stationary", rows, 2)
    except ValueError as error:
        assert "incomplete null-monitor sequence" in str(error)
    else:
        raise AssertionError("incomplete sequence was accepted")


def test_long_null_sequence_counts_distinct_safety_annotations() -> None:
    rows = [
        {
            "seed": "7",
            "monitor_trial": str(trial),
            "alarm": "False",
            "cusum": "0.0",
            "normalized_nis": "1.0",
            "valid": "True",
            "safety_events": "base_height" if trial == 2 else "",
        }
        for trial in range(1, 4)
    ]
    summary = _sequence_rows("stationary", rows, 3)
    assert summary[0]["monitor_safety_event_count"] == 1
