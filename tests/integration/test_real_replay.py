from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from calibagent.eval.readiness import _real_data_checks
from calibagent.eval.real_delivery import verify_real_delivery
from calibagent.eval.real_replay import (
    build_real_replay_evidence,
    file_sha256,
    process_raw_trials,
)


def _raw_fixture() -> pd.DataFrame:
    rng = np.random.default_rng(81)
    matrix = np.asarray([[0.82, 0.18, 0.05], [-0.12, 0.91, 0.04], [0.08, -0.05, 0.84]])
    rows = []
    for session in range(3):
        anchors = np.asarray(
            [
                [-0.5, -0.2, -0.7],
                [0.5, 0.2, 0.7],
                [-0.4, 0.2, 0.6],
                [0.4, -0.2, -0.6],
            ]
        )
        commands = np.vstack([anchors, rng.uniform([-0.6, -0.3, -0.8], [0.6, 0.3, 0.8], (8, 3))])
        for trial, command in enumerate(commands):
            velocity = matrix @ command
            time = np.linspace(0.0, 2.0, 101)
            vx, vy, wz = velocity
            yaw = wz * time
            if abs(wz) < 1e-10:
                x, y = vx * time, vy * time
            else:
                x = (vx * np.sin(yaw) + vy * (np.cos(yaw) - 1.0)) / wz
                y = (vx * (1.0 - np.cos(yaw)) + vy * np.sin(yaw)) / wz
            for index in range(len(time)):
                rows.append(
                    {
                        "trial_id": trial,
                        "session_id": f"session-{session}",
                        "timestamp": session * 100.0 + trial * 4.0 + time[index],
                        "cmd_vx": command[0],
                        "cmd_vy": command[1],
                        "cmd_wz": command[2],
                        "pose_x": x[index],
                        "pose_y": y[index],
                        "pose_yaw": yaw[index],
                        "terrain_id": "fixture",
                    }
                )
    return pd.DataFrame(rows)


def test_real_replay_builder_keeps_fixture_marked_synthetic(tmp_path) -> None:
    source = tmp_path / "fixture.csv"
    raw = _raw_fixture()
    raw.to_csv(source, index=False)
    plan_path = tmp_path / "plan.csv"
    raw.groupby(["session_id", "trial_id"], as_index=False)[
        ["cmd_vx", "cmd_vy", "cmd_wz"]
    ].first().to_csv(plan_path, index=False)
    output = tmp_path / "evidence"
    evidence = build_real_replay_evidence(
        source,
        output,
        source_kind="synthetic_fixture",
        robot_model="unitree_go2",
        reference_sensor="synthetic",
        capture_plan=plan_path,
        budget=8,
        validation_fraction=0.3,
    )
    assert evidence["synthetic"] is True
    assert evidence["valid_observations"] == 36
    assert len(evidence["sessions"]) == 3
    assert evidence["capture_plan_command_match"] == 1.0
    assert evidence["capture_plan_completion"] == 1.0
    assert (output / "observations.parquet").is_file()
    assert (output / "sampling_sensitivity.json").is_file()
    frozen = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert frozen["source_sha256"] == evidence["source_sha256"]
    checks = {
        check.check_id: check
        for check in _real_data_checks(
            tmp_path,
            {
                "required_real_data_manifest": "evidence/manifest.json",
                "real_data": {
                    "robot_model": "unitree_go2",
                    "min_sessions": 3,
                    "min_valid_observations": 30,
                    "min_axis_command_magnitude": 0.1,
                    "min_m1_vs_raw_rmse_reduction": -1.0,
                    "min_m1_vs_m0_rmse_reduction": -1.0,
                    "min_capture_plan_command_match": 0.99,
                    "min_capture_plan_completion": 0.82,
                },
            },
        )
    }
    assert not checks["p1_real_data_evidence"].passed
    assert checks["p1_real_data_scale_coverage"].passed
    assert checks["p1_real_baseline_improvement"].passed


def test_raw_trial_schema_rejects_missing_columns() -> None:
    try:
        process_raw_trials(pd.DataFrame({"trial_id": [1]}))
    except ValueError as error:
        assert "missing required columns" in str(error)
    else:
        raise AssertionError("incomplete raw schema was accepted")


