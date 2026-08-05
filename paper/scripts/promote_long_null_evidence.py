#!/usr/bin/env python3
"""Promote compact, hash-bound stationary-monitor evidence into Git."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from calibagent.eval.real_replay import file_sha256

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs" / "long_null_signature_final_030"
DESTINATION = ROOT / "evidence" / "long_null_signature_final_030"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON mapping: {path}")
    return payload


def _verify_source() -> dict[str, Any]:
    manifest = _load(SOURCE / "manifest.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("source manifest has no artifacts")
    root = SOURCE.resolve()
    for record in artifacts.values():
        if not isinstance(record, dict):
            raise ValueError("invalid source artifact record")
        path = (SOURCE / str(record["path"])).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"source artifact escapes output tree: {path}")
        if file_sha256(path) != str(record["sha256"]):
            raise RuntimeError(f"source artifact hash mismatch: {path}")
    return manifest


def main() -> None:
    if DESTINATION.exists():
        raise FileExistsError(f"refusing to overwrite {DESTINATION}")
    summary = _load(SOURCE / "summary.json")
    if summary.get("verdict") != "GO" or summary.get("detector_mode") != "paired_signature":
        raise RuntimeError("stationary-monitor confirmation is not a paired-signature GO")
    source_manifest = _verify_source()

    DESTINATION.mkdir(parents=True)
    for filename in ("resolved_config.json", "summary.json"):
        shutil.copy2(SOURCE / filename, DESTINATION / filename)
    (DESTINATION / "per_sequence.csv").write_text(
        (SOURCE / "per_sequence.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (DESTINATION / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (DESTINATION / "README.md").write_text(
        "# Stationary paired-signature monitor evidence\n\n"
        "The final paired-signature detector was evaluated for 100 monitor trials "
        "after commissioning in each of 120 stationary sequences spanning four "
        "contexts (12,000 trials; 31,200 s aggregate command time). It produced "
        "zero sequence-level alarms, with an exact two-sided 95% upper bound of "
        "0.0303. Every monitor observation was valid and no serious safety event "
        "occurred. `per_sequence.csv` and `summary.json` contain the complete "
        "reported endpoints; `source_manifest.json` binds every source artifact, "
        "including omitted full-resolution traces.\n",
        encoding="utf-8",
    )
    artifacts: dict[str, dict[str, str]] = {}
    for path in sorted(DESTINATION.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(DESTINATION).as_posix()
            artifacts[relative] = {"path": relative, "sha256": file_sha256(path)}
    manifest = {
        "schema_version": "1.0",
        "experiment": "stationary_paired_signature_monitor",
        "source_output_manifest_sha256": file_sha256(SOURCE / "manifest.json"),
        "source_git_commit": source_manifest["git_commit"],
        "verdict": "GO",
        "artifacts": artifacts,
    }
    (DESTINATION / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
