from __future__ import annotations

import json
from pathlib import Path

from calibagent.eval.readiness import audit_publication_readiness

WORKSPACE = Path(__file__).resolve().parents[2]


def test_current_publication_verdict_is_go_and_claims_match() -> None:
    report = audit_publication_readiness(WORKSPACE)
    assert report.verdict == "GO"
    assert all(check.passed for check in report.checks)
    readme = (WORKSPACE / "README.md").read_text(encoding="utf-8").lower()
    assert "icra readiness: go" in readme
    assert "does **not** claim that" in readme


def test_readiness_report_is_json_serializable() -> None:
    report = audit_publication_readiness(WORKSPACE)
    assert '"verdict": "GO"' in report.to_json()


def test_historical_audit_is_a_valid_immutable_snapshot() -> None:
    frozen = json.loads(
        (WORKSPACE / "reports/icra_readiness_2026-07-18.json").read_text(encoding="utf-8")
    )
    assert frozen["schema_version"] == "1.0"
    assert frozen["verdict"] == "NO_GO"
    assert {item["check_id"] for item in frozen["checks"]} >= {
        "p1_replay_measurement_vertical_slice",
        "p2_synthetic_noise_contract",
    }


def test_latest_audit_snapshot_matches_live_gate() -> None:
    live = audit_publication_readiness(WORKSPACE)
    latest = json.loads(
        (WORKSPACE / "reports/icra_readiness_latest.json").read_text(encoding="utf-8")
    )
    assert latest["verdict"] == live.verdict
    assert {item["check_id"]: item["passed"] for item in latest["checks"]} == {
        item.check_id: item.passed for item in live.checks
    }
