#!/usr/bin/env python3
"""Build the qualitative real-Go2 navigation comparison figure.

The figure uses matched elapsed times within each uncompensated/GAUGE pair.
Frames are decoded directly from the archived comparison video so the panel
selection is reproducible and auditable.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"
VIDEO = PAPER / "figures" / "Compensation.mp4"
OUTPUT_PDF = PAPER / "figures" / "real_go2_navigation.pdf"
OUTPUT_PNG = PAPER / "figures" / "real_go2_navigation.png"
MANIFEST = ROOT / "evidence" / "paper_figure_provenance" / "real_go2_navigation.json"

BASELINE_COLOR = "#A3473C"
GAUGE_COLOR = "#1F5A94"
TEXT_COLOR = "#1E2530"

# Starts are the first full video frames of the executions following each
# title card.  Both conditions use the same elapsed times within each scene.
SCENES = (
    {
        "label": "Static I",
        "panel": "(a)",
        "baseline_start_s": 1.0,
        "gauge_start_s": 12.0,
        "elapsed_s": (1.75, 3.25),
    },
    {
        "label": "Static II",
        "panel": "(b)",
        "baseline_start_s": 22.0,
        "gauge_start_s": 31.0,
        "elapsed_s": (1.0, 2.5),
    },
    {
        "label": "Moving\nperson",
        "panel": "(c)",
        "baseline_start_s": 41.0,
        "gauge_start_s": 53.0,
        "elapsed_s": (2.5, 4.0),
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_frame(timestamp_s: float) -> Image.Image:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to build the real-Go2 figure")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp_s:.3f}",
        "-i",
        str(VIDEO),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    result = subprocess.run(command, check=True, capture_output=True)
    with Image.open(io.BytesIO(result.stdout)) as frame:
        return frame.convert("RGB")


def style_frame_axis(ax: plt.Axes, image: Image.Image, color: str, elapsed_s: float) -> None:
    ax.imshow(image, interpolation="lanczos")
    ax.set_axis_off()
    ax.add_patch(
        Rectangle(
            (0, 0),
            1,
            1,
            transform=ax.transAxes,
            fill=False,
            linewidth=1.15,
            edgecolor=color,
            clip_on=False,
        )
    )
    ax.text(
        0.025,
        0.95,
        f"t = {elapsed_s:.2f} s",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=6.2,
        color="white",
        bbox={"boxstyle": "round,pad=0.16", "facecolor": "black", "alpha": 0.68, "edgecolor": "none"},
    )


def build() -> dict[str, object]:
    if not VIDEO.is_file():
        raise FileNotFoundError(f"Missing source video: {VIDEO}")

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Liberation Sans", "DejaVu Sans"],
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.linewidth": 0.6,
        }
    )

    fig = plt.figure(figsize=(7.08, 1.94), facecolor="white")
    grid = fig.add_gridspec(
        3,
        9,
        height_ratios=(0.22, 1.0, 1.0),
        width_ratios=(0.56, 1.0, 1.0, 0.07, 1.0, 1.0, 0.07, 1.0, 1.0),
        left=0.012,
        right=0.995,
        bottom=0.025,
        top=0.985,
        wspace=0.025,
        hspace=0.06,
    )

    for columns, panel, title in (
        ((1, 2), "(a)", "Static I"),
        ((4, 5), "(b)", "Static II"),
        ((7, 8), "(c)", "Moving person"),
    ):
        ax = fig.add_subplot(grid[0, columns[0] : columns[1] + 1])
        ax.set_axis_off()
        ax.text(
            0.5,
            0.58,
            f"{panel}  {title}",
            ha="center",
            va="center",
            fontsize=7.7,
            weight="bold",
            color=TEXT_COLOR,
            transform=ax.transAxes,
            clip_on=False,
        )
        ax.plot([0.08, 0.92], [0.08, 0.08], color="#727981", linewidth=0.85, transform=ax.transAxes)

    for column in (3, 6):
        divider = fig.add_subplot(grid[:, column])
        divider.set_axis_off()
        divider.plot([0.5, 0.5], [0.01, 0.93], color="#C8CDD3", linewidth=0.65, transform=divider.transAxes)

    for row, title, color in (
        (1, "DRL-DCLP\ndirect", BASELINE_COLOR),
        (2, "DRL-DCLP\n+ GAUGE", GAUGE_COLOR),
    ):
        label_ax = fig.add_subplot(grid[row, 0])
        label_ax.set_axis_off()
        label_ax.text(
            0.5,
            0.5,
            title,
            ha="center",
            va="center",
            fontsize=6.8,
            weight="bold",
            color=color,
            linespacing=1.05,
        )

    frame_records: list[dict[str, object]] = []
    for scene, columns in zip(SCENES, ((1, 2), (4, 5), (7, 8)), strict=True):
        elapsed_values = scene["elapsed_s"]
        assert isinstance(elapsed_values, tuple)
        for condition, start_key, row, color in (
            ("direct_command", "baseline_start_s", 1, BASELINE_COLOR),
            ("gauge", "gauge_start_s", 2, GAUGE_COLOR),
        ):
            start_s = float(scene[start_key])
            for elapsed_s, column in zip(elapsed_values, columns, strict=True):
                timestamp_s = start_s + float(elapsed_s)
                frame = decode_frame(timestamp_s)
                axis = fig.add_subplot(grid[row, column])
                style_frame_axis(axis, frame, color, float(elapsed_s))
                frame_records.append(
                    {
                        "scene": str(scene["label"]).replace("\n", " "),
                        "condition": condition,
                        "run_start_s": start_s,
                        "elapsed_s": float(elapsed_s),
                        "video_timestamp_s": timestamp_s,
                    }
                )

    metadata = {
        "Title": "Real-Go2 navigation with DRL-DCLP and GAUGE",
        "Author": "Anonymous Authors",
        "Subject": "Qualitative matched-time hardware navigation comparison",
        "Keywords": "Unitree Go2, navigation, calibration, DRL-DCLP, GAUGE",
        "Creator": "paper/scripts/build_real_navigation_figure.py",
        "CreationDate": None,
        "ModDate": None,
    }
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PDF, dpi=300, metadata=metadata, facecolor="white")
    fig.savefig(OUTPUT_PNG, dpi=300, metadata={"Software": metadata["Creator"]}, facecolor="white")
    plt.close(fig)

    return {
        "schema_version": 1,
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "source_video": str(VIDEO.relative_to(ROOT)),
        "source_video_sha256": sha256(VIDEO),
        "source_video_duration_s": 62.0,
        "source_video_resolution": [1280, 720],
        "selection_rule": "Two frames at matched elapsed times in each direct-command/GAUGE scene pair.",
        "interpretation": (
            "Representative qualitative image sequence. Each scene and condition was repeated five times; "
            "the source video contains the representative execution shown here and is not a quantitative log."
        ),
        "frames": frame_records,
        "outputs": {
            str(OUTPUT_PDF.relative_to(ROOT)): sha256(OUTPUT_PDF),
            str(OUTPUT_PNG.relative_to(ROOT)): sha256(OUTPUT_PNG),
        },
    }


def main() -> None:
    manifest = build()
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PDF.relative_to(ROOT)}")
    print(f"Wrote {OUTPUT_PNG.relative_to(ROOT)}")
    print(f"Wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
