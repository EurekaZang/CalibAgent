#!/usr/bin/env python3
"""Audit the Isaac Sim visual evidence included in the manuscript.

Direct scene PNGs must be declared by companion capture records, match their
registered hashes and resolutions, come from declared experimental seeds, and
be used only once.  Data-driven P5/P6 PDFs must trace to the registered capture
records and frozen summaries listed in the scientific-figure manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets" / "readme" / "isaac_sim"
MAIN_TEX = ROOT / "paper" / "main.tex"
STAGED_FIGURES = ROOT / "paper" / "figures"
PROVENANCE = ROOT / "evidence" / "paper_figure_provenance"
MANIFEST = PROVENANCE / "simulation_figure_manifest.json"
SCIENTIFIC_MANIFEST = PROVENANCE / "simulation_scientific_figure_manifest.json"

CAPTURES = {
    "p7_replicate_s_bend_capture.json": [("p7_replicate_s_bend_overview.png", "map_s_bend.png")],
    "p7_replicate_offset_slalom_capture.json": [
        ("p7_replicate_offset_slalom_overview.png", "map_offset_slalom.png")
    ],
    "p7_replicate_narrow_lane_capture.json": [
        ("p7_replicate_narrow_lane_overview.png", "map_narrow_lane.png")
    ],
    "p7_replicate_double_chicane_capture.json": [
        ("p7_replicate_double_chicane_overview.png", "map_double_chicane.png")
    ],
    "p7_replicate_weighted_arc_capture.json": [
        ("p7_replicate_weighted_arc_overview.png", "map_weighted_arc.png")
    ],
    "p7_replicate_extended_lane_capture.json": [
        ("p7_replicate_extended_lane_overview.png", "map_extended_lane.png")
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def png_resolution(path: Path) -> list[int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Not a valid PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    return [width, height]


def manuscript_sim_assets() -> list[str]:
    text = MAIN_TEX.read_text(encoding="utf-8")
    pattern = re.compile(r"\\includegraphics(?:\[[^]]*\])?\{figures/(map_[^}]+\.png)\}")
    return pattern.findall(text)


def main() -> None:
    expected_assets = [staged for assets in CAPTURES.values() for _, staged in assets]
    used_assets = manuscript_sim_assets()
    if sorted(used_assets) != sorted(expected_assets):
        missing = sorted(set(expected_assets) - set(used_assets))
        extra = sorted(set(used_assets) - set(expected_assets))
        raise SystemExit(f"Manuscript asset mismatch; missing={missing}, extra={extra}")
    if len(used_assets) != len(set(used_assets)):
        raise SystemExit("A simulation image is included more than once in main.tex")

    scientific = json.loads(SCIENTIFIC_MANIFEST.read_text(encoding="utf-8"))
    for source in scientific["sources"]:
        source_path = ROOT / source["path"]
        if sha256(source_path) != source["sha256"]:
            raise SystemExit(f"Scientific-figure source hash mismatch: {source['path']}")
    for stem in scientific["figures"]:
        for suffix in (".pdf", ".png"):
            figure_path = ROOT / "paper" / "figures" / f"{stem}{suffix}"
            if not figure_path.is_file():
                raise SystemExit(f"Missing data-driven simulation figure: {figure_path}")

    entries: list[dict[str, object]] = []
    seen_hashes: dict[str, str] = {}
    for capture_name, asset_names in CAPTURES.items():
        capture_path = ASSETS / capture_name
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        if capture.get("quantitative_evidence") is not False:
            raise SystemExit(f"Unexpected evidence designation: {capture_name}")
        if capture.get("declared_seed_membership_verified") is not True:
            raise SystemExit(f"Unverified display seed: {capture_name}")
        declared_frames = {frame["path"]: frame for frame in capture.get("frames", [])}

        for asset_name, staged_name in asset_names:
            if asset_name not in declared_frames:
                raise SystemExit(f"{asset_name} is not declared by {capture_name}")
            asset_path = ASSETS / asset_name
            frame = declared_frames[asset_name]
            actual_hash = sha256(asset_path)
            if actual_hash != frame["sha256"]:
                raise SystemExit(f"Hash mismatch: {asset_name}")
            actual_resolution = png_resolution(asset_path)
            if actual_resolution != frame["resolution"]:
                raise SystemExit(f"Resolution mismatch: {asset_name}")
            if actual_hash in seen_hashes:
                raise SystemExit(
                    f"Duplicate image content: {asset_name} and {seen_hashes[actual_hash]}"
                )
            seen_hashes[actual_hash] = asset_name
            staged_path = STAGED_FIGURES / staged_name
            if sha256(staged_path) != actual_hash:
                raise SystemExit(f"Staged manuscript image differs from source: {staged_name}")
            entries.append(
                {
                    "asset": str(asset_path.relative_to(ROOT)),
                    "staged_manuscript_asset": str(staged_path.relative_to(ROOT)),
                    "asset_sha256": actual_hash,
                    "capture_record": str(capture_path.relative_to(ROOT)),
                    "capture_record_sha256": sha256(capture_path),
                    "artifact_type": capture["artifact_type"],
                    "source_phase": capture["source_phase"],
                    "scenario_id": capture["scenario_id"],
                    "method": capture.get("method"),
                    "selected_seed": capture["selected_seed"],
                    "resolution": actual_resolution,
                    "quantitative_evidence": False,
                    "scenario_config": capture["scenario_config"],
                    "scenario_config_sha256": capture["scenario_config_sha256"],
                    "runtime_manifest": capture["runtime_manifest"],
                }
            )

    output = {
        "schema_version": 1,
        "purpose": "Provenance and uniqueness audit for Isaac Sim evidence in paper/main.tex",
        "interpretation": (
            "These images document registered simulator scenes and response replays. "
            "They are qualitative and do not replace the frozen multi-seed statistics."
        ),
        "asset_count": len(entries),
        "all_asset_hashes_unique": True,
        "all_declared_seed_memberships_verified": True,
        "scientific_figure_manifest": str(SCIENTIFIC_MANIFEST.relative_to(ROOT)),
        "scientific_figure_manifest_sha256": sha256(SCIENTIFIC_MANIFEST),
        "scientific_figure_source_count": len(scientific["sources"]),
        "entries": entries,
    }
    PROVENANCE.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: audited {len(entries)} unique scene images and "
        f"{len(scientific['figures'])} data-driven simulation figures"
    )
    print(f"Manifest: {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
