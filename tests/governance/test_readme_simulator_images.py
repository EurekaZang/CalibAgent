"""Governance checks for the native Isaac Sim images embedded in the README."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
GALLERY_DIR = WORKSPACE / "docs" / "assets" / "readme" / "isaac_sim"

GALLERY_PREFIXES = (
    "p5_tier_a_affine",
    "p5_tier_a_deadzone",
    "p5_tier_b_friction_payload",
    "p5_tier_b_rough",
    "p6_main_friction_payload_gain_shift",
    "p6_main_gain_coupling_shift",
    "p6_main_mixed_context_shift",
    "p6_confirm_friction_payload",
    "p6_confirm_gain_recoupling",
    "p6_confirm_mixed_context",
    "p6_confirm_payload_com_only",
    "p7_main_narrow_corridor",
    "p7_main_open_field",
    "p7_main_slalom",
    "p7_replicate_double_chicane",
    "p7_replicate_extended_lane",
    "p7_replicate_narrow_lane",
    "p7_replicate_offset_slalom",
    "p7_replicate_s_bend",
    "p7_replicate_weighted_arc",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _gallery_identity(prefix: str) -> tuple[str, str, str, str]:
    if prefix.startswith("p5_"):
        scenario = prefix.removeprefix("p5_")
        manifest = "evidence/p5_main/manifest.json"
        config = f"evidence/p5_main/scenarios/{scenario}/launch_config.json"
        return "P5", scenario, manifest, config
    if prefix.startswith("p6_main_"):
        scenario = prefix.removeprefix("p6_main_")
        manifest = "evidence/p6_main/manifest.json"
        config = f"evidence/p6_main/scenarios/{scenario}/full/launch_config.json"
        return "P6", scenario, manifest, config
    if prefix.startswith("p6_confirm_"):
        scenario = prefix.removeprefix("p6_")
        manifest = "evidence/p6_strong_confirmatory/manifest.json"
        config = (
            f"evidence/p6_strong_confirmatory/scenarios/{scenario}/full/"
            "launch_config.json"
        )
        return "P6", scenario, manifest, config
    if prefix.startswith("p7_main_"):
        scenario = prefix.removeprefix("p7_main_")
        manifest = "evidence/p7_main/manifest.json"
        config = f"evidence/p7_main/maps/{scenario}/B8_full/launch_config.json"
        return "P7", scenario, manifest, config
    scenario = prefix.removeprefix("p7_")
    manifest = "evidence/p7_strong_confirmatory_v2/manifest.json"
    config = (
        f"evidence/p7_strong_confirmatory_v2/maps/{scenario}/B8_full/"
        "launch_config.json"
    )
    return "P7", scenario, manifest, config


def _assert_png_matches_record(image_path: Path, frame: dict[str, object]) -> None:
    assert image_path.is_file()
    assert _sha256(image_path) == frame["sha256"]
    with image_path.open("rb") as stream:
        header = stream.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", header[16:24])
    assert [width, height] == frame["resolution"] == [1280, 720]


@pytest.mark.parametrize(
    ("phase", "scenario_config"),
    [
        ("p5", "evidence/p5_main/scenarios/tier_a_affine/launch_config.json"),
        ("p7", "evidence/p7_main/maps/slalom/B8_full/launch_config.json"),
    ],
)
def test_native_isaac_sim_frames_are_hash_bound(
    phase: str,
    scenario_config: str,
) -> None:
    capture_path = WORKSPACE / "docs" / "assets" / "readme" / f"{phase}_isaac_sim_capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    evidence_manifest = json.loads(
        (WORKSPACE / f"evidence/{phase}_main/manifest.json").read_text(encoding="utf-8")
    )
    config_path = WORKSPACE / scenario_config
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert capture["artifact_type"] == "qualitative_isaac_sim_scene_capture"
    assert capture["quantitative_evidence"] is False
    assert capture["runtime"] == evidence_manifest["runtime"]
    assert capture["scenario_config"] == scenario_config
    assert capture["scenario_config_sha256"] == _sha256(config_path)
    assert capture["selected_seed"] in config["seeds"]
    assert capture["checkpoint"]["sha256"] == capture["checkpoint"]["registered_sha256"]

    for frame in capture["frames"]:
        image_path = capture_path.parent / frame["path"]
        _assert_png_matches_record(image_path, frame)


def test_gallery_contains_exactly_the_registered_twenty_configurations() -> None:
    captures = {
        path.name.removesuffix("_capture.json")
        for path in GALLERY_DIR.glob("*_capture.json")
    }
    assert captures == set(GALLERY_PREFIXES)


@pytest.mark.parametrize("prefix", GALLERY_PREFIXES)
def test_gallery_frames_are_bound_to_frozen_evidence(prefix: str) -> None:
    source_phase, scenario, manifest_path, config_path = _gallery_identity(prefix)
    capture_path = GALLERY_DIR / f"{prefix}_capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    manifest = json.loads((WORKSPACE / manifest_path).read_text(encoding="utf-8"))
    config_file = WORKSPACE / config_path
    config = json.loads(config_file.read_text(encoding="utf-8"))

    assert capture["artifact_type"] == "qualitative_isaac_sim_scene_capture"
    assert capture["quantitative_evidence"] is False
    assert capture["source_phase"] == source_phase
    assert capture["scenario_id"] == scenario
    assert capture["runtime_manifest"] == manifest_path
    assert capture["runtime"] == manifest["runtime"]
    assert capture["scenario_config"] == config_path
    assert capture["scenario_config_sha256"] == _sha256(config_file)
    assert capture["selected_seed"] in config["seeds"]
    assert capture["declared_seed_membership_verified"] is True
    assert capture["checkpoint"]["sha256"] == capture["checkpoint"]["registered_sha256"]
    assert len(capture["frames"]) == 2

    second_view = "robot_view" if source_phase == "P7" else "closeup"
    expected_frames = {f"{prefix}_overview.png", f"{prefix}_{second_view}.png"}
    assert {frame["path"] for frame in capture["frames"]} == expected_frames
    for frame in capture["frames"]:
        _assert_png_matches_record(GALLERY_DIR / frame["path"], frame)

    overlays = capture["capture_only_visualization_overlays"]
    if source_phase == "P7":
        assert overlays
        assert {overlay["kind"] for overlay in overlays} <= {
            "goal",
            "route_segment",
            "waypoint",
        }
    else:
        assert overlays == []


def test_bilingual_readmes_embed_native_isaac_sim_frames() -> None:
    hero_image = "docs/assets/readme/p7_isaac_sim_overview.png"
    gallery_images = {
        f"docs/assets/readme/isaac_sim/{prefix}_{view}.png"
        for prefix in GALLERY_PREFIXES
        for view in (
            ("overview", "robot_view")
            if prefix.startswith("p7_")
            else ("overview", "closeup")
        )
    }
    gallery_records = {
        f"docs/assets/readme/isaac_sim/{prefix}_capture.json"
        for prefix in GALLERY_PREFIXES
    }
    for readme_name in ("README.md", "README_zh-CN.md"):
        readme = (WORKSPACE / readme_name).read_text(encoding="utf-8")
        assert hero_image in readme
        assert gallery_images <= {image for image in gallery_images if image in readme}
        assert gallery_records <= {record for record in gallery_records if record in readme}
        assert "40" in readme
