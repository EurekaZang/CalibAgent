"""Governance checks for factual, non-duplicate Isaac Sim README images."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from calibagent.sim import make_distortion_parameters

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
    assert [width, height] == frame["resolution"]


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
    assert capture["stabilization"]["policy"] == (
        f"registered official Go2 {capture['checkpoint']['key']} checkpoint"
    )

    overlays = capture["capture_only_visualization_overlays"]
    if source_phase == "P7":
        assert capture["physical_context"]["physics"] == config["physics"]
        assert capture["artifact_type"] == "qualitative_isaac_sim_scene_capture"
        assert len(capture["frames"]) == 2
        expected_frames = {
            f"{prefix}_overview.png",
            f"{prefix}_robot_view.png",
        }
        assert {frame["path"] for frame in capture["frames"]} == expected_frames
        for frame in capture["frames"]:
            assert frame["resolution"] == [1280, 720]
            _assert_png_matches_record(GALLERY_DIR / frame["path"], frame)
        assert overlays
        assert {overlay["kind"] for overlay in overlays} <= {
            "goal",
            "route_segment",
            "waypoint",
        }
    else:
        if source_phase == "P5":
            context = capture["physical_context"]
            for key in (
                "terrain",
                "static_friction",
                "dynamic_friction",
                "payload_add_kg",
                "com_offset_x_m",
                "distortion",
            ):
                assert context[key] == config[key]
        else:
            assert capture["physical_context"]["pre_physics"] == config["pre_physics"]
            assert capture["physical_context"]["post_physics"] == config["post_physics"]
            assert (
                capture["physical_context"]["pre_distortion"]
                == config["pre_distortion"]
            )
            assert (
                capture["physical_context"]["post_distortion"]
                == config["post_distortion"]
            )
        assert capture["artifact_type"] == "qualitative_isaac_sim_response_card"
        assert capture["schema_version"] == "1.1"
        assert capture["composite_presentation"] is True
        assert len(capture["frames"]) == 1
        card = capture["frames"][0]
        assert card["path"] == f"{prefix}_experiment_card.png"
        assert card["resolution"] == [1600, 900]
        _assert_png_matches_record(GALLERY_DIR / card["path"], card)

        expected_family = (
            config["distortion"] if source_phase == "P5" else config["post_distortion"]
        )
        expected_parameter_seed = capture["selected_seed"]
        expected_stochastic_seed = int(config["simulator_seed"]) + 91
        if source_phase == "P6":
            expected_parameter_seed += int(config["post_seed_offset"])
            expected_stochastic_seed = int(config["simulator_seed"]) + 117
        distortion = capture["dynamic_response_distortion"]
        assert distortion["family"] == expected_family
        assert distortion["parameter_seed"] == expected_parameter_seed
        assert distortion["stochastic_seed"] == expected_stochastic_seed
        assert distortion["parameters"] == make_distortion_parameters(
            expected_family,
            (expected_parameter_seed,),
        ).to_dict()

        assert len(capture["source_frames"]) == 2
        assert capture["card_generation"]["source_frame_sha256"] == [
            frame["sha256"] for frame in capture["source_frames"]
        ]
        assert capture["card_generation"]["standalone_source_frames_retained"] is False
        expected_commands = {
            2: [0.20, -0.18, -0.30],
            7: [0.35, 0.00, 0.50],
        }
        observed_indices = set()
        for source_frame in capture["source_frames"]:
            assert source_frame["retained_as_standalone"] is False
            assert source_frame["source_capture_basename"].startswith(prefix)
            probe = source_frame["response_probe"]
            index = probe["registered_command_index"]
            observed_indices.add(index)
            assert probe["desired_command"] == expected_commands[index]
            assert probe["capture_at"] == (
                "registered_measurement_window_endpoint_before_ramp_out"
            )
            assert len(probe["response_endpoint_pose"]) == 6
            assert np.all(np.isfinite(probe["response_endpoint_pose"]))
            assert len(probe["trajectory_sha256"]) == 64
            assert len(probe["effective_command_trace_sha256"]) == 64
        assert observed_indices == {2, 7}

        assert len(overlays) == 2
        assert {overlay["probe_name"] for overlay in overlays} == {
            "coupled_response",
            "forward_turn_response",
        }
        for overlay in overlays:
            assert overlay["kind"] == "measured_response_trajectory"
            assert overlay["collision_enabled"] is False
            assert overlay["source_samples"] >= overlay["rendered_points"] >= 2
            points = np.asarray(overlay["sampled_xy_m"], dtype=np.float64)
            assert points.shape == (overlay["rendered_points"], 2)
            assert np.all(np.isfinite(points))


def test_response_cards_have_unique_fact_and_trace_signatures() -> None:
    signatures = set()
    for prefix in GALLERY_PREFIXES:
        if prefix.startswith("p7_"):
            continue
        capture = json.loads(
            (GALLERY_DIR / f"{prefix}_capture.json").read_text(encoding="utf-8")
        )
        signature = (
            capture["scenario_config_sha256"],
            capture["dynamic_response_distortion"]["family"],
            capture["dynamic_response_distortion"]["parameter_seed"],
            tuple(
                frame["response_probe"]["trajectory_sha256"]
                for frame in capture["source_frames"]
            ),
        )
        assert signature not in signatures
        signatures.add(signature)
    assert len(signatures) == 11


def test_gallery_contains_no_exact_or_near_duplicate_images() -> None:
    image_paths = []
    for prefix in GALLERY_PREFIXES:
        capture = json.loads(
            (GALLERY_DIR / f"{prefix}_capture.json").read_text(encoding="utf-8")
        )
        image_paths.extend(GALLERY_DIR / frame["path"] for frame in capture["frames"])
    assert len(image_paths) == 29
    hashes = [_sha256(path) for path in image_paths]
    assert len(hashes) == len(set(hashes))

    thumbnails = {
        path.name: np.asarray(
            Image.open(path)
            .convert("RGB")
            .resize((160, 90), Image.Resampling.LANCZOS),
            dtype=np.float32,
        )
        / 255.0
        for path in image_paths
    }
    for left, right in combinations(sorted(thumbnails), 2):
        mean_absolute_difference = float(
            np.mean(np.abs(thumbnails[left] - thumbnails[right]))
        )
        assert mean_absolute_difference >= 0.005, (
            f"near-duplicate gallery images: {left} vs {right}; "
            f"downsampled RGB MAE={mean_absolute_difference:.6f}"
        )


def test_bilingual_readmes_embed_every_factual_gallery_image() -> None:
    gallery_images = set()
    for prefix in GALLERY_PREFIXES:
        if prefix.startswith("p7_"):
            gallery_images.update(
                {
                    f"docs/assets/readme/isaac_sim/{prefix}_overview.png",
                    f"docs/assets/readme/isaac_sim/{prefix}_robot_view.png",
                }
            )
        else:
            gallery_images.add(
                f"docs/assets/readme/isaac_sim/{prefix}_experiment_card.png"
            )
    gallery_records = {
        f"docs/assets/readme/isaac_sim/{prefix}_capture.json"
        for prefix in GALLERY_PREFIXES
    }
    for readme_name in ("README.md", "README_zh-CN.md"):
        readme = (WORKSPACE / readme_name).read_text(encoding="utf-8")
        local_images = [
            source
            for source in re.findall(r'<img\s+src="([^"]+)"', readme)
            if not source.startswith(("http://", "https://"))
        ]
        assert len(local_images) == len(set(local_images))
        assert all((WORKSPACE / source).is_file() for source in local_images)
        assert gallery_images <= {image for image in gallery_images if image in readme}
        assert gallery_records <= {record for record in gallery_records if record in readme}
        assert "29" in readme
        assert "_closeup.png" not in readme
        assert "isaac_sim/p5_tier_a_affine_overview.png" not in readme
