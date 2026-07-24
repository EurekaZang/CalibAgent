from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from calibagent.cli import audit_readiness as cli
from calibagent.eval.readiness import AuditCheck, PublicationReadinessReport


def test_audit_cli_prints_and_writes_ready_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = PublicationReadinessReport(
        "1.0",
        "GO",
        (AuditCheck("test", True, "evidence"),),
    )
    output = tmp_path / "report.json"
    monkeypatch.setattr(cli, "audit_publication_readiness", lambda workspace: report)
    monkeypatch.setattr(
        sys,
        "argv",
        ["calibagent-audit", "--workspace", str(tmp_path), "--output", str(output)],
    )

    cli.main()

    assert json.loads(capsys.readouterr().out)["verdict"] == "GO"
    assert json.loads(output.read_text(encoding="utf-8"))["checks"][0]["passed"] is True


def test_audit_cli_require_ready_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = PublicationReadinessReport(
        "1.0",
        "NO_GO",
        (AuditCheck("test", False, "missing"),),
    )
    monkeypatch.setattr(cli, "audit_publication_readiness", lambda workspace: report)
    monkeypatch.setattr(
        sys,
        "argv",
        ["calibagent-audit", "--workspace", str(tmp_path), "--require-ready"],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
