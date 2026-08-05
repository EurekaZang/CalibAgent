#!/usr/bin/env python3
"""Promote compact, hash-bound recovery-selector evidence into Git."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs/p6_recovery_selector_ablation_v2"
DESTINATION = ROOT / "evidence/recovery_selector_ablation"
SCENARIO_FILES = (
    "monitor_metrics.csv",
    "paired_recovery_effects.csv",
    "per_seed_metrics.csv",
    "recovery_curve.csv",
    "recovery_metrics.csv",
    "summary.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(relative: Path) -> None:
    source = SOURCE / relative
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"missing source artifact: {source}")
    target = DESTINATION / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> None:
    if DESTINATION.exists():
        raise FileExistsError(f"refusing to overwrite {DESTINATION}")
    summary = json.loads((SOURCE / "summary.json").read_text(encoding="utf-8"))
    if summary.get("verdict") != "GO":
        raise RuntimeError("recovery-selector experiment did not produce GO")

    for name in ("resolved_config.json", "summary.json"):
        _copy(Path(name))
    source_manifest = SOURCE / "manifest.json"
    _copy(Path("manifest.json"))
    (DESTINATION / "source_manifest.json").write_text(
        (DESTINATION / "manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (DESTINATION / "manifest.json").unlink()

    scenario_root = SOURCE / "scenarios"
    scenario_names = sorted(path.name for path in scenario_root.iterdir() if path.is_dir())
    if len(scenario_names) != 4:
        raise RuntimeError(f"expected four scenarios, found {len(scenario_names)}")
    for scenario in scenario_names:
        for name in SCENARIO_FILES:
            _copy(Path("scenarios") / scenario / name)

    (DESTINATION / "README.md").write_text(
        "# Recovery-selector ablation evidence\n\n"
        "This compact evidence tree compares the task-weighted recovery selector "
        "with no-task IVR, D-optimal, LHS, and random recovery under four held-out "
        "Isaac Lab shifts and 30 paired seeds per shift. `summary.json` contains the "
        "paired effect estimates and publication gates; each scenario directory "
        "contains the per-seed records and curves required to recompute them.\n\n"
        "Full-resolution pose trajectories remain in the supplemental output archive. "
        "`source_manifest.json` records their SHA-256 hashes and binds the compact "
        "records to the pinned simulator run. The experiment verdict is GO and no "
        "serious safety event occurred.\n",
        encoding="utf-8",
    )

    artifacts: dict[str, dict[str, object]] = {}
    for path in sorted(DESTINATION.rglob("*")):
        if path.is_file() and path.name != "compact_manifest.json":
            relative = path.relative_to(DESTINATION).as_posix()
            artifacts[relative] = {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
    compact_manifest = {
        "schema_version": "1.0",
        "experiment": "recovery_selector_ablation",
        "source_output_manifest_sha256": _sha256(source_manifest),
        "source_git_commit": json.loads(source_manifest.read_text(encoding="utf-8"))[
            "git_commit"
        ],
        "verdict": "GO",
        "artifacts": artifacts,
    }
    (DESTINATION / "compact_manifest.json").write_text(
        json.dumps(compact_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
