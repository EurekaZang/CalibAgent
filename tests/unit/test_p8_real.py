"""P8 real-robot workflow tests use the immediate deterministic backend."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from calibagent.p8.analysis import analyze
from calibagent.p8.backend import (
    _navigation_goal_reached,
    navigation_quality_reasons,
    trial_quality_diagnostics,
)
from calibagent.p8.config import load_config, validate_config
from calibagent.p8.recording import AppendCsv, export_jsonl
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
        "schedule_rows": 36,
        "sequences": 36,
        "motion_trials": 1620,
        "restore_checks": 72,
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


def test_p8_overwrite_replaces_only_the_exact_run_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "replace_me"
    run_dir.mkdir()
    sentinel = run_dir / "stale.txt"
    sentinel.write_text("stale", encoding="utf-8")
    sibling = tmp_path / "keep_me"
    sibling.mkdir()

    runtime = P8Runtime(
        load_config(ROOT / "configs/p8/nav.yaml"),
        "replace_me",
        tmp_path,
        backend_name="fake",
        overwrite=True,
        auto_continue=True,
        max_units=1,
    )
    try:
        result = runtime.run_nav(
            blocks=["NAV_BLOCK_01"], methods=["B0_raw"], routes=["A"]
        )
    finally:
        runtime.close()

    assert result["units_executed"] == 1
    assert not sentinel.exists()
    assert sibling.is_dir()


def test_navigation_goal_requires_explicit_reached_and_geometric_arrival() -> None:
    goal = {"x": 2.0, "y": 3.0}
    near = {"x": 2.1, "y": 3.1}
    far = {"x": 8.0, "y": 9.0}
    assert not _navigation_goal_reached("WAITING_FOR_SCAN", near, goal, 0.25)
    assert not _navigation_goal_reached("NAVIGATING", near, goal, 0.25)
    assert not _navigation_goal_reached("REACHED", far, goal, 0.25)
    assert _navigation_goal_reached("REACHED", near, goal, 0.25)


def test_navigation_quality_uses_delivery_and_active_action_freshness() -> None:
    metrics = {
        "max_scan_age_ms": 99.0,
        "max_reference_source_age_ms": 101.0,
        "max_reference_receive_gap_ms": 87.0,
        "max_scan_receive_gap_ms": 68.0,
        "max_active_action_receive_age_ms": 40.0,
        "max_planned_action_receive_gap_ms": 76.0,
        "max_active_action_receive_gap_ms": 76.0,
        "planned_action_rate_hz": 22.0,
        "reference_rate_hz": 20.0,
        "scan_rate_hz": 20.0,
    }
    quality = {
        "max_scan_age_ms": 120.0,
        "max_reference_age_ms": 120.0,
        "max_reference_gap_ms": 120.0,
        "max_scan_gap_ms": 120.0,
        "max_planned_action_receive_age_ms": 80.0,
        "max_planned_action_gap_ms": 120.0,
        "min_planned_action_rate_hz": 20.0,
        "min_reference_rate_hz": 10.0,
        "min_scan_rate_hz": 15.0,
    }
    assert navigation_quality_reasons(metrics, quality) == []
    metrics["max_reference_receive_gap_ms"] = 121.0
    assert navigation_quality_reasons(metrics, quality) == [
        "reference receive gap exceeded data-quality threshold"
    ]


def test_trial_quality_ignores_one_age_spike_but_detects_sustained_staleness() -> None:
    receives = np.arange(80, dtype=np.float64) * 0.05
    ages = [80.0] * 80
    ages[35] = 127.4
    measure_samples = [
        {"age_ms": ages[index], "receive": float(receives[index])}
        for index in range(20, 60)
    ]
    diagnostics, reasons = trial_quality_diagnostics(
        ages,
        receives,
        [50.0] * 80,
        receives,
        measure_samples,
        {"max_reference_age_ms": 120.0},
    )
    assert reasons == []
    assert diagnostics["reference_max_age_ms"] == 127.4
    assert diagnostics["reference_age_exceedance_count"] == 1
    assert diagnostics["reference_measure_age_p95_ms"] == 80.0

    for index in range(35, 40):
        ages[index] = 140.0
        measure_samples[index - 20]["age_ms"] = 140.0
    _, reasons = trial_quality_diagnostics(
        ages,
        receives,
        [50.0] * 80,
        receives,
        measure_samples,
        {"max_reference_age_ms": 120.0},
    )
    assert reasons == [
        "reference measure-window p95 age exceeded data-quality threshold"
    ]


def test_trial_quality_detects_measure_window_receive_gap() -> None:
    measure_receives = np.arange(40, dtype=np.float64) * 0.05
    measure_receives[20:] += 0.13
    measure_samples = [
        {"age_ms": 80.0, "receive": float(receive)}
        for receive in measure_receives
    ]
    _, reasons = trial_quality_diagnostics(
        [80.0] * 40,
        measure_receives,
        [50.0] * 40,
        np.arange(40, dtype=np.float64) * 0.05,
        measure_samples,
        {"max_reference_age_ms": 120.0, "max_reference_gap_ms": 120.0},
    )
    assert reasons == [
        "reference measure-window receive gap exceeded data-quality threshold"
    ]


def test_append_csv_resumes_legacy_compatible_header_without_widening_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.csv"
    path.write_text("id,status\nold,SUCCESS\n", encoding="utf-8")
    table = AppendCsv(path, ("id", "new_metric", "status"))
    table.append({"id": "new", "new_metric": 42, "status": "SUCCESS"})
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == ["id", "status"]
    assert rows == [
        {"id": "old", "status": "SUCCESS"},
        {"id": "new", "status": "SUCCESS"},
    ]


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


def test_resume_code_migration_requires_explicit_manifest_audit(tmp_path: Path) -> None:
    config = load_config(ROOT / "configs/p8/nav.yaml")
    first = P8Runtime(
        config,
        "code_migration",
        tmp_path,
        backend_name="fake",
        auto_continue=True,
        max_units=1,
    )
    try:
        first.run_nav(blocks=["NAV_BLOCK_01"], methods=["B0_raw"], routes=["A"])
    finally:
        first.close()
    manifest_path = tmp_path / "code_migration" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["git_commit"] = "pre-fix-commit"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="--allow-code-migration"):
        P8Runtime(
            config,
            "code_migration",
            tmp_path,
            backend_name="fake",
            resume=True,
        )

    resumed = P8Runtime(
        config,
        "code_migration",
        tmp_path,
        backend_name="fake",
        resume=True,
        allow_code_migration=True,
    )
    resumed.close()
    migrated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert migrated["code_history"][-1]["from_commit"] == "pre-fix-commit"
    assert "explicitly authorized" in migrated["code_history"][-1]["reason"]


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
