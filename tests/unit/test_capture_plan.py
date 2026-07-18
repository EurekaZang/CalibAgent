from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from calibagent.eval.capture_plan import (
    CapturePlanConfig,
    generate_capture_plan,
    write_capture_plan,
)

WORKSPACE = Path(__file__).resolve().parents[2]


def test_frozen_capture_plan_is_balanced_safe_and_deterministic(tmp_path) -> None:
    config = CapturePlanConfig.from_yaml(WORKSPACE / "configs/experiments/p1_go2_capture.yaml")
    first = generate_capture_plan(config)
    second = generate_capture_plan(config)
    assert first.equals(second)
    assert len(first) == 183
    assert set(first.groupby("session_id").size()) == {61}
    commands = first[["cmd_vx", "cmd_vy", "cmd_wz"]].to_numpy()
    assert np.all(commands.min(axis=0) <= [-0.1, -0.1, -0.1])
    assert np.all(commands.max(axis=0) >= [0.1, 0.1, 0.1])
    assert np.all(np.linalg.norm(commands[:, :2], axis=1) <= config.max_linear_norm)
    assert set(first["design_source"]) == {"anchor", "sentinel", "lhs"}
    output = tmp_path / "plan.csv"
    manifest = write_capture_plan(config, output)
    assert manifest["planned_trials"] == 183
    assert output.with_suffix(".manifest.json").is_file()


def test_capture_plan_rejects_mismatched_session_seeds() -> None:
    config = CapturePlanConfig.from_yaml(WORKSPACE / "configs/experiments/p1_go2_capture.yaml")
    try:
        generate_capture_plan(replace(config, session_seeds=(1,)))
    except ValueError as error:
        assert "equal length" in str(error)
    else:
        raise AssertionError("mismatched session design was accepted")
