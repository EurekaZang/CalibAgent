"""Reproducible run identity and configuration hashing."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from calibagent.interfaces.types import RunManifest


def canonical_config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "UNVERSIONED_WORKTREE"


def build_manifest(
    config: dict[str, Any], seeds: dict[str, int], backend: str, model_id: str, planner_id: str
) -> RunManifest:
    config_hash = canonical_config_hash(config)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return RunManifest(
        run_id=f"{timestamp}_seed{seeds.get('global', 0):04d}_{planner_id}",
        git_commit=current_git_commit(),
        config_hash=config_hash,
        random_seeds=seeds,
        backend=backend,
        model_id=model_id,
        planner_id=planner_id,
        artifacts={},
    )


def write_resolved_config(config: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
