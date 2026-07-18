from __future__ import annotations

from calibagent.cli.build_figures import build_sample_efficiency_figure, build_uncertainty_heatmap
from calibagent.eval.benchmark import BenchmarkConfig, run_suite


def test_benchmark_writes_complete_artifact_set(tmp_path) -> None:
    config = BenchmarkConfig(
        output_dir=str(tmp_path),
        seeds=(1,),
        methods=("active", "lhs", "random", "sobol", "d_opt", "active_no_task", "dense"),
        families=("affine",),
        max_trials=10,
        seed_design_count=6,
        candidate_count=64,
        task_grid_size=80,
        evaluation_grid_size=100,
        prior_scale=1.0,
        assumed_noise_variance=(0.000625, 0.000324, 0.001225),
        target_rmse=0.1,
        target_uncertainty=0.1,
    )
    statistics = run_suite(config)
    assert "active_vs_lhs" in statistics
    for name in (
        "trial_trace.csv",
        "metrics.csv",
        "paired_statistics.json",
        "resolved_config.json",
        "manifest.json",
        "representative_posterior.npz",
        "planner_diagnostics.csv",
        "uncertainty_slice.csv",
        "dense_oracle_metrics.csv",
    ):
        assert (tmp_path / name).is_file()
    figure = tmp_path / "sample_efficiency.png"
    build_sample_efficiency_figure(tmp_path / "trial_trace.csv", figure)
    assert figure.stat().st_size > 1000
    heatmap = tmp_path / "uncertainty_heatmap.png"
    build_uncertainty_heatmap(tmp_path / "uncertainty_slice.csv", heatmap)
    assert heatmap.stat().st_size > 1000


def test_benchmark_config_parses_task_distribution() -> None:
    config = BenchmarkConfig.from_dict(
        {
            "output_dir": "unused",
            "seeds": [1],
            "methods": ["active"],
            "families": ["affine"],
            "max_trials": 8,
            "seed_design_count": 6,
            "candidate_count": 32,
            "task_grid_size": 32,
            "evaluation_grid_size": 32,
            "prior_scale": 1.0,
            "assumed_noise_variance": [0.1, 0.2, 0.3],
            "target_rmse": 0.1,
            "target_uncertainty": 0.1,
            "task_centers": [[0.2, 0.0, 0.0]],
            "task_scales": [[0.1, 0.1, 0.2]],
            "task_mixture_weights": [1.0],
        }
    )
    assert config.task_centers == ((0.2, 0.0, 0.0),)
    assert config.task_scales == ((0.1, 0.1, 0.2),)
