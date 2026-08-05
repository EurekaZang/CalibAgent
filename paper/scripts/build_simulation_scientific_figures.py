#!/usr/bin/env python3
"""Build formal P5/P6 simulation figures from registered machine-readable data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[2]
CAPTURE_DIR = ROOT / "docs" / "assets" / "readme" / "isaac_sim"
OUT = ROOT / "paper" / "figures"
PROVENANCE_OUT = ROOT / "evidence" / "paper_figure_provenance"
P5_SUMMARY = ROOT / "evidence" / "p5_main" / "summary.json"
P6_SUMMARY = ROOT / "evidence" / "p6_paired_signature_pooled_030" / "summary.json"
SELECTOR_ROOT = ROOT / "evidence" / "recovery_selector_ablation"

BLUE = "#0072B2"
VERMILLION = "#D55E00"
GREEN = "#009E73"
ORANGE = "#E69F00"
GREY = "#8A8A8A"
LIGHT_GREY = "#D8DDE3"
BLACK = "#222222"

mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 7.5,
        "axes.titlesize": 8.5,
        "axes.labelsize": 7.5,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "legend.fontsize": 6.5,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.7,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
    }
)

P5_CAPTURE_NAMES = [
    "p5_tier_a_affine_capture.json",
    "p5_tier_a_deadzone_capture.json",
    "p5_tier_b_friction_payload_capture.json",
    "p5_tier_b_rough_capture.json",
]
P6_CAPTURE_NAMES = [
    "p6_confirm_friction_payload_capture.json",
    "p6_confirm_gain_recoupling_capture.json",
    "p6_confirm_mixed_context_capture.json",
    "p6_confirm_payload_com_only_capture.json",
]
LABELS = {
    "tier_a_affine": "Affine",
    "tier_a_deadzone": "Dead zone",
    "tier_b_friction_payload": "Friction + load + COM",
    "tier_b_rough": "Rough + load + COM",
    "confirm_friction_payload": "Friction + load + gain",
    "confirm_gain_recoupling": "Gain + coupling",
    "confirm_mixed_context": "Physical + nonlinear",
    "confirm_payload_com_only": "Load + COM + gain",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def captures(names: list[str]) -> list[dict[str, Any]]:
    return [load_json(CAPTURE_DIR / name) for name in names]


def style_axis(ax: plt.Axes) -> None:
    ax.axhline(0.0, color=LIGHT_GREY, lw=0.6, zorder=0)
    ax.axvline(0.0, color=LIGHT_GREY, lw=0.6, zorder=0)
    ax.tick_params(direction="out", length=2.8, pad=1.5)


def draw_response_axis(
    ax: plt.Axes,
    capture: dict[str, Any],
    panel: str,
    limits: tuple[tuple[float, float], tuple[float, float]],
) -> None:
    overlays = {item["probe_name"]: item for item in capture["capture_only_visualization_overlays"]}
    probes = {
        item["response_probe"]["name"]: item["response_probe"] for item in capture["source_frames"]
    }
    names = ["coupled_response", "forward_turn_response"]
    colors = [BLUE, VERMILLION]
    for name, color in zip(names, colors, strict=True):
        points = np.asarray(overlays[name]["sampled_xy_m"], dtype=float)
        probe = probes[name]
        command = np.asarray(probe["desired_command"], dtype=float)
        counts = probe["profile_phase_counts"]
        ramp = np.linspace(0.0, 1.0, int(counts["0"]), endpoint=True)
        scales = np.concatenate(
            [
                np.zeros(int(counts["-1"])),
                ramp,
                np.ones(int(counts["1"]) + int(counts["2"])),
            ]
        )
        dt = float(probe["step_dt_s"])
        ideal = np.zeros((len(scales), 3), dtype=float)
        for step in range(1, len(scales)):
            vx, vy, wz = command * scales[step - 1]
            yaw = ideal[step - 1, 2]
            ideal[step, 0] = ideal[step - 1, 0] + dt * (np.cos(yaw) * vx - np.sin(yaw) * vy)
            ideal[step, 1] = ideal[step - 1, 1] + dt * (np.sin(yaw) * vx + np.cos(yaw) * vy)
            ideal[step, 2] = yaw + dt * wz
        ax.plot(
            ideal[:, 0],
            ideal[:, 1],
            color=GREY,
            lw=0.9,
            ls="--",
            alpha=0.85,
            zorder=1,
        )
        ax.scatter(
            ideal[-1, 0],
            ideal[-1, 1],
            s=18,
            marker="x",
            color=GREY,
            linewidth=0.9,
            zorder=3,
        )
        ax.plot(points[:, 0], points[:, 1], color=color, lw=1.45, zorder=2)
        ax.scatter(points[0, 0], points[0, 1], s=12, marker="D", color=BLACK, zorder=3)
        ax.scatter(
            points[-1, 0],
            points[-1, 1],
            s=20,
            marker="o",
            color=color,
            edgecolor="white",
            linewidth=0.45,
            zorder=4,
        )
    ax.set_xlim(*limits[0])
    ax.set_ylim(*limits[1])
    ax.set_aspect("equal", adjustable="box")
    style_axis(ax)
    ax.set_title(f"{panel}  {LABELS[capture['scenario_id']]}", loc="left", pad=3, fontweight="bold")
    ax.set_xlabel("$x$ displacement [m]", labelpad=1.5)


def finish(fig: plt.Figure, stem: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}.pdf", facecolor="white")
    fig.savefig(OUT / f"{stem}.png", facecolor="white", dpi=300)
    plt.close(fig)


def build_p5() -> None:
    p5_caps = captures(P5_CAPTURE_NAMES)
    summary = load_json(P5_SUMMARY)
    rows = {item["scenario"]: item for item in summary["scenarios"]}
    ordered = [rows[item["scenario_id"]] for item in p5_caps]

    fig = plt.figure(figsize=(7.05, 3.00), constrained_layout=True)
    outer = fig.add_gridspec(2, 1, height_ratios=[1.1, 0.9], hspace=0.20)
    top = outer[0].subgridspec(1, 4, wspace=0.25)
    bottom = outer[1].subgridspec(1, 2, wspace=0.34)
    limits = ((-0.06, 0.58), (-0.43, 0.35))
    response_axes = []
    for index, capture in enumerate(p5_caps):
        ax = fig.add_subplot(top[0, index])
        draw_response_axis(ax, capture, chr(ord("a") + index), limits)
        response_axes.append(ax)
        if index == 0:
            ax.set_ylabel("$y$ displacement [m]", labelpad=1.5)
        else:
            ax.set_yticklabels([])

    handles = [
        mpl.lines.Line2D(
            [],
            [],
            color=BLUE,
            lw=1.5,
            marker="o",
            markersize=3.5,
            label=r"Coupled command: $[0.20,-0.18,-0.30]$",
        ),
        mpl.lines.Line2D(
            [],
            [],
            color=VERMILLION,
            lw=1.5,
            marker="o",
            markersize=3.5,
            label=r"Forward-turn command: $[0.35,0.00,0.50]$",
        ),
        mpl.lines.Line2D([], [], color=BLACK, lw=0, marker="D", markersize=3, label="Start"),
        mpl.lines.Line2D(
            [],
            [],
            color=GREY,
            lw=0.9,
            ls="--",
            marker="x",
            markersize=3,
            label="Ideal command response",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="outside upper center",
        ncol=4,
        frameon=False,
        columnspacing=1.3,
        handlelength=1.7,
    )

    # Paired raw-to-calibrated RMSE.
    ax_rmse = fig.add_subplot(bottom[0, 0])
    y = np.arange(len(ordered))
    raw = np.asarray([row["raw_rmse"] for row in ordered])
    calibrated = np.asarray([row["calibrated_rmse"] for row in ordered])
    for i in range(len(ordered)):
        ax_rmse.plot([calibrated[i], raw[i]], [i, i], color=GREY, lw=1.3, zorder=1)
    ax_rmse.scatter(raw, y, color=GREY, marker="s", s=22, zorder=2)
    ax_rmse.scatter(calibrated, y, color=GREEN, marker="o", s=24, zorder=3)
    for i, row in enumerate(ordered):
        reduction = 100.0 * row["calibrated_vs_raw_reduction"]
        ax_rmse.text(raw[i] + 0.0025, i, f"{reduction:.1f}%", va="center", fontsize=6.2)
    ax_rmse.set_yticks(y, [LABELS[row["scenario"]] for row in ordered])
    ax_rmse.invert_yaxis()
    ax_rmse.set_ylim(3.2, -0.62)
    ax_rmse.set_xlim(0.07, 0.162)
    ax_rmse.set_xlabel("Held-out velocity RMSE")
    ax_rmse.set_title("e  Held-out calibration", loc="left", fontweight="bold")
    ax_rmse.text(
        raw[0], -0.42, "Raw", color=GREY, ha="right", va="center", fontsize=6.4, fontweight="bold"
    )
    ax_rmse.text(
        calibrated[0],
        -0.42,
        "Calibrated",
        color=GREEN,
        ha="center",
        va="center",
        fontsize=6.4,
        fontweight="bold",
    )
    ax_rmse.grid(axis="x", color=LIGHT_GREY, lw=0.55)

    # Seed-paired absolute improvement and bootstrap interval.
    ax_effect = fig.add_subplot(bottom[0, 1])
    means = np.asarray([row["paired_absolute_improvement_mean"] for row in ordered])
    cis = np.asarray([row["paired_absolute_improvement_ci95"] for row in ordered])
    ax_effect.errorbar(
        means,
        y,
        xerr=np.vstack([means - cis[:, 0], cis[:, 1] - means]),
        fmt="o",
        color=BLUE,
        ecolor=BLUE,
        markersize=4.2,
        capsize=2.4,
        lw=1.1,
    )
    ax_effect.axvline(0, color=BLACK, lw=0.7)
    ax_effect.set_yticks(y, [LABELS[row["scenario"]] for row in ordered])
    ax_effect.invert_yaxis()
    ax_effect.set_xlim(0, 0.052)
    ax_effect.set_xlabel("Paired raw $-$ calibrated RMSE")
    ax_effect.set_title("f  Seed-paired effect (95% bootstrap CI)", loc="left", fontweight="bold")
    ax_effect.grid(axis="x", color=LIGHT_GREY, lw=0.55)
    finish(fig, "closed_loop_response")


def shift_cell_text(capture: dict[str, Any]) -> tuple[list[str], list[float]]:
    context = capture["physical_context"]
    pre = context["pre_physics"]
    post = context["post_physics"]
    texts = [
        f"{pre['static_friction']:.2f}$\\to${post['static_friction']:.2f}",
        f"{pre['dynamic_friction']:.2f}$\\to${post['dynamic_friction']:.2f}",
        f"{pre['payload_add_kg']:.1f}$\\to${post['payload_add_kg']:.1f}",
        f"{1000 * pre['com_offset_x_m']:.0f}$\\to${1000 * post['com_offset_x_m']:.0f}",
        "1.05--1.15",
        ".65--.72",
        "$\\leq$.04",
        "$\\leq$.12",
    ]
    magnitudes = [
        abs(post["static_friction"] - pre["static_friction"]),
        abs(post["dynamic_friction"] - pre["dynamic_friction"]),
        abs(post["payload_add_kg"] - pre["payload_add_kg"]),
        abs(1000 * (post["com_offset_x_m"] - pre["com_offset_x_m"])),
        1.0,
        1.0,
        1.0,
        1.0,
    ]
    return texts, magnitudes


def build_p6() -> None:
    p6_caps = captures(P6_CAPTURE_NAMES)
    summary = load_json(P6_SUMMARY)
    rows = {item["context"]: item for item in summary["contexts"]}
    ordered = [rows[str(item["scenario_id"]).removeprefix("confirm_")] for item in p6_caps]

    fig = plt.figure(figsize=(7.05, 3.85), constrained_layout=True)
    outer = fig.add_gridspec(3, 1, height_ratios=[0.92, 1.03, 0.38], hspace=0.24)
    top = outer[0].subgridspec(1, 4, wspace=0.25)
    middle = outer[1].subgridspec(1, 4, wspace=0.42)
    limits = ((-0.035, 0.225), (-0.32, 0.075))
    for index, capture in enumerate(p6_caps):
        ax = fig.add_subplot(top[0, index])
        draw_response_axis(ax, capture, chr(ord("a") + index), limits)
        if index == 0:
            ax.set_ylabel("$y$ displacement [m]", labelpad=1.5)
        else:
            ax.set_yticklabels([])

    handles = [
        mpl.lines.Line2D(
            [],
            [],
            color=BLUE,
            lw=1.5,
            marker="o",
            markersize=3.5,
            label=r"Coupled command: $[0.20,-0.18,-0.30]$",
        ),
        mpl.lines.Line2D(
            [],
            [],
            color=VERMILLION,
            lw=1.5,
            marker="o",
            markersize=3.5,
            label=r"Forward-turn command: $[0.35,0.00,0.50]$",
        ),
        mpl.lines.Line2D(
            [],
            [],
            color=GREY,
            lw=0.9,
            ls="--",
            marker="x",
            markersize=3,
            label="Ideal command response",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="outside upper center",
        ncol=3,
        frameon=False,
        columnspacing=1.6,
        handlelength=1.7,
    )

    # Exact shift design matrix.
    ax_matrix = fig.add_subplot(middle[0, 0:2])
    all_texts, all_mags = [], []
    for capture in p6_caps:
        texts, mags = shift_cell_text(capture)
        all_texts.append(texts)
        all_mags.append(mags)
    text_matrix = np.asarray(all_texts, dtype=object).T
    mag_matrix = np.asarray(all_mags, dtype=float).T
    normalized = np.zeros_like(mag_matrix)
    for row_index in range(mag_matrix.shape[0]):
        maximum = np.max(mag_matrix[row_index])
        normalized[row_index] = mag_matrix[row_index] / maximum if maximum else 0.0
    cmap = LinearSegmentedColormap.from_list("shift", ["#FFFFFF", "#D7EAF5", "#75AADB"])
    ax_matrix.imshow(normalized, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for row_index in range(text_matrix.shape[0]):
        for column_index in range(text_matrix.shape[1]):
            ax_matrix.text(
                column_index,
                row_index,
                text_matrix[row_index, column_index],
                ha="center",
                va="center",
                fontsize=5.8,
                color=BLACK,
            )
    ax_matrix.set_xticks(
        np.arange(4),
        [
            "Friction,\nload,\ngain",
            "Gain,\ncoupling",
            "Physical,\nnonlinear",
            "Load,\nCOM,\ngain",
        ],
    )
    ax_matrix.set_yticks(
        np.arange(8),
        [
            r"$\mu_s$",
            r"$\mu_d$",
            "Payload [kg]",
            "COM [mm]",
            "Gain (pre)",
            "Gain (post)",
            r"$|c_{ij}|_{\max}$ (pre)",
            r"$|c_{ij}|_{\max}$ (post)",
        ],
    )
    ax_matrix.tick_params(length=0, pad=2)
    for spine in ax_matrix.spines.values():
        spine.set_visible(True)
        spine.set_color("white")
        spine.set_linewidth(1.0)
    ax_matrix.set_xticks(np.arange(-0.5, 4, 1), minor=True)
    ax_matrix.set_yticks(np.arange(-0.5, 8, 1), minor=True)
    ax_matrix.grid(which="minor", color="white", linewidth=1.3)
    ax_matrix.tick_params(which="minor", bottom=False, left=False)
    ax_matrix.set_title("e  Exact pre$\\to$post shifts", loc="left", fontweight="bold")

    # Early active-recovery effect.
    y = np.arange(4)
    early = np.asarray([row["full_vs_passive_early_rmse_improvement_mean"] for row in ordered])
    early_ci = np.asarray([row["full_vs_passive_early_rmse_improvement_ci95"] for row in ordered])
    ax_early = fig.add_subplot(middle[0, 2])
    ax_early.errorbar(
        early,
        y,
        xerr=np.vstack([early - early_ci[:, 0], early_ci[:, 1] - early]),
        fmt="o",
        color=BLUE,
        ecolor=BLUE,
        capsize=2.3,
        markersize=4.0,
        lw=1.05,
    )
    ax_early.axvline(0, color=BLACK, lw=0.7)
    ax_early.set_yticks(
        y,
        [
            "Friction + load + gain",
            "Gain + coupling",
            "Physical + nonlinear",
            "Load + COM + gain",
        ],
    )
    ax_early.invert_yaxis()
    ax_early.set_xlim(0, 0.0205)
    ax_early.set_xlabel("Passive $-$ GAUGE RMSE")
    ax_early.set_title("f  Early recovery", loc="left", fontweight="bold")
    ax_early.grid(axis="x", color=LIGHT_GREY, lw=0.55)

    # Recovery-selector ablation, averaged across contexts within paired seed.
    methods = ["recovery_d_opt", "recovery_no_task", "recovery_lhs", "recovery_random"]
    method_labels = ["D-opt", "No-task", "LHS", "Random"]
    scenario_effects: list[pd.DataFrame] = []
    for scenario_dir in sorted((SELECTOR_ROOT / "scenarios").iterdir()):
        curve = pd.read_csv(scenario_dir / "recovery_curve.csv")
        early = curve.loc[curve["recovery_trial"].between(4, 9)]
        means = early.groupby(["seed", "method"], as_index=False)["rolling_rmse"].mean()
        pivot = means.pivot(index="seed", columns="method", values="rolling_rmse")
        rows = pd.DataFrame(
            {method: pivot[method] - pivot["full"] for method in methods},
            index=pivot.index,
        )
        scenario_effects.append(rows)
    paired = sum(scenario_effects[1:], scenario_effects[0].copy()) / len(scenario_effects)
    rng = np.random.default_rng(61337)
    selector_rows: list[dict[str, Any]] = []
    for method, label in zip(methods, method_labels, strict=True):
        values = paired[method].to_numpy(dtype=float)
        samples = np.mean(
            rng.choice(values, size=(4000, len(values)), replace=True),
            axis=1,
        )
        selector_rows.append(
            {
                "method": method,
                "label": label,
                "mean_selector_minus_task_ivr_rmse": float(np.mean(values)),
                "ci95": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
                "task_ivr_win_rate": float(np.mean(values > 0.0)),
                "paired_seeds": len(values),
                "contexts_averaged_within_seed": len(scenario_effects),
            }
        )
    PROVENANCE_OUT.mkdir(parents=True, exist_ok=True)
    (PROVENANCE_OUT / "recovery_selector_effects.json").write_text(
        json.dumps(selector_rows, indent=2) + "\n",
        encoding="utf-8",
    )
    selector_mean = np.asarray(
        [row["mean_selector_minus_task_ivr_rmse"] for row in selector_rows],
        dtype=float,
    )
    selector_ci = np.asarray([row["ci95"] for row in selector_rows], dtype=float)
    selector_x = np.arange(len(methods))
    ax_selector = fig.add_subplot(outer[2])
    ax_selector.errorbar(
        selector_x,
        selector_mean,
        yerr=np.vstack([selector_mean - selector_ci[:, 0], selector_ci[:, 1] - selector_mean]),
        fmt="s",
        color=VERMILLION,
        ecolor=VERMILLION,
        capsize=2.3,
        markersize=3.6,
        lw=1.05,
    )
    ax_selector.axhline(0, color=BLACK, lw=0.7)
    ax_selector.set_xticks(selector_x, method_labels)
    ax_selector.set_xlim(-0.45, 3.45)
    ax_selector.set_ylim(0.0, 0.026)
    ax_selector.set_ylabel("Selector $-$ task IVR RMSE")
    ax_selector.set_title(
        "h  Recovery-selector ablation (four contexts averaged within paired seed)",
        loc="left",
        fontweight="bold",
    )
    ax_selector.grid(axis="y", color=LIGHT_GREY, lw=0.55)

    # Absolute terminal accuracy.
    terminal = np.asarray([row["full_final_rmse_mean"] for row in ordered])
    terminal_ci = np.asarray([row["full_final_rmse_ci95"] for row in ordered])
    ax_terminal = fig.add_subplot(middle[0, 3])
    ax_terminal.errorbar(
        terminal,
        y,
        xerr=np.vstack([terminal - terminal_ci[:, 0], terminal_ci[:, 1] - terminal]),
        fmt="D",
        color=GREEN,
        ecolor=GREEN,
        capsize=2.3,
        markersize=3.8,
        lw=1.05,
    )
    ax_terminal.axvline(0.14, color=ORANGE, ls="--", lw=1.0)
    ax_terminal.set_yticks(y, [])
    ax_terminal.invert_yaxis()
    ax_terminal.set_xlim(0.09, 0.142)
    ax_terminal.set_xticks([0.10, 0.12, 0.14])
    ax_terminal.set_xlabel("Terminal RMSE")
    ax_terminal.set_title("g  Absolute gate", loc="left", fontweight="bold")
    ax_terminal.grid(axis="x", color=LIGHT_GREY, lw=0.55)
    ax_terminal.text(0.1395, 3.35, "0.14", ha="right", va="bottom", color=ORANGE, fontsize=6.2)
    finish(fig, "shift_recovery_results")


def write_manifest() -> None:
    sources = [CAPTURE_DIR / name for name in P5_CAPTURE_NAMES + P6_CAPTURE_NAMES]
    sources.extend([P5_SUMMARY, P6_SUMMARY])
    sources.extend(sorted((SELECTOR_ROOT / "scenarios").glob("*/recovery_curve.csv")))
    manifest = {
        "schema_version": 1,
        "figures": {
            "closed_loop_response": {
                "purpose": "Closed-loop response geometry and paired calibration effects",
                "display_seed": 5301,
                "statistical_unit": "20 paired seeds per scenario",
            },
            "shift_recovery_results": {
                "purpose": "Held-out shift construction, response geometry, and recovery effects",
                "display_seed": 10101,
                "statistical_unit": "144 paired seeds per shift in two disjoint blocks",
            },
        },
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sources
        ],
        "constraint": (
            "Trajectory panels use registered capture overlays; effect panels use frozen "
            "multi-seed summaries. No values are digitized from prior raster figures."
        ),
    }
    PROVENANCE_OUT.mkdir(parents=True, exist_ok=True)
    (PROVENANCE_OUT / "simulation_scientific_figure_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    build_p5()
    build_p6()
    write_manifest()


if __name__ == "__main__":
    main()
