from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from calibagent.cli.freeze_strong_evidence import _freeze_phase
from calibagent.eval.real_replay import file_sha256


def test_freeze_phase_copies_nontraces_and_binds_receipt(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "metrics.csv").write_text("seed,value\n1,2\n", encoding="utf-8")
    (source / "nav_trace.csv.gz").write_bytes(b"trace")
    source_manifest = {
        "schema_version": "1.0",
        "phase": "P7",
        "backend": "test",
        "config_path": "config.yaml",
        "config_sha256": "frozen",
        "git_commit": "commit",
        "runtime": {},
        "checkpoints": {},
        "artifacts": {
            "metrics.csv": {
                "path": "metrics.csv",
                "sha256": file_sha256(source / "metrics.csv"),
            },
            "nav_trace.csv.gz": {
                "path": "nav_trace.csv.gz",
                "sha256": file_sha256(source / "nav_trace.csv.gz"),
            },
        },
    }
    (source / "manifest.json").write_text(
        json.dumps(source_manifest),
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "1.0",
        "phase": "P7",
        "all_passed": True,
        "traces": {},
    }

    def receipt_builder(
        workspace: Path,
        section: dict[str, Any],
    ) -> dict[str, Any]:
        assert workspace == tmp_path
        assert section["evidence"] == "raw"
        return receipt

    _freeze_phase(
        tmp_path,
        phase="P7",
        raw_section={"evidence": "raw", "manifest": "raw/manifest.json"},
        compact_section={"evidence": "compact"},
        receipt_builder=receipt_builder,
    )

    compact = tmp_path / "compact"
    manifest = json.loads((compact / "manifest.json").read_text(encoding="utf-8"))
    assert (compact / "metrics.csv").is_file()
    assert not (compact / "nav_trace.csv.gz").exists()
    assert json.loads((compact / "trace_audit.json").read_text(encoding="utf-8")) == receipt
    assert manifest["packaging"] == "compact_nontrajectory_with_hash_bound_trace_audit"
    assert set(manifest["artifacts"]) == {
        "README.md",
        "metrics.csv",
        "source_manifest.json",
        "trace_audit.json",
    }

    with pytest.raises(FileExistsError):
        _freeze_phase(
            tmp_path,
            phase="P7",
            raw_section={"evidence": "raw", "manifest": "raw/manifest.json"},
            compact_section={"evidence": "compact"},
            receipt_builder=receipt_builder,
        )


def test_freeze_phase_rejects_failed_trace_audit(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({"artifacts": {}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="trace audit failed"):
        _freeze_phase(
            tmp_path,
            phase="P6",
            raw_section={"evidence": "raw", "manifest": "raw/manifest.json"},
            compact_section={"evidence": "compact"},
            receipt_builder=lambda workspace, section: {"all_passed": False},
        )
