"""Freeze compact, hash-bound strong-confirmatory evidence trees."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from calibagent.eval.real_replay import file_sha256
from calibagent.eval.strong_readiness import (
    build_p6_trace_receipt,
    build_p7_trace_receipt,
)


def _freeze_phase(
    workspace: Path,
    *,
    phase: str,
    raw_section: dict[str, Any],
    compact_section: dict[str, Any],
    receipt_builder: Callable[[Path, dict[str, Any]], dict[str, Any]],
) -> None:
    source = workspace / str(raw_section["evidence"])
    destination = workspace / str(compact_section["evidence"])
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite evidence tree: {destination}")
    source_manifest_path = workspace / str(raw_section["manifest"])
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    receipt = receipt_builder(workspace, raw_section)
    if not bool(receipt["all_passed"]):
        raise RuntimeError(f"{phase} full-resolution trace audit failed")

    destination.mkdir(parents=True)
    for record in source_manifest["artifacts"].values():
        relative = Path(str(record["path"]))
        if relative.name in {"pose_trace.csv.gz", "nav_trace.csv.gz"}:
            continue
        source_path = source / relative
        if file_sha256(source_path) != record["sha256"]:
            raise RuntimeError(f"source artifact changed: {source_path}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)

    (destination / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "trace_audit.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "README.md").write_text(
        (
            f"# {phase} strong-confirmatory evidence\n\n"
            "This versioned tree contains every non-trajectory artifact from the "
            "frozen run. Full-resolution trajectories are intentionally kept in "
            "the supplemental output archive because they exceed practical Git "
            "size. `source_manifest.json` records the SHA-256 of every original "
            "artifact, including every trajectory. `trace_audit.json` records an "
            "independent finite/identity/uniqueness/safety scan of each trajectory "
            "and binds that scan to the same hashes.\n\n"
            "The compact tree is sufficient to recompute every registered endpoint "
            "from per-seed records. Use `calibagent-audit-strong --raw` when the "
            "full supplemental output trees are mounted to re-hash and rescan them.\n"
        ),
        encoding="utf-8",
    )
    artifacts: dict[str, dict[str, str]] = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative_name = path.relative_to(destination).as_posix()
            artifacts[relative_name] = {
                "path": relative_name,
                "sha256": file_sha256(path),
            }
    compact_manifest = {
        **{
            key: value
            for key, value in source_manifest.items()
            if key != "artifacts"
        },
        "schema_version": "1.0",
        "packaging": "compact_nontrajectory_with_hash_bound_trace_audit",
        "source_output_manifest_sha256": file_sha256(source_manifest_path),
        "artifacts": artifacts,
    }
    (destination / "manifest.json").write_text(
        json.dumps(compact_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    workspace = Path.cwd().resolve()
    criteria_path = workspace / "configs/audit/icra_p6_p7_strong.yaml"
    criteria = yaml.safe_load(criteria_path.read_text(encoding="utf-8"))
    if not isinstance(criteria, dict):
        raise ValueError(f"expected a mapping in {criteria_path}")
    _freeze_phase(
        workspace,
        phase="P6",
        raw_section=dict(criteria["p6_raw"]),
        compact_section=dict(criteria["p6"]),
        receipt_builder=build_p6_trace_receipt,
    )
    _freeze_phase(
        workspace,
        phase="P7",
        raw_section=dict(criteria["p7_raw"]),
        compact_section=dict(criteria["p7"]),
        receipt_builder=build_p7_trace_receipt,
    )


if __name__ == "__main__":
    main()
