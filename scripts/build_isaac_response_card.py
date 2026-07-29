#!/usr/bin/env python3
"""Build one publication-facing card from two native Isaac Sim response frames."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec
from PIL import Image
from PIL import __version__ as pillow_version

CARD_WIDTH = 1600
CARD_HEIGHT = 900
BACKGROUND = "#0b1118"
FOREGROUND = "#e8eef5"
MUTED = "#a9b5c2"
GRID = "#334250"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _physical_lines(capture: dict[str, Any]) -> list[str]:
    context = capture["physical_context"]
    if capture["source_phase"] == "P5":
        return [
            f"terrain: {context['terrain']}",
            (
                "friction static/dynamic: "
                f"{context['static_friction']:.3f} / {context['dynamic_friction']:.3f}"
            ),
            f"payload added: {context['payload_add_kg']:+.3f} kg",
            f"COM x-offset: {context['com_offset_x_m']:+.3f} m",
            f"distortion: {context['distortion']}",
        ]
    pre = context["pre_physics"]
    post = context["post_physics"]
    return [
        (
            "friction static: "
            f"{pre['static_friction']:.3f} -> {post['static_friction']:.3f}"
        ),
        (
            "friction dynamic: "
            f"{pre['dynamic_friction']:.3f} -> {post['dynamic_friction']:.3f}"
        ),
        f"payload: {pre['payload_add_kg']:+.3f} -> {post['payload_add_kg']:+.3f} kg",
        (
            "COM x-offset: "
            f"{pre['com_offset_x_m']:+.3f} -> {post['com_offset_x_m']:+.3f} m"
        ),
        f"distortion: {context['pre_distortion']} -> {context['post_distortion']}",
    ]


def _probe_title(frame: dict[str, Any]) -> str:
    probe = frame["response_probe"]
    command = probe["desired_command"]
    return (
        f"Registered validation probe #{probe['registered_command_index']}: "
        f"[{command[0]:+.2f}, {command[1]:+.2f}, {command[2]:+.2f}]"
    )


def _draw_card(
    capture: dict[str, Any],
    frame_dir: Path,
    output_path: Path,
) -> None:
    frames = capture["frames"]
    overlays = {
        overlay["probe_name"]: overlay
        for overlay in capture["capture_only_visualization_overlays"]
    }
    figure = plt.figure(
        figsize=(CARD_WIDTH / 100, CARD_HEIGHT / 100),
        dpi=100,
        facecolor=BACKGROUND,
    )
    grid = GridSpec(
        2,
        2,
        figure=figure,
        height_ratios=(1.12, 0.88),
        hspace=0.16,
        wspace=0.08,
        left=0.035,
        right=0.975,
        top=0.88,
        bottom=0.07,
    )
    figure.suptitle(
        f"{capture['source_phase']} | {capture['scenario_id']} | "
        "registered Isaac Sim response replay",
        color=FOREGROUND,
        fontsize=22,
        fontweight="bold",
        x=0.035,
        y=0.955,
        ha="left",
    )
    figure.text(
        0.035,
        0.905,
        (
            f"seed {capture['selected_seed']}  |  "
            f"Isaac Lab {capture['runtime']['isaaclab_describe']}  |  "
            f"Isaac Sim {capture['runtime']['isaac_sim_version'].split('+')[0]}"
        ),
        color=MUTED,
        fontsize=11,
        ha="left",
    )

    for column, frame in enumerate(frames):
        axis = figure.add_subplot(grid[0, column])
        axis.imshow(Image.open(frame_dir / frame["path"]).convert("RGB"))
        axis.set_title(_probe_title(frame), color=FOREGROUND, fontsize=11, pad=8)
        axis.axis("off")
        for spine in axis.spines.values():
            spine.set_edgecolor(GRID)

    trajectory_axis = figure.add_subplot(grid[1, 0])
    trajectory_axis.set_facecolor("#111a23")
    colors = {
        "coupled_response": "#18bce8",
        "forward_turn_response": "#f0642d",
    }
    for frame in frames:
        probe = frame["response_probe"]
        name = probe["name"]
        points = np.asarray(overlays[name]["sampled_xy_m"], dtype=np.float64)
        trajectory_axis.plot(
            points[:, 0],
            points[:, 1],
            color=colors[name],
            linewidth=3.0,
            label=(
                f"probe #{probe['registered_command_index']} "
                f"(trace {probe['trajectory_sha256'][:10]})"
            ),
        )
        trajectory_axis.scatter(
            points[0, 0],
            points[0, 1],
            color="#f5cf2e",
            s=65,
            zorder=3,
        )
        trajectory_axis.scatter(
            points[-1, 0],
            points[-1, 1],
            color="#35df63",
            s=65,
            zorder=3,
        )
    trajectory_axis.set_title(
        "Actual body-response trajectory at the registered measurement window",
        color=FOREGROUND,
        fontsize=12,
        loc="left",
    )
    trajectory_axis.set_xlabel("body x displacement [m]", color=MUTED)
    trajectory_axis.set_ylabel("body y displacement [m]", color=MUTED)
    trajectory_axis.tick_params(colors=MUTED)
    trajectory_axis.grid(color=GRID, alpha=0.7, linewidth=0.8)
    trajectory_axis.axis("equal")
    legend = trajectory_axis.legend(
        loc="best",
        facecolor="#111a23",
        edgecolor=GRID,
        fontsize=9,
    )
    for text in legend.get_texts():
        text.set_color(FOREGROUND)
    for spine in trajectory_axis.spines.values():
        spine.set_edgecolor(GRID)

    facts_axis = figure.add_subplot(grid[1, 1])
    facts_axis.set_facecolor("#111a23")
    facts_axis.axis("off")
    facts_axis.set_title(
        "Frozen configuration and replayed endpoints",
        color=FOREGROUND,
        fontsize=12,
        loc="left",
        pad=10,
    )
    lines = _physical_lines(capture)
    distortion = capture["dynamic_response_distortion"]
    lines.extend(
        [
            f"distortion parameter seed: {distortion['parameter_seed']}",
            f"checkpoint SHA-256: {capture['checkpoint']['sha256'][:16]}...",
            f"scenario config SHA-256: {capture['scenario_config_sha256'][:16]}...",
        ]
    )
    for frame in frames:
        probe = frame["response_probe"]
        endpoint = probe["response_endpoint_pose"]
        lines.append(
            f"probe #{probe['registered_command_index']} endpoint "
            f"(x, y, yaw): ({endpoint[0]:+.3f}, {endpoint[1]:+.3f}, "
            f"{endpoint[5]:+.3f})"
        )
    facts_axis.text(
        0.02,
        0.96,
        "\n".join(lines),
        transform=facts_axis.transAxes,
        va="top",
        ha="left",
        color=FOREGROUND,
        fontsize=10.5,
        linespacing=1.42,
        family="monospace",
    )
    facts_axis.text(
        0.02,
        0.04,
        (
            "Yellow = start; green = measurement-window endpoint. "
            "The colored trace is capture-only, non-colliding geometry replayed "
            "from the simulated body pose. Quantitative claims use the frozen "
            "multi-seed evidence, not this qualitative card."
        ),
        transform=facts_axis.transAxes,
        va="bottom",
        ha="left",
        color=MUTED,
        fontsize=9,
        wrap=True,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output_path,
        dpi=100,
        facecolor=figure.get_facecolor(),
        metadata={"Software": "CalibAgent build_isaac_response_card.py"},
    )
    plt.close(figure)


def _write_provenance(
    capture: dict[str, Any],
    output_path: Path,
    provenance_path: Path,
) -> None:
    source_frames = []
    for frame in capture.pop("frames"):
        source = dict(frame)
        source["source_capture_basename"] = source.pop("path")
        source["retained_as_standalone"] = False
        source_frames.append(source)
    capture["schema_version"] = "1.1"
    capture["artifact_type"] = "qualitative_isaac_sim_response_card"
    capture["composite_presentation"] = True
    capture["source_frames"] = source_frames
    capture["frames"] = [
        {
            "path": output_path.name,
            "sha256": _sha256(output_path),
            "resolution": [CARD_WIDTH, CARD_HEIGHT],
            "description": (
                "Two native Isaac Sim response frames, their actual XY response "
                "traces, and the frozen scenario facts."
            ),
        }
    ]
    capture["card_generation"] = {
        "script": "scripts/build_isaac_response_card.py",
        "matplotlib_version": matplotlib.__version__,
        "pillow_version": pillow_version,
        "source_frame_count": 2,
        "source_frame_sha256": [frame["sha256"] for frame in source_frames],
        "standalone_source_frames_retained": False,
    }
    capture["interpretation"] = (
        "This composite documents two registered validation-command replays and "
        "their exact scenario context. It is qualitative setup/response "
        "documentation and does not replace the registered multi-seed statistics."
    )
    provenance_path.write_text(
        json.dumps(capture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-json", type=Path, required=True)
    parser.add_argument("--frame-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    capture = json.loads(arguments.capture_json.read_text(encoding="utf-8"))
    prefix = arguments.capture_json.name.removesuffix("_capture.json")
    output_path = arguments.output_dir / f"{prefix}_experiment_card.png"
    provenance_path = arguments.output_dir / f"{prefix}_capture.json"
    _draw_card(capture, arguments.frame_dir, output_path)
    _write_provenance(capture, output_path, provenance_path)


if __name__ == "__main__":
    main()
