#!/usr/bin/env python3
"""Build an auditable long-exposure comparison from two real-Go2 videos.

The output contains no drawn trajectory, recoloring, or geometric annotation.
For each run, a temporal-median background is estimated from uniformly sampled
frames.  Robot appearances at matched elapsed times are then composited where
they differ from that background.  Source-frame RGB values are unchanged;
only foreground alpha encodes time, decreasing from 100% to 50% opacity.
The direct-command run is placed on the left and the GAUGE-compensated run on
the right.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"
DIRECT_VIDEO = PAPER / "figures" / "uncalib.mp4"
GAUGE_VIDEO = PAPER / "figures" / "calib.mp4"
OUTPUT = PAPER / "figures" / "real_dclp_long_exposure.png"
MANIFEST = ROOT / "evidence" / "paper_figure_provenance" / "real_dclp_long_exposure.json"

BACKGROUND_FRAME_COUNT = 31
EXPOSURE_TIMESTAMPS_S = tuple(np.linspace(0.8, 9.2, 11).round(3))
EXPOSURE_OPACITIES = tuple(np.linspace(1.0, 0.5, len(EXPOSURE_TIMESTAMPS_S)).round(3))
DIFFERENCE_THRESHOLD = 15.0
MIN_COMPONENT_AREA_PX = 180
MASK_DILATION_ITERATIONS = 2
MASK_FEATHER_SIGMA_PX = 1.15
PANEL_GAP_PX = 12
PANEL_CROP_LEFT_PX = 0
PANEL_CROP_RIGHT_PX = 1560


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_video(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("ffprobe is required to build the long-exposure figure")
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    return {
        "duration_s": float(payload["format"]["duration"]),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "avg_frame_rate": str(stream["avg_frame_rate"]),
    }


def decode_frame(path: Path, timestamp_s: float) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to build the long-exposure figure")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp_s:.3f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    result = subprocess.run(command, check=True, capture_output=True)
    with Image.open(io.BytesIO(result.stdout)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def center_crop_height(frame: np.ndarray, target_height: int) -> np.ndarray:
    excess = frame.shape[0] - target_height
    if excess < 0:
        raise ValueError("target height exceeds decoded frame height")
    top = excess // 2
    return frame[top : top + target_height]


def temporal_background(
    path: Path,
    duration_s: float,
    target_height: int,
) -> tuple[np.ndarray, list[float]]:
    timestamps = np.linspace(0.05, duration_s - 0.05, BACKGROUND_FRAME_COUNT)
    frames = [
        center_crop_height(decode_frame(path, float(timestamp)), target_height)
        for timestamp in timestamps
    ]
    frame_stack = np.stack(frames, axis=0)
    background = np.median(frame_stack, axis=0, overwrite_input=True)
    return background.astype(np.uint8), [round(float(value), 4) for value in timestamps]


def foreground_mask(frame: np.ndarray, background: np.ndarray) -> np.ndarray:
    delta = frame.astype(np.float32) - background.astype(np.float32)
    magnitude = np.sqrt(np.mean(np.square(delta), axis=2))
    mask = magnitude >= DIFFERENCE_THRESHOLD
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 3), dtype=bool))
    mask = ndimage.binary_dilation(mask, iterations=MASK_DILATION_ITERATIONS)

    labels, count = ndimage.label(mask)
    if count:
        areas = np.bincount(labels.ravel())
        retained = areas >= MIN_COMPONENT_AREA_PX
        retained[0] = False
        mask = retained[labels]

    mask = ndimage.binary_fill_holes(mask)
    soft_mask = ndimage.gaussian_filter(mask.astype(np.float32), sigma=MASK_FEATHER_SIGMA_PX)
    return np.clip(soft_mask, 0.0, 1.0)


def build_panel(
    path: Path,
    duration_s: float,
    target_height: int,
) -> tuple[np.ndarray, list[float]]:
    background, background_timestamps = temporal_background(path, duration_s, target_height)
    canvas = background.astype(np.float32)
    for timestamp_s, opacity in zip(
        EXPOSURE_TIMESTAMPS_S,
        EXPOSURE_OPACITIES,
        strict=True,
    ):
        if timestamp_s >= duration_s:
            raise ValueError(f"exposure timestamp {timestamp_s} exceeds {path.name}")
        frame = center_crop_height(decode_frame(path, float(timestamp_s)), target_height)
        alpha = foreground_mask(frame, background)[..., None] * float(opacity)
        canvas = frame.astype(np.float32) * alpha + canvas * (1.0 - alpha)
    return np.clip(canvas, 0, 255).astype(np.uint8), background_timestamps


def build() -> dict[str, object]:
    for path in (DIRECT_VIDEO, GAUGE_VIDEO):
        if not path.is_file():
            raise FileNotFoundError(f"Missing source video: {path}")

    direct_info = probe_video(DIRECT_VIDEO)
    gauge_info = probe_video(GAUGE_VIDEO)
    if int(direct_info["width"]) != int(gauge_info["width"]):
        raise ValueError("source videos must have the same width")
    target_height = min(int(direct_info["height"]), int(gauge_info["height"]))

    direct_panel, direct_background_times = build_panel(
        DIRECT_VIDEO,
        float(direct_info["duration_s"]),
        target_height,
    )
    gauge_panel, gauge_background_times = build_panel(
        GAUGE_VIDEO,
        float(gauge_info["duration_s"]),
        target_height,
    )

    source_width = int(direct_info["width"])
    if not 0 <= PANEL_CROP_LEFT_PX < PANEL_CROP_RIGHT_PX <= source_width:
        raise ValueError("invalid shared horizontal crop")
    direct_panel = direct_panel[:, PANEL_CROP_LEFT_PX:PANEL_CROP_RIGHT_PX]
    gauge_panel = gauge_panel[:, PANEL_CROP_LEFT_PX:PANEL_CROP_RIGHT_PX]
    if direct_panel.shape != gauge_panel.shape:
        raise ValueError("cropped panels must have identical dimensions")

    gap = np.full((target_height, PANEL_GAP_PX, 3), 255, dtype=np.uint8)
    composite = np.concatenate((direct_panel, gap, gauge_panel), axis=1)
    output_image = Image.fromarray(composite, mode="RGB")
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("Title", "Real-Go2 DRL-DCLP long-exposure comparison")
    png_info.add_text("Author", "Anonymous Authors")
    png_info.add_text("Creator", "paper/scripts/build_real_dclp_long_exposure.py")
    png_info.add_text("Panel order", "Left: direct commands; right: DRL-DCLP + GAUGE")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output_image.save(OUTPUT, format="PNG", dpi=(300, 300), pnginfo=png_info, optimize=True)

    return {
        "schema_version": 1,
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "selection_rule": (
            "Eleven matched elapsed times sampled uniformly from 0.8 to 9.2 s. "
            "A temporal-median background is estimated independently for each fixed-camera run; "
            "only foreground differences are alpha-composited."
        ),
        "interpretation": (
            "Qualitative long-exposure visualization of one matched-scene run per condition. "
            "No trajectory geometry is drawn and no quantitative endpoint is inferred from pixels."
        ),
        "panel_order": ["direct_command", "gauge"],
        "exposure_timestamps_s": [float(value) for value in EXPOSURE_TIMESTAMPS_S],
        "exposure_opacities": [float(value) for value in EXPOSURE_OPACITIES],
        "exposure_transparencies": [
            round(1.0 - float(value), 3) for value in EXPOSURE_OPACITIES
        ],
        "algorithm": {
            "background_frame_count": BACKGROUND_FRAME_COUNT,
            "difference_threshold_rgb_rms": DIFFERENCE_THRESHOLD,
            "minimum_component_area_px": MIN_COMPONENT_AREA_PX,
            "mask_dilation_iterations": MASK_DILATION_ITERATIONS,
            "mask_feather_sigma_px": MASK_FEATHER_SIGMA_PX,
            "time_encoding": (
                "only foreground alpha changes with elapsed time; opacity decreases "
                "linearly from 100% to 50%, while source-frame RGB is unchanged"
            ),
            "common_center_crop_height_px": target_height,
            "common_horizontal_crop_px": [PANEL_CROP_LEFT_PX, PANEL_CROP_RIGHT_PX],
            "panel_gap_px": PANEL_GAP_PX,
        },
        "sources": {
            "direct_command": {
                "path": str(DIRECT_VIDEO.relative_to(ROOT)),
                "sha256": sha256(DIRECT_VIDEO),
                **direct_info,
                "background_timestamps_s": direct_background_times,
            },
            "gauge": {
                "path": str(GAUGE_VIDEO.relative_to(ROOT)),
                "sha256": sha256(GAUGE_VIDEO),
                **gauge_info,
                "background_timestamps_s": gauge_background_times,
            },
        },
        "output": {
            "path": str(OUTPUT.relative_to(ROOT)),
            "sha256": sha256(OUTPUT),
            "width": composite.shape[1],
            "height": composite.shape[0],
        },
    }


def main() -> None:
    manifest = build()
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    print(f"Wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
