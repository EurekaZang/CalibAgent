"""P8 real-robot workflow tests use the immediate deterministic backend."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from calibagent.p8.analysis import analyze
from calibagent.p8.backend import _navigation_goal_reached
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


def test_p8_nav_route_phase_runs_only_selected_route(tmp_path: Path) -> None:
    runtime = P8Runtime(
        load_config(ROOT / "configs/p8/nav.yaml"),
        "nav_route_b_phase",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=9,
    )
    try:
        result = runtime.run_nav(
            blocks=["NAV_BLOCK_01"], methods=["B0_raw"], routes=["B"]
        )
    finally:
        runtime.close()
    assert result["completed_trials"] == 8
    assert result["completed_episodes"] == 1
    episodes = list(
        csv.DictReader(
            (tmp_path / "nav_route_b_phase" / "navigation_episodes.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert [row["map_id"] for row in episodes] == ["real_weighted_arc"]
    assert episodes[0]["route_order"] == "B"


def test_navigation_goal_requires_explicit_reached_and_geometric_arrival() -> None:
    goal = {"x": 2.0, "y": 3.0}
    near = {"x": 2.1, "y": 3.1}
    far = {"x": 8.0, "y": 9.0}
    assert not _navigation_goal_reached("WAITING_FOR_SCAN", near, goal, 0.25)
    assert not _navigation_goal_reached("NAVIGATING", near, goal, 0.25)
    assert not _navigation_goal_reached("REACHED", far, goal, 0.25)
    assert _navigation_goal_reached("REACHED", near, goal, 0.25)


def test_p8_nav_retries_inconsistent_false_success_episode(tmp_path: Path) -> None:
    runtime = P8Runtime(
        load_config(ROOT / "configs/p8/nav.yaml"),
        "nav_retry_false_success",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=9,
    )
    planned_unit_id = "NAV_BLOCK_01_B0_raw_NAV_real_offset_slalom"
    runtime.recorder.episodes.append(
        {
            "run_id": "nav_retry_false_success",
            "planned_unit_id": planned_unit_id,
            "attempt_id": planned_unit_id + "_attempt_01",
            "block_id": "NAV_BLOCK_01",
            "method_id": "B0_raw",
            "map_id": "real_offset_slalom",
            "route_order": "AB",
            "status": "SUCCESS",
            "terminal_reason": "reached",
            "success": True,
            "collision": False,
            "duration_s": 0.4,
            "path_length_m": 0.05,
            "final_goal_distance_m": 8.4,
            "route_goal_count": 5,
            "waypoints_reached": 4,
        }
    )
    try:
        result = runtime.run_nav(blocks=["NAV_BLOCK_01"], methods=["B0_raw"])
    finally:
        runtime.close()
    assert result["completed_trials"] == 8
    episodes = list(
        csv.DictReader(
            (tmp_path / "nav_retry_false_success" / "navigation_episodes.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(episodes) == 2
    assert episodes[-1]["attempt_id"].endswith("attempt_02")
    assert float(episodes[-1]["final_goal_distance_m"]) == 0.0


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
