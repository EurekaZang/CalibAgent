from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from calibagent.eval.p4_benchmark import run_p4_suite


def test_p4_suite_meets_frozen_gates(tmp_path: Path) -> None:
    workspace = Path(__file__).resolve().parents[2]
    config_path = workspace / "configs/experiments/p4_safety_stop_main.yaml"
    config = config_path.read_text(encoding="utf-8").replace(
        "output_dir: outputs/p4_main",
        f"output_dir: {tmp_path.relative_to(workspace) if tmp_path.is_relative_to(workspace) else tmp_path}",
    )
    local_config = tmp_path / "p4.yaml"
    local_config.write_text(config, encoding="utf-8")
    summary = run_p4_suite(local_config, workspace)
    assert summary["verdict"] == "GO"
    assert summary["stop_runs"] == 60
    assert summary["premature_stop_rate"] < 0.05
    assert summary["median_extra_trials"] <= 3
    assert summary["hazard_rejection_rate"] == 1.0
    assert summary["safe_false_rejection_rate"] == 0.0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "P4"
    faults = pd.read_csv(tmp_path / "fault_injection.csv")
    assert faults[faults["hazard"]]["expected_reason_present"].all()