def _write_delivery_checksums(root: Path) -> None:
    checksum_path = root / "checksums.sha256"
    checksum_path.write_text(
        "\n".join(
            f"{file_sha256(path)}  ./{path.relative_to(root).as_posix()}"
            for path in sorted(root.rglob("*"))
            if path.is_file() and path != checksum_path
        )
        + "\n",
        encoding="utf-8",
    )


def _minimal_delivery(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "delivery"
    for relative in (
        "calibration",
        "capture_plan",
        "exported",
        "metadata",
        "raw/go2-session-01/reference_native",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    raw = _raw_fixture()
    raw = raw[(raw["session_id"] == "session-0") & (raw["trial_id"] == 0)].copy()
    raw["session_id"] = "go2-session-01"
    source = root / "exported/go2_raw_trials.csv"
    raw.to_csv(source, index=False)
    plan = (
        raw.groupby(["session_id", "trial_id"], as_index=False)[
            ["cmd_vx", "cmd_vy", "cmd_wz"]
        ]
        .first()
        .assign(sample_rate_hz=50.0)
    )
    plan_path = root / "capture_plan/plan.csv"
    plan.to_csv(plan_path, index=False)

    native = raw[
        ["timestamp", "cmd_vx", "cmd_vy", "cmd_wz", "pose_x", "pose_y", "pose_yaw"]
    ].copy()
    native["phase"] = "measure"
    native["loc_ready"] = "true"
    native["frame_id"] = "map"
    native["child_frame_id"] = "base_link"
    native_path = (
        root
        / "raw/go2-session-01/reference_native/trial_00_attempt_01.csv"
    )
    native.to_csv(native_path, index=False)
    pd.DataFrame(
        [
            {
                "session_id": "go2-session-01",
                "trial_id": 0,
                "attempt_id": 1,
                "status": "complete",
                "exclusion_reason": "",
                "selected_for_csv": True,
                "reference_valid": True,
            }
        ]
    ).to_csv(root / "metadata/trial_ledger.csv", index=False)
    pd.DataFrame(
        [{"session_id": "go2-session-01", "rosbag_recorded": "yes"}]
    ).to_csv(root / "metadata/session_metadata.csv", index=False)
    for relative in (
        "README.md",
        "calibration/calibration_notes.md",
        "calibration/reference_to_base_extrinsic.yaml",
        "metadata/coordinate_frames.md",
        "metadata/time_sync.md",
    ):
        (root / relative).write_text("test fixture\n", encoding="utf-8")
    _write_delivery_checksums(root)
    return root, source, plan_path, native_path


def test_real_delivery_traces_final_rows_to_checksummed_native_attempt(tmp_path) -> None:
    root, source, plan_path, native_path = _minimal_delivery(tmp_path)
    verification = verify_real_delivery(root, source, plan_path)

    assert verification["verified"] is True
    assert verification["native_traceability_ratio"] == 1.0
    assert verification["checksum_files_verified"] == 10

    native_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_real_delivery(root, source, plan_path)


def test_real_delivery_rejects_missing_or_unlisted_artifacts(tmp_path) -> None:
    root, source, plan_path, _ = _minimal_delivery(tmp_path / "missing")
    (root / "metadata/time_sync.md").unlink()
    with pytest.raises(ValueError, match=r"missing metadata/time_sync\.md"):
        verify_real_delivery(root, source, plan_path)

    root, source, plan_path, _ = _minimal_delivery(tmp_path / "unlisted")
    (root / "unexpected.txt").write_text("not checksummed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing from checksum manifest"):
        verify_real_delivery(root, source, plan_path)


def test_real_delivery_rejects_ambiguous_or_unexplained_attempts(tmp_path) -> None:
    root, source, plan_path, _ = _minimal_delivery(tmp_path / "duplicate")
    ledger_path = root / "metadata/trial_ledger.csv"
    ledger = pd.read_csv(ledger_path)
    duplicate = ledger.iloc[0].copy()
    duplicate["attempt_id"] = 2
    ledger = pd.concat([ledger, duplicate.to_frame().T], ignore_index=True)
    ledger.to_csv(ledger_path, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="multiple attempts"):
        verify_real_delivery(root, source, plan_path)

    root, source, plan_path, _ = _minimal_delivery(tmp_path / "unexplained")
    ledger_path = root / "metadata/trial_ledger.csv"
    ledger = pd.read_csv(ledger_path)
    rejected = ledger.iloc[0].copy()
    rejected["attempt_id"] = 2
    rejected["status"] = "technical_abort"
    rejected["selected_for_csv"] = False
    rejected["exclusion_reason"] = ""
    pd.concat([ledger, rejected.to_frame().T], ignore_index=True).to_csv(
        ledger_path, index=False
    )
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="no exclusion reason"):
        verify_real_delivery(root, source, plan_path)


def test_real_delivery_rejects_nonmonotonic_and_untraceable_data(tmp_path) -> None:
    root, source, plan_path, _ = _minimal_delivery(tmp_path / "time")
    raw = pd.read_csv(source)
    raw.loc[1, "timestamp"] = raw.loc[0, "timestamp"]
    raw.to_csv(source, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="non-monotonic"):
        verify_real_delivery(root, source, plan_path)

    root, source, plan_path, native_path = _minimal_delivery(tmp_path / "native")
    native_path.unlink()
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="native attempt is missing"):
        verify_real_delivery(root, source, plan_path)


