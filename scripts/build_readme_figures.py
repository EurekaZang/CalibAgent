#!/usr/bin/env python3
"""Build the README trajectory figure from frozen P7 simulator evidence."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import Circle, Rectangle

matplotlib.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)

RAW_COLOR = "#666666"
ACTIVE_COLOR = "#0077BB"
OBSTACLE_COLOR = "#EE7733"


def _load_trace(
    path: Path,
    seed: int,
    *,
    stop_on_success: bool = False,
) -> tuple[list[float], list[float]]:
    x: list[float] = []
    y: list[float] = []
    with gzip.open(path, mode="rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["seed"]) == seed:
                x.append(float(row["pose_x"]))
                y.append(float(row["pose_y"]))
                if stop_on_success and row["success"].lower() == "true":
                    break
    if not x:
        raise ValueError(f"seed {seed} was not found in {path}")
    return x, y


def _load_geometry(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _draw_map(
    ax: Axes,
    geometry: dict[str, Any],
    navigation: dict[str, Any],
) -> None:
    safety_radius = float(geometry["collision_footprint_radius_m"])
    for index, obstacle in enumerate(geometry["obstacles"]):
        center_x, center_y = (float(value) for value in obstacle["center"])
        size_x, size_y = (float(value) for value in obstacle["size"][:2])
        ax.add_patch(
            Rectangle(
                (
                    center_x - size_x / 2 - safety_radius,
                    center_y - size_y / 2 - safety_radius,
                ),
                size_x + 2 * safety_radius,
                size_y + 2 * safety_radius,
                facecolor=OBSTACLE_COLOR,
                edgecolor="none",
                alpha=0.12,
            )
        )
        ax.add_patch(
            Rectangle(
                (center_x - size_x / 2, center_y - size_y / 2),
                size_x,
                size_y,
                facecolor=OBSTACLE_COLOR,
                edgecolor="#9A3412",
                linewidth=0.8,
                label="Obstacle" if index == 0 else None,
            )
        )

    waypoint_x = [float(point[0]) for point in geometry["waypoints"]]
    waypoint_y = [float(point[1]) for point in geometry["waypoints"]]
    ax.plot(
        [0.0, *waypoint_x],
        [0.0, *waypoint_y],
        color="#BBBBBB",
        linestyle="--",
        linewidth=1.1,
        marker="o",
        markersize=3,
        label="Fixed waypoint plan",
        zorder=1,
    )
    ax.scatter([0.0], [0.0], marker="s", s=40, color="#000000", label="Start", zorder=5)
    ax.scatter(
        [waypoint_x[-1]],
        [waypoint_y[-1]],
        marker="*",
        s=110,
        color="#009988",
        edgecolor="#005F55",
        linewidth=0.6,
        label="Goal",
        zorder=5,
    )
    ax.add_patch(
        Circle(
            (waypoint_x[-1], waypoint_y[-1]),
            radius=float(navigation["goal_radius_m"]),
            facecolor="#009988",
            edgecolor="#009988",
            linewidth=0.8,
            alpha=0.10,
        )
    )


def build_figure(workspace: Path, output: Path, seed: int) -> None:
    evidence = workspace / "evidence/p7_main/maps/slalom"
    geometry = _load_geometry(evidence / "B8_full/map_geometry.json")
    scenario = _load_geometry(evidence / "B8_full/scenario_config.json")
    raw_x, raw_y = _load_trace(evidence / "B0_raw/nav_trace.csv.gz", seed)
    active_x, active_y = _load_trace(
        evidence / "B8_full/nav_trace.csv.gz",
        seed,
        stop_on_success=True,
    )

    figure, ax = plt.subplots(figsize=(6.9, 3.8))
    _draw_map(ax, geometry, dict(scenario["navigation"]))
    ax.plot(
        raw_x,
        raw_y,
        color=RAW_COLOR,
        linestyle="--",
        linewidth=1.6,
        label="B0 raw (timeout)",
        zorder=3,
    )
    ax.plot(
        active_x,
        active_y,
        color=ACTIVE_COLOR,
        linewidth=1.8,
        label="B8 active, 12 trials (success)",
        zorder=4,
    )
    ax.scatter([raw_x[-1]], [raw_y[-1]], marker="x", s=45, color=RAW_COLOR, zorder=5)
    ax.scatter(
        [active_x[-1]],
        [active_y[-1]],
        marker="o",
        s=28,
        color=ACTIVE_COLOR,
        edgecolor="white",
        linewidth=0.6,
        zorder=5,
    )

    ax.set_title(f"Held-out slalom trajectory, paired simulator seed {seed}")
    ax.set_xlabel("World x position [m]")
    ax.set_ylabel("World y position [m]")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-0.2, 3.25)
    ax.set_ylim(-1.0, 1.0)
    ax.grid(True, color="#DDDDDD", linewidth=0.6, alpha=0.7)
    ax.legend(frameon=False, ncols=2, loc="lower center")

    output.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(output)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/assets/readme/p7_slalom_seed_8006.png"),
    )
    parser.add_argument("--seed", type=int, default=8006)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    output = args.output
    if not output.is_absolute():
        output = workspace / output
    build_figure(workspace, output, args.seed)


if __name__ == "__main__":
    main()
