"""Rebuild paper-facing figures from versioned experiment evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def build_sample_efficiency_figure(registry: Path, output: Path) -> None:
    trace = pd.read_csv(registry)
    required = {"trial", "method", "family", "seed", "rmse", "integrated_uncertainty"}
    if not required <= set(trace.columns):
        raise ValueError(f"registry is missing columns: {sorted(required - set(trace.columns))}")
    figure, axes = plt.subplots(1, 2, figsize=(8.0, 3.2), constrained_layout=True)
    colors = {
        "active": "#0072B2",
        "lhs": "#D55E00",
        "random": "#999999",
        "sobol": "#009E73",
        "grid": "#CC79A7",
    }
    for method_value, group in trace.groupby("method", sort=True):
        method = str(method_value)
        per_seed = group.groupby(["seed", "trial"], as_index=False)[
            ["rmse", "integrated_uncertainty"]
        ].mean()
        aggregated = per_seed.groupby("trial")
        trial = np.asarray(sorted(per_seed["trial"].unique()))
        color = colors.get(method)
        for axis, metric, label in zip(
            axes,
            ("rmse", "integrated_uncertainty"),
            ("Task-weighted RMSE", "Integrated epistemic variance"),
            strict=True,
        ):
            mean = aggregated[metric].mean().reindex(trial).to_numpy()
            sem = aggregated[metric].sem().reindex(trial).fillna(0).to_numpy()
            axis.plot(trial, mean, label=method, color=color)
            axis.fill_between(trial, mean - 1.96 * sem, mean + 1.96 * sem, color=color, alpha=0.18)
            axis.set_xlabel("Effective trials")
            axis.set_ylabel(label)
            axis.grid(alpha=0.2)
    axes[0].legend(frameon=False)
    axes[1].set_yscale("log")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220)
    plt.close(figure)


def build_uncertainty_heatmap(slice_path: Path, output: Path) -> None:
    frame = pd.read_csv(slice_path)
    required = {"vx", "wz", "epistemic_trace", "error_norm"}
    if not required <= set(frame.columns):
        raise ValueError(
            f"uncertainty slice is missing columns: {sorted(required - set(frame.columns))}"
        )
    uncertainty = frame.pivot(index="wz", columns="vx", values="epistemic_trace")
    error = frame.pivot(index="wz", columns="vx", values="error_norm")
    extent = [
        float(frame["vx"].min()),
        float(frame["vx"].max()),
        float(frame["wz"].min()),
        float(frame["wz"].max()),
    ]
    figure, axes = plt.subplots(1, 2, figsize=(7.4, 3.0), constrained_layout=True)
    for axis, values, title in zip(
        axes,
        (uncertainty.to_numpy(), error.to_numpy()),
        ("Epistemic variance trace", "Forward error norm"),
        strict=True,
    ):
        image = axis.imshow(values, origin="lower", extent=extent, aspect="auto", cmap="viridis")
        axis.set_title(title)
        axis.set_xlabel("$v_x$ command [m/s]")
        axis.set_ylabel("$\\omega$ command [rad/s]")
        figure.colorbar(image, ax=axis, fraction=0.046)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220)
    plt.close(figure)


def build_p6_strong_figure(evidence: Path, output: Path) -> None:
    """Plot preregistered P6 early-recovery effects and terminal accuracy."""

    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((evidence / "scenarios").glob("*/summary.json"))
    ]
    if not rows:
        raise ValueError(f"no P6 scenario summaries under {evidence}")
    labels = [str(row["scenario"]).removeprefix("confirm_").replace("_", "\n") for row in rows]
    effects = np.asarray(
        [row["full_vs_passive_early_rmse_improvement_mean"] for row in rows],
        dtype=float,
    )
    effect_ci = np.asarray(
        [row["full_vs_passive_early_rmse_improvement_ci95"] for row in rows],
        dtype=float,
    )
    final = np.asarray([row["full_final_rmse_mean"] for row in rows], dtype=float)
    final_ci = np.asarray([row["full_final_rmse_ci95"] for row in rows], dtype=float)
    position = np.arange(len(rows))
    figure, axes = plt.subplots(1, 2, figsize=(8.2, 3.25), constrained_layout=True)
    axes[0].errorbar(
        position,
        effects,
        yerr=np.vstack((effects - effect_ci[:, 0], effect_ci[:, 1] - effects)),
        fmt="o",
        color="#0072B2",
        capsize=3,
    )
    axes[0].axhline(0.0, color="#333333", linewidth=0.8)
    axes[0].set_ylabel("Passive minus active early RMSE")
    axes[0].set_title("Active recovery effect (95% bootstrap CI)")
    axes[1].errorbar(
        position,
        final,
        yerr=np.vstack((final - final_ci[:, 0], final_ci[:, 1] - final)),
        fmt="o",
        color="#009E73",
        capsize=3,
    )
    axes[1].axhline(0.14, color="#D55E00", linestyle="--", linewidth=1.0, label="gate")
    axes[1].set_ylabel("Active terminal RMSE")
    axes[1].set_title("Terminal accuracy (95% bootstrap CI)")
    axes[1].legend(frameon=False)
    for axis in axes:
        axis.set_xticks(position, labels)
        axis.grid(axis="y", alpha=0.2)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220)
    plt.close(figure)


def build_p7_strong_figure(evidence: Path, output: Path) -> None:
    """Plot P7 exact success bounds and completion-time noninferiority."""

    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((evidence / "maps").glob("*/summary.json"))
    ]
    if not rows:
        raise ValueError(f"no P7 map summaries under {evidence}")
    labels = [str(row["map"]).removeprefix("replicate_").replace("_", "\n") for row in rows]
    success = np.asarray([row["b8_success_rate"] for row in rows], dtype=float)
    success_ci = np.asarray([row["b8_success_rate_ci95"] for row in rows], dtype=float)
    dense_ratio = np.asarray(
        [row["b8_to_b1_mean_completion_time_ratio"] for row in rows],
        dtype=float,
    )
    dense_upper = np.asarray(
        [row["b8_to_b1_completion_time_ratio_ci95"][1] for row in rows],
        dtype=float,
    )
    matched_upper = np.asarray(
        [
            max(
                comparison["b8_to_baseline_completion_time_ratio_ci95"][1]
                for comparison in row["matched_baseline_comparisons"].values()
            )
            for row in rows
        ],
        dtype=float,
    )
    position = np.arange(len(rows))
    figure, axes = plt.subplots(1, 2, figsize=(9.0, 3.35), constrained_layout=True)
    axes[0].errorbar(
        position,
        success,
        yerr=np.vstack((success - success_ci[:, 0], success_ci[:, 1] - success)),
        fmt="o",
        color="#0072B2",
        capsize=3,
    )
    axes[0].axhline(0.90, color="#D55E00", linestyle="--", linewidth=1.0, label="CI gate")
    axes[0].set_ylim(0.87, 1.01)
    axes[0].set_ylabel("B8 navigation success rate")
    axes[0].set_title("Exact 95% binomial intervals")
    axes[0].legend(frameon=False)
    axes[1].errorbar(
        position - 0.08,
        dense_ratio,
        yerr=np.vstack((np.zeros_like(dense_ratio), dense_upper - dense_ratio)),
        fmt="o",
        color="#009E73",
        capsize=3,
        label="B8 / dense",
    )
    axes[1].scatter(
        position + 0.08,
        matched_upper,
        marker="^",
        color="#CC79A7",
        label="worst matched CI upper",
    )
    axes[1].axhline(1.25, color="#D55E00", linestyle="--", linewidth=1.0, label="CI gate")
    axes[1].set_ylabel("Completion-time ratio")
    axes[1].set_title("Paired bootstrap noninferiority")
    axes[1].legend(frameon=False, fontsize=8)
    for axis in axes:
        axis.set_xticks(position, labels)
        axis.grid(axis="y", alpha=0.2)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, help="P3 trial_trace.csv")
    parser.add_argument("--output", type=Path, help="P3 figure output")
    parser.add_argument("--uncertainty-slice", type=Path)
    parser.add_argument("--uncertainty-output", type=Path)
    parser.add_argument("--p6-evidence", type=Path)
    parser.add_argument("--p6-output", type=Path)
    parser.add_argument("--p7-evidence", type=Path)
    parser.add_argument("--p7-output", type=Path)
    arguments = parser.parse_args()
    built = False
    if arguments.registry is not None:
        if arguments.output is None:
            parser.error("--registry requires --output")
        build_sample_efficiency_figure(arguments.registry, arguments.output)
        built = True
    if arguments.uncertainty_slice is not None:
        if arguments.output is None and arguments.uncertainty_output is None:
            parser.error("--uncertainty-slice requires --uncertainty-output or --output")
        uncertainty_output = arguments.uncertainty_output or arguments.output.with_name(
            "uncertainty_heatmap.png"
        )
        build_uncertainty_heatmap(arguments.uncertainty_slice, uncertainty_output)
        built = True
    if arguments.p6_evidence is not None:
        if arguments.p6_output is None:
            parser.error("--p6-evidence requires --p6-output")
        build_p6_strong_figure(arguments.p6_evidence, arguments.p6_output)
        built = True
    if arguments.p7_evidence is not None:
        if arguments.p7_output is None:
            parser.error("--p7-evidence requires --p7-output")
        build_p7_strong_figure(arguments.p7_evidence, arguments.p7_output)
        built = True
    if not built:
        parser.error("select at least one figure input")


if __name__ == "__main__":
    main()
