from __future__ import annotations

import json

import numpy as np
import pandas as pd

from calibagent.eval.readiness import _real_data_checks
from calibagent.eval.real_replay import build_real_replay_evidence, process_raw_trials


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
