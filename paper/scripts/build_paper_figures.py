#!/usr/bin/env python3
"""Build publication figures from frozen CalibAgent evidence artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

P1_FOLDS = ROOT / "evidence/p1_real/baseline_fold_metrics.csv"
P1_POOLED = ROOT / "evidence/p1_real/baseline_metrics.csv"
P3 = ROOT / "evidence/p3_main/paired_statistics.json"
P7 = ROOT / "evidence/p7_strong_confirmatory_v2/summary.json"
INPUTS = [P1_FOLDS, P1_POOLED, P3, P7]

BLUE = "#0072B2"
CYAN = "#56B4E9"
GREEN = "#009E73"
ORANGE = "#E69F00"
VERMILLION = "#D55E00"
PURPLE = "#7A5195"
GREY = "#8A8A8A"
LIGHT_GREY = "#E6E6E6"
BLACK = "#222222"

mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 8,
        "axes.titlesize": 9,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
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


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.12,
        1.13,
        label,
        transform=ax.transAxes,
        fontsize=9,
        fontweight="bold",
        va="bottom",
    )


def finish(fig: plt.Figure, stem: str) -> list[Path]:
    outputs = [OUT / f"{stem}.pdf", OUT / f"{stem}.png"]
    fig.savefig(outputs[0], transparent=False)
    fig.savefig(outputs[1], transparent=False, dpi=300)
    plt.close(fig)
    return outputs


def p1_values() -> tuple[list[str], np.ndarray]:
    sessions = ["go2-session-01", "go2-session-02", "go2-session-03"]
    labels = ["S1", "S2", "S3", "Pooled"]
    rows: dict[tuple[str, str], float] = {}
    with P1_FOLDS.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            sampler = row["sampler"]
            model = row["model"]
            if sampler == "raw_command" or sampler == "lhs":
                rows[(row["validation_session"], model)] = float(row["validation_rmse"])
    pooled: dict[str, float] = {}
    with P1_POOLED.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["sampler"] == "raw_command" or row["sampler"] == "lhs":
                pooled[row["model"]] = float(row["validation_rmse"])
    model_ids = ["B0_raw", "M0_diagonal_affine", "M1_full_affine"]
    values = np.asarray(
        [[rows[(session, model)] for session in sessions] + [pooled[model]] for model in model_ids]
    )
    return labels, values


def build_calibration_figure() -> list[Path]:
    p3 = load_json(P3)
    fig, axes = plt.subplots(1, 2, figsize=(7.05, 2.35), constrained_layout=True)

    # (a) Passive hardware model comparison.
    labels, values = p1_values()
    x = np.arange(len(labels))
    width = 0.23
    styles = [
        (GREY, "///", "Raw"),
        (CYAN, "\\\\", "M0 diagonal"),
        (BLUE, "", "M1 coupled"),
    ]
    for i, (color, hatch, name) in enumerate(styles):
        axes[0].bar(
            x + (i - 1) * width,
            values[i],
            width,
            label=name,
            color=color,
            edgecolor=BLACK,
            linewidth=0.55,
            hatch=hatch,
        )
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("Held-out velocity RMSE")
    axes[0].set_ylim(0, 0.092)
    axes[0].grid(axis="y", color=LIGHT_GREY, linewidth=0.55, zorder=0)
    axes[0].legend(frameon=False, ncol=3, loc="upper center", columnspacing=0.8,
                   handlelength=2.0)
    axes[0].set_title("Passive Go2 model check")
    axes[0].text(
        3,
        values[2, 3] + 0.003,
        "−54.5% vs raw",
        ha="center",
        va="bottom",
        fontsize=6.8,
        color=BLUE,
        fontweight="bold",
    )
    panel_label(axes[0], "a")

    # (b) P3 paired trials saved; the interval is for the paired difference.
    comparisons = [
        ("LHS", "active_vs_lhs"),
        ("Random", "active_vs_random"),
        ("Sobol", "active_vs_sobol"),
        ("D-optimal", "active_vs_d_opt"),
        ("No task", "active_vs_active_no_task"),
    ]
    means = np.asarray([p3[key]["mean_paired_trials_saved"] for _, key in comparisons])
    cis = np.asarray([p3[key]["paired_trials_saved_ci95"] for _, key in comparisons])
    y = np.arange(len(comparisons))
    axes[1].errorbar(
        means,
        y,
        xerr=np.vstack([means - cis[:, 0], cis[:, 1] - means]),
        fmt="o",
        color=BLUE,
        ecolor=BLUE,
        capsize=2.5,
        markersize=4.5,
        linewidth=1.1,
    )
    axes[1].axvline(0, color=BLACK, linewidth=0.7)
    axes[1].set_yticks(y, [name for name, _ in comparisons])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Trials saved by task-weighted active design")
    axes[1].set_xlim(-0.5, 15.0)
    axes[1].grid(axis="x", color=LIGHT_GREY, linewidth=0.55)
    axes[1].set_title("Synthetic sample efficiency")
    axes[1].text(
        0.98,
        0.03,
        "Active mean: 18.67 trials\n95% paired bootstrap CI",
        transform=axes[1].transAxes,
        ha="right",
        va="bottom",
        fontsize=6.6,
    )
    panel_label(axes[1], "b")

    return finish(fig, "calibration_evidence")


def build_navigation_figure() -> list[Path]:
    p7 = load_json(P7)
    map_order = [
        "replicate_s_bend",
        "replicate_offset_slalom",
        "replicate_narrow_lane",
        "replicate_double_chicane",
        "replicate_weighted_arc",
        "replicate_extended_lane",
    ]
    map_labels = ["S-bend", "Offset", "Narrow", "Chicane", "W. arc", "Extended"]
    rows = {row["map"]: row for row in p7["maps"]}
    scenarios = [rows[name] for name in map_order]
    methods = ["B0_raw", "B1_dense", "B2_lhs", "B3_sobol", "B4_d_opt", "B5_active_no_task", "B8_full"]
    method_labels = ["Raw", "Dense", "LHS", "Sobol", "D-opt", "No task", "Full"]

    fig, axes = plt.subplots(1, 3, figsize=(7.05, 2.55), constrained_layout=True)
    success = np.asarray(
        [[row["method_summaries"][method]["success_rate"] for method in methods] for row in scenarios]
    )
    image = axes[0].imshow(success, vmin=0.0, vmax=1.0, cmap="cividis", aspect="auto")
    axes[0].set_xticks(np.arange(len(methods)), method_labels, rotation=55, ha="right")
    axes[0].set_yticks(np.arange(len(map_labels)), map_labels)
    for i in range(success.shape[0]):
        for j in range(success.shape[1]):
            value = success[i, j]
            color = "white" if value < 0.55 else "black"
            axes[0].text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=5.7, color=color)
    cbar = fig.colorbar(image, ax=axes[0], fraction=0.046, pad=0.03)
    cbar.set_label("Success rate", fontsize=7)
    cbar.ax.tick_params(labelsize=6)
    axes[0].set_title("Six-map success")
    panel_label(axes[0], "a")

    y = np.arange(len(scenarios))
    gain = np.asarray([row["b8_vs_b0_completion_time_improvement_mean_s"] for row in scenarios])
    gain_ci = np.asarray([row["b8_vs_b0_completion_time_improvement_ci95_s"] for row in scenarios])
    axes[1].errorbar(
        gain,
        y,
        xerr=np.vstack([gain - gain_ci[:, 0], gain_ci[:, 1] - gain]),
        fmt="o",
        color=BLUE,
        ecolor=BLUE,
        capsize=2.5,
        markersize=4.5,
        linewidth=1.1,
    )
    axes[1].axvline(0, color=BLACK, linewidth=0.7)
    axes[1].set_yticks(y, map_labels)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Full − raw time gain (s)")
    axes[1].set_xlim(20, 37)
    axes[1].grid(axis="x", color=LIGHT_GREY, linewidth=0.55)
    axes[1].set_title("Paired completion-time gain")
    panel_label(axes[1], "b")

    ratio = np.asarray([row["b8_to_b1_mean_completion_time_ratio"] for row in scenarios])
    ratio_ci = np.asarray([row["b8_to_b1_completion_time_ratio_ci95"] for row in scenarios])
    axes[2].errorbar(
        ratio,
        y,
        xerr=np.vstack([ratio - ratio_ci[:, 0], ratio_ci[:, 1] - ratio]),
        fmt="D",
        color=GREEN,
        ecolor=GREEN,
        capsize=2.5,
        markersize=4.3,
        linewidth=1.1,
    )
    axes[2].axvline(1.0, color=BLACK, linewidth=0.7, label="Equal time")
    axes[2].axvline(1.25, color=VERMILLION, linestyle="--", linewidth=1.0, label="NI margin")
    axes[2].set_yticks(y, map_labels)
    axes[2].invert_yaxis()
    axes[2].set_xlabel("Full / dense time ratio")
    axes[2].set_xlim(0.88, 1.27)
    axes[2].grid(axis="x", color=LIGHT_GREY, linewidth=0.55)
    axes[2].legend(frameon=False, loc="lower right")
    axes[2].set_title("Dense-budget noninferiority")
    panel_label(axes[2], "c")

    fig.text(0.5, -0.015, "All B8 collision counts were 0/72 on every map.", ha="center", fontsize=7)
    return finish(fig, "navigation_results")


def main() -> None:
    for path in INPUTS:
        if not path.is_file():
            raise FileNotFoundError(path)
    outputs = build_calibration_figure() + build_navigation_figure()
    script_path = Path(__file__).resolve()
    manifest = {
        "schema_version": "1.0",
        "generator": str(script_path.relative_to(ROOT)),
        "inputs": {str(path.relative_to(ROOT)): sha256(path) for path in INPUTS},
        "outputs": {str(path.relative_to(ROOT)): sha256(path) for path in outputs},
        "notes": [
            "All plotted values are parsed from the listed frozen artifacts.",
            "P3 intervals are paired bootstrap intervals for trials saved.",
            "P7 intervals are the registered intervals stored in summary.json.",
        ],
    }
    (OUT / "quantitative_figure_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
