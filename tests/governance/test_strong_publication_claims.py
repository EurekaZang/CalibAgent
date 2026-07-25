from __future__ import annotations

import json
from pathlib import Path

from calibagent.eval.strong_readiness import audit_strong_readiness

WORKSPACE = Path(__file__).resolve().parents[2]


def test_strong_p6_p7_verdict_is_go() -> None:
    report = audit_strong_readiness(WORKSPACE)
    assert report.verdict == "GO"
    assert len(report.checks) == 12
    assert all(check.passed for check in report.checks)


def test_failed_p7_confirmation_is_retained() -> None:
    summary = json.loads(
        (
            WORKSPACE / "evidence/p7_strong_confirmatory_failed/summary.json"
        ).read_text(encoding="utf-8")
    )
    report = audit_strong_readiness(WORKSPACE)
    retained = next(
        check
        for check in report.checks
        if check.check_id == "p7_failed_confirmation_retained"
    )
    assert summary["verdict"] == "NO_GO"
    assert retained.passed


def test_strong_snapshot_matches_live_audit() -> None:
    live = json.loads(audit_strong_readiness(WORKSPACE).to_json())
    frozen = json.loads(
        (
            WORKSPACE / "reports/p6_p7_strong_readiness_latest.json"
        ).read_text(encoding="utf-8")
    )
    assert frozen == live


def test_readme_keeps_simulator_claim_boundary() -> None:
    readme = (WORKSPACE / "README.md").read_text(encoding="utf-8").lower()
    assert "strong p6/p7 simulator readiness: go" in readme
    assert "first strong p7 confirmation failed" in readme
    assert "real-robot online active calibration remains p8" in readme