def test_real_delivery_rejects_source_plan_and_ledger_mismatch(tmp_path) -> None:
    root, source, plan_path, _ = _minimal_delivery(tmp_path / "source")
    other_source = tmp_path / "different.csv"
    other_source.write_text("different\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source CSV does not match"):
        verify_real_delivery(root, other_source, plan_path)

    root, source, plan_path, _ = _minimal_delivery(tmp_path / "plan")
    other_plan = tmp_path / "different-plan.csv"
    other_plan.write_text(plan_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="capture plan does not match"):
        verify_real_delivery(root, source, other_plan)

    root, source, plan_path, _ = _minimal_delivery(tmp_path / "ledger-columns")
    ledger_path = root / "metadata/trial_ledger.csv"
    pd.read_csv(ledger_path).drop(columns=["status"]).to_csv(ledger_path, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="ledger is missing columns"):
        verify_real_delivery(root, source, plan_path)

    root, source, plan_path, _ = _minimal_delivery(tmp_path / "ledger-status")
    ledger_path = root / "metadata/trial_ledger.csv"
    ledger = pd.read_csv(ledger_path)
    ledger.loc[0, "status"] = "post_hoc_reject"
    ledger.to_csv(ledger_path, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="unsupported status"):
        verify_real_delivery(root, source, plan_path)


def test_real_delivery_rejects_corrupt_final_and_native_rows(tmp_path) -> None:
    root, source, plan_path, _ = _minimal_delivery(tmp_path / "nonfinite")
    raw = pd.read_csv(source)
    raw.loc[0, "pose_x"] = np.nan
    raw.to_csv(source, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="non-finite"):
        verify_real_delivery(root, source, plan_path)

    root, source, plan_path, native_path = _minimal_delivery(tmp_path / "native-column")
    native = pd.read_csv(native_path).drop(columns=["loc_ready"])
    native.to_csv(native_path, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="missing native columns"):
        verify_real_delivery(root, source, plan_path)

    root, source, plan_path, native_path = _minimal_delivery(tmp_path / "native-ready")
    native = pd.read_csv(native_path)
    native.loc[0, "loc_ready"] = False
    native.to_csv(native_path, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="reference was not ready"):
        verify_real_delivery(root, source, plan_path)

    root, source, plan_path, native_path = _minimal_delivery(tmp_path / "native-count")
    native = pd.read_csv(native_path).iloc[:-1]
    native.to_csv(native_path, index=False)
    _write_delivery_checksums(root)
    with pytest.raises(ValueError, match="row count mismatch"):
        verify_real_delivery(root, source, plan_path)


def test_real_delivery_reports_protocol_limitations(tmp_path) -> None:
    root, source, plan_path, _ = _minimal_delivery(tmp_path)
    plan = pd.read_csv(plan_path)
    plan["sample_rate_hz"] = 100.0
    plan.to_csv(plan_path, index=False)
    sessions_path = root / "metadata/session_metadata.csv"
    sessions = pd.read_csv(sessions_path)
    sessions["rosbag_recorded"] = "no"
    sessions["firmware_version"] = "unknown"
    sessions.to_csv(sessions_path, index=False)
    _write_delivery_checksums(root)
    with (root / "checksums.sha256").open("a", encoding="utf-8") as stream:
        stream.write(f"{'0' * 64}  ./checksums.sha256\n")

    verification = verify_real_delivery(root, source, plan_path)

    assert len(verification["limitations"]) == 4
    assert verification["checksum_self_entries_ignored"] == 1
    assert verification["metadata_unknown_cells"] == 1
