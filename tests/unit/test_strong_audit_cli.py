from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from calibagent.cli import audit_strong_readiness as cli
from calibagent.eval.readiness import AuditCheck, PublicationReadinessReport


def test_strong_audit_cli_writes_raw_ready_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = PublicationReadinessReport(
        "1.0",
        "GO",
        (AuditCheck("strong", True, "evidence"),),
    )
    output = tmp_path / "strong.json"
    calls: list[tuple[Path, bool]] = []

    def audit(workspace: Path, *, raw: bool) -> PublicationReadinessReport:
        calls.append((workspace, raw))
        return report

    monkeypatch.setattr(cli, "audit_strong_readiness", audit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "calibagent-audit-strong",
            "--workspace",
            str(tmp_path),
            "--raw",
            "--output",
            str(output),
            "--require-ready",
        ],
    )

    cli.main()

    assert calls == [(tmp_path, True)]
    assert json.loads(capsys.readouterr().out)["verdict"] == "GO"
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == "GO"


def test_strong_audit_cli_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = PublicationReadinessReport(
        "1.0",
        "NO_GO",
        (AuditCheck("strong", False, "missing"),),
    )
    monkeypatch.setattr(
        cli,
        "audit_strong_readiness",
        lambda workspace, *, raw: report,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["calibagent-audit-strong", "--workspace", str(tmp_path), "--require-ready"],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
