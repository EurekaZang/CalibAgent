"""P8 real-robot workflow tests use the immediate deterministic backend."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from calibagent.p8.analysis import analyze
from calibagent.p8.config import load_config, validate_config
from calibagent.p8.recording import export_jsonl
from calibagent.p8.runner import P8Runtime

ROOT = Path(__file__).resolve().parents[2]


def _count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def test_p8_frozen_protocol_counts_and_balancing() -> None:
    nav = validate_config(load_config(ROOT / "configs/p8/nav.yaml"))
    assert nav["expected"] == {
        "schedule_rows": 240,
        "calibration_trials": 3060,
        "validation_trials": 1920,
        "navigation_episodes": 480,
    }
    shift = validate_config(load_config(ROOT / "configs/p8/shift.yaml"))
    assert shift["expected"] == {
        "schedule_rows": 240,
        "sequences": 240,
        "motion_trials": 10800,
        "restore_checks": 480,
    }


def test_p8_nav_fake_end_to_end(tmp_path: Path) -> None:
    runtime = P8Runtime(
        load_config(ROOT / "configs/p8/nav.yaml"),
        "nav_fake",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=22,
    )
    try:
        result = runtime.run_nav(blocks=["NAV_BLOCK_01"], methods=["B8_full"])
    finally:
        runtime.close()
    assert result["completed_trials"] == 20
    assert result["completed_episodes"] == 2
    run_dir = tmp_path / "nav_fake"
    assert _count(run_dir / "trials.csv") == 20
    assert _count(run_dir / "navigation_episodes.csv") == 2
    assert export_jsonl(run_dir)["navigation_trace.csv"]
    assert analyze(run_dir)["protocol"] == "nav"


def test_p8_nav_max_units_stops_between_formal_routes(tmp_path: Path) -> None:
    runtime = P8Runtime(
        load_config(ROOT / "configs/p8/nav.yaml"),
        "nav_route_a_only",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=9,
    )
    try:
        result = runtime.run_nav(blocks=["NAV_BLOCK_01"], methods=["B0_raw"])
    finally:
        runtime.close()
    assert result["completed_trials"] == 8
    assert result["completed_episodes"] == 1
    episodes = list(
        csv.DictReader(
            (tmp_path / "nav_route_a_only" / "navigation_episodes.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert [row["map_id"] for row in episodes] == ["real_offset_slalom"]


def test_p8_shift_fake_complete_sequence_and_method_isolation(tmp_path: Path) -> None:
    runtime = P8Runtime(
        load_config(ROOT / "configs/p8/shift.yaml"),
        "shift_fake",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=47,
    )
    try:
        result = runtime.run_shift(
            shifts=["R1_command_gain_coupling"],
            blocks=["SHIFT_BLOCK_01"],
            methods=["full"],
        )
    finally:
        runtime.close()
    assert result["completed_trials"] == 47
    assert result["completed_sequences"] == 1
    run_dir = tmp_path / "shift_fake"
    assert _count(run_dir / "trials.csv") == 47
    assert _count(run_dir / "shift_sequences.csv") == 1
    assert analyze(run_dir)["protocol"] == "shift"


def test_p8_nav_resume_is_append_only_and_does_not_duplicate_trials(tmp_path: Path) -> None:
    config = load_config(ROOT / "configs/p8/nav.yaml")
    first = P8Runtime(
        config,
        "nav_resume",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=7,
    )
    try:
        first.run_nav(blocks=["NAV_BLOCK_01"], methods=["B8_full"])
    finally:
        first.close()
    resumed = P8Runtime(
        config,
        "nav_resume",
        tmp_path,
        backend_name="fake",
        resume=True,
        auto_continue=True,
    )
    try:
        result = resumed.run_nav(blocks=["NAV_BLOCK_01"], methods=["B8_full"])
    finally:
        resumed.close()
    assert result["completed_trials"] == 20
    assert result["completed_episodes"] == 2
    rows = list(csv.DictReader((tmp_path / "nav_resume" / "trials.csv").open(encoding="utf-8")))
    assert len(rows) == 20
    assert len({row["planned_unit_id"] for row in rows}) == 20


def test_p8_shift_resume_never_marks_a_partial_sequence_complete(tmp_path: Path) -> None:
    config = load_config(ROOT / "configs/p8/shift.yaml")
    first = P8Runtime(
        config,
        "shift_resume",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=17,
    )
    try:
        partial = first.run_shift(
            shifts=["R1_command_gain_coupling"],
            blocks=["SHIFT_BLOCK_01"],
            methods=["full"],
        )
    finally:
        first.close()
    assert partial["completed_trials"] == 17
    assert partial["completed_sequences"] == 0
    resumed = P8Runtime(
        config,
        "shift_resume",
        tmp_path,
        backend_name="fake",
        resume=True,
        auto_continue=True,
    )
    try:
        result = resumed.run_shift(
            shifts=["R1_command_gain_coupling"],
            blocks=["SHIFT_BLOCK_01"],
            methods=["full"],
        )
    finally:
        resumed.close()
    assert result["completed_trials"] == 47
    assert result["completed_sequences"] == 1
    rows = list(
        csv.DictReader((tmp_path / "shift_resume" / "trials.csv").open(encoding="utf-8"))
    )
    assert len(rows) == 47
    assert len({row["planned_unit_id"] for row in rows}) == 47


def test_p8_command_path_has_no_post_planner_control_layer() -> None:
    source = (ROOT / "src/calibagent/p8/backend.py").read_text(encoding="utf-8")
    runner = (ROOT / "src/calibagent/p8/runner.py").read_text(encoding="utf-8")
    forbidden_calls = (
        "np.clip(",
        "clamp(",
        "def _slew",
        "slew_limit",
        "safety_filter",
        "emergency_stop",
        "feedback_target",
    )
    for token in forbidden_calls:
        assert token not in source
        assert token not in runner
    assert "MOVE_API_ID = 1008" in source


def test_p8_calibration_transform_preserves_policy_zero(tmp_path: Path) -> None:
    runtime = P8Runtime(
        load_config(ROOT / "configs/p8/nav.yaml"),
        "zero_passthrough",
        tmp_path,
        backend_name="fake",
    )
    try:
        command, diagnostics = runtime.transform.apply(
            np.zeros(3), runtime._new_model("m1_affine")
        )
    finally:
        runtime.close()
    assert np.array_equal(command, np.zeros(3))
    assert diagnostics["candidate_id"] == "policy_zero_passthrough"
