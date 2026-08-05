#!/usr/bin/env python3
"""Promote the compact task-distribution mismatch analysis into Git."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs/task_distribution_mismatch"
DESTINATION = ROOT / "evidence/task_distribution_mismatch"
FILES = (
    "comparisons.csv",
    "manifest.json",
    "per_condition.csv",
    "resolved_config.json",
    "summary.json",
    "task_ivr_mismatch_ratios.csv",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if DESTINATION.exists():
        raise FileExistsError(f"refusing to overwrite {DESTINATION}")
    summary = json.loads((SOURCE / "summary.json").read_text(encoding="utf-8"))
    if not all(summary["checks"][key] for key in ("finite_and_complete", "lhs_robustness")):
        raise RuntimeError("task-mismatch analysis is incomplete")
    DESTINATION.mkdir(parents=True)
    for name in FILES:
        source = SOURCE / name
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError(source)
        shutil.copy2(source, DESTINATION / name)
    (DESTINATION / "README.md").write_text(
        "# Task-distribution mismatch sensitivity\n\n"
        "This evidence tree re-evaluates frozen synthetic acquisitions on an "
        "independent 1,024-command grid under the declared deployment measure, "
        "three within-family mixture reweightings, and a broad uniform command "
        "measure. Families are averaged within each of 20 paired seeds before "
        "inference. No acquisition command is reselected.\n\n"
        "Task IVR retains positive paired advantages over LHS and no-task IVR "
        "under the three navigation-family reweightings. The broad-uniform shift "
        "reverses the ordering and exceeds the frozen two-fold RMSE-inflation gate; "
        "the recorded verdict is therefore NO_GO. This negative control identifies "
        "the method's intended boundary: the task measure must be revised when the "
        "deployment support expands to the full safe command envelope.\n",
        encoding="utf-8",
    )
    artifacts = {}
    for path in sorted(DESTINATION.iterdir()):
        if path.is_file() and path.name != "compact_manifest.json":
            artifacts[path.name] = {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
    compact = {
        "schema_version": "1.0",
        "analysis": "task_distribution_mismatch",
        "verdict": summary["verdict"],
        "artifacts": artifacts,
    }
    (DESTINATION / "compact_manifest.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
