"""Rebuild the P3 paper-facing sample-efficiency figure from raw traces."""

from __future__ import annotations

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True, help="trial_trace.csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uncertainty-slice", type=Path)
    parser.add_argument("--uncertainty-output", type=Path)
    arguments = parser.parse_args()
    build_sample_efficiency_figure(arguments.registry, arguments.output)
    if arguments.uncertainty_slice is not None:
        uncertainty_output = arguments.uncertainty_output or arguments.output.with_name(
            "uncertainty_heatmap.png"
        )
        build_uncertainty_heatmap(arguments.uncertainty_slice, uncertainty_output)


if __name__ == "__main__":
    main()
