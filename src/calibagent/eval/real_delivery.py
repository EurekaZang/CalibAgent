"""Verification of traceable real-robot delivery packages."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_DELIVERY_FILES = (
    "README.md",
    "checksums.sha256",
    "calibration/calibration_notes.md",
    "calibration/reference_to_base_extrinsic.yaml",
    "capture_plan/plan.csv",
    "metadata/coordinate_frames.md",
    "metadata/session_metadata.csv",
    "metadata/time_sync.md",
    "metadata/trial_ledger.csv",
    "exported/go2_raw_trials.csv",
)
RAW_ID_COLUMNS = ("session_id", "trial_id")
RAW_NUMERIC_COLUMNS = (
    "timestamp",
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "pose_x",
    "pose_y",
    "pose_yaw",
)
NATIVE_REQUIRED_COLUMNS = {
    "timestamp",
    "phase",
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "pose_x",
    "pose_y",
    "pose_yaw",
    "loc_ready",
    "frame_id",
    "child_frame_id",
}
LEDGER_REQUIRED_COLUMNS = {
    "session_id",
    "trial_id",
    "attempt_id",
    "status",
    "exclusion_reason",
    "selected_for_csv",
    "reference_valid",
}
ALLOWED_ATTEMPT_STATUS = {
    "complete",
    "pre_measure_abort",
    "technical_abort",
    "safety_abort",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _truthy(values: pd.Series) -> pd.Series:
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _trial_keys(frame: pd.DataFrame) -> set[tuple[str, str]]:
    return {
        (str(session), str(int(trial)))
        for session, trial in frame[list(RAW_ID_COLUMNS)].itertuples(index=False, name=None)
    }


def _verify_checksum_manifest(root: Path) -> tuple[int, int]:
    manifest = root / "checksums.sha256"
    listed: set[str] = set()
    verified = 0
    ignored_self_entries = 0
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"invalid checksum line {line_number}")
        expected, raw_name = parts
        raw_name = raw_name.strip().lstrip("*")
        relative = PurePosixPath(raw_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe checksum path {raw_name!r}")
        normalized = relative.as_posix().removeprefix("./")
        if normalized == "checksums.sha256":
            ignored_self_entries += 1
            continue
        path = root / normalized
        if not path.is_file():
            raise ValueError(f"checksum target is missing: {normalized}")
        if _sha256(path) != expected:
            raise ValueError(f"checksum mismatch: {normalized}")
        listed.add(normalized)
        verified += 1

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    unlisted = sorted(actual - listed)
    if unlisted:
        raise ValueError(f"delivery files missing from checksum manifest: {unlisted}")
    return verified, ignored_self_entries


def verify_real_delivery(
    delivery_root: Path,
    source_csv: Path,
    capture_plan: Path,
) -> dict[str, Any]:
    """Verify final CSV provenance back to selected native attempt rows."""

    root = delivery_root.resolve()
    source = source_csv.resolve()
    plan_path = capture_plan.resolve()
    for relative in REQUIRED_DELIVERY_FILES:
        if not (root / relative).is_file():
            raise ValueError(f"real delivery is missing {relative}")

    delivered_source = (root / "exported/go2_raw_trials.csv").resolve()
    if _sha256(delivered_source) != _sha256(source):
        raise ValueError("source CSV does not match delivery exported/go2_raw_trials.csv")
    delivered_plan = root / "capture_plan/plan.csv"
    if _sha256(delivered_plan) != _sha256(plan_path):
        raise ValueError("capture plan does not match the delivery plan")

    checksum_files, ignored_self_entries = _verify_checksum_manifest(root)
    raw = pd.read_csv(delivered_source)
    plan = pd.read_csv(delivered_plan)
    ledger = pd.read_csv(root / "metadata/trial_ledger.csv")
    sessions = pd.read_csv(root / "metadata/session_metadata.csv")
    missing_ledger = LEDGER_REQUIRED_COLUMNS - set(ledger.columns)
    if missing_ledger:
        raise ValueError(f"trial ledger is missing columns: {sorted(missing_ledger)}")
    if not set(ledger["status"].astype(str)) <= ALLOWED_ATTEMPT_STATUS:
        raise ValueError("trial ledger contains an unsupported status")

    selected = ledger[_truthy(ledger["selected_for_csv"])].copy()
    unselected = ledger[~_truthy(ledger["selected_for_csv"])].copy()
    if selected.duplicated(list(RAW_ID_COLUMNS)).any():
        raise ValueError("multiple attempts were selected for one trial")
    if _trial_keys(selected) != _trial_keys(raw):
        raise ValueError("selected ledger trials do not match final CSV trials")
    if not unselected.empty:
        missing_reason = unselected["exclusion_reason"].fillna("").astype(str).str.strip().eq("")
        if missing_reason.any():
            raise ValueError("an unselected attempt has no exclusion reason")

    numeric = raw[list(RAW_NUMERIC_COLUMNS)].to_numpy(dtype=np.float64)
    if not np.all(np.isfinite(numeric)):
        raise ValueError("final CSV contains non-finite values")
    for _, group in raw.groupby(list(RAW_ID_COLUMNS), sort=False):
        timestamps = group["timestamp"].to_numpy(dtype=np.float64)
        if len(timestamps) < 2 or np.any(np.diff(timestamps) <= 0.0):
            raise ValueError("final CSV contains a non-monotonic trial")
        for column in ("terrain_id", "payload_kg", "battery_ratio", "gait_id"):
            if column in group and group[column].nunique(dropna=False) != 1:
                raise ValueError(f"{column} changes within a trial")

    frames: set[tuple[str, str]] = set()
    traced = 0
    for row in selected.itertuples(index=False):
        session_id = str(row.session_id)
        trial_id = int(float(str(row.trial_id)))
        attempt_id = int(float(str(row.attempt_id)))
        native_path = (
            root
            / "raw"
            / session_id
            / "reference_native"
            / f"trial_{trial_id:02d}_attempt_{attempt_id:02d}.csv"
        )
        if not native_path.is_file():
            raise ValueError(f"selected native attempt is missing: {native_path.relative_to(root)}")
        native = pd.read_csv(native_path)
        missing_native = NATIVE_REQUIRED_COLUMNS - set(native.columns)
        if missing_native:
            raise ValueError(
                f"{native_path.name} is missing native columns: {sorted(missing_native)}"
            )
        measure = native[native["phase"].astype(str) == "measure"]
        final = raw[
            (raw["session_id"].astype(str) == session_id)
            & (raw["trial_id"].astype(int) == trial_id)
        ]
        if len(measure) != len(final):
            raise ValueError(f"native/final row count mismatch for {session_id}/{trial_id}")
        if not np.allclose(
            measure[list(RAW_NUMERIC_COLUMNS)].to_numpy(dtype=np.float64),
            final[list(RAW_NUMERIC_COLUMNS)].to_numpy(dtype=np.float64),
            rtol=0.0,
            atol=5e-10,
        ):
            raise ValueError(f"native/final values differ for {session_id}/{trial_id}")
        if not _truthy(measure["loc_ready"]).all():
            raise ValueError(f"reference was not ready during {session_id}/{trial_id}")
        frames.update(
            (str(parent), str(child))
            for parent, child in measure[["frame_id", "child_frame_id"]].itertuples(
                index=False, name=None
            )
        )
        traced += 1

    if traced != len(selected):
        raise ValueError("not all selected trials were traced to native data")
    session_ids = sorted(set(raw["session_id"].astype(str)))
    if set(session_ids) - set(sessions["session_id"].astype(str)):
        raise ValueError("session metadata does not cover all final CSV sessions")

    trial_stats: list[dict[str, float]] = []
    for _, group in raw.groupby(list(RAW_ID_COLUMNS), sort=False):
        timestamps = group["timestamp"].to_numpy(dtype=np.float64)
        delta = np.diff(timestamps)
        trial_stats.append(
            {
                "samples": float(len(group)),
                "duration_s": float(timestamps[-1] - timestamps[0]),
                "median_hz": float(1.0 / np.median(delta)),
                "max_gap_s": float(np.max(delta)),
            }
        )
    stats = pd.DataFrame(trial_stats)
    planned_hz = float(plan["sample_rate_hz"].median())
    observed_hz = float(stats["median_hz"].median())
    limitations: list[str] = []
    if observed_hz < 0.9 * planned_hz:
        limitations.append(
            f"reference sampling median {observed_hz:.3f} Hz is below "
            f"the frozen {planned_hz:.3f} Hz target"
        )
    if ignored_self_entries:
        limitations.append(
            "checksums.sha256 contains an unverifiable self-entry; all other files verified"
        )
    if "rosbag_recorded" in sessions and not _truthy(sessions["rosbag_recorded"]).all():
        limitations.append("full rosbag was not recorded")
    unknown_cells = int(
        sessions.astype(str).apply(lambda column: column.str.strip().str.lower().eq("unknown")).sum().sum()
    )
    if unknown_cells:
        limitations.append(f"session metadata contains {unknown_cells} unknown values")

    return {
        "schema_version": "1.0",
        "verified": True,
        "source_csv_sha256": _sha256(delivered_source),
        "capture_plan_sha256": _sha256(delivered_plan),
        "checksum_files_verified": checksum_files,
        "checksum_self_entries_ignored": ignored_self_entries,
        "ledger_attempts": len(ledger),
        "selected_trials": len(selected),
        "unselected_attempts": len(unselected),
        "native_trials_traced": traced,
        "native_traceability_ratio": float(traced / len(selected)) if len(selected) else 0.0,
        "sessions": session_ids,
        "reference_frames": [list(frame) for frame in sorted(frames)],
        "sample_count_min": int(stats["samples"].min()),
        "sample_count_median": float(stats["samples"].median()),
        "duration_s_min": float(stats["duration_s"].min()),
        "duration_s_median": float(stats["duration_s"].median()),
        "observed_median_hz": observed_hz,
        "planned_sample_rate_hz": planned_hz,
        "max_timestamp_gap_s": float(stats["max_gap_s"].max()),
        "metadata_unknown_cells": unknown_cells,
        "limitations": limitations,
    }
