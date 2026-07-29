"""Governance checks for the native Isaac Sim images embedded in the README."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        assert image_path.is_file()
        assert _sha256(image_path) == frame["sha256"]
        with image_path.open("rb") as stream:
            header = stream.read(24)
        assert header[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", header[16:24])
        assert [width, height] == frame["resolution"]


def test_bilingual_readmes_embed_native_isaac_sim_frames() -> None:
    required_images = {
        "docs/assets/readme/p7_isaac_sim_overview.png",
        "docs/assets/readme/p5_isaac_sim_closeup.png",
        "docs/assets/readme/p7_isaac_sim_robot_view.png",
    }
    for readme_name in ("README.md", "README_zh-CN.md"):
        readme = (WORKSPACE / readme_name).read_text(encoding="utf-8")
        assert required_images <= {image for image in required_images if image in readme}
