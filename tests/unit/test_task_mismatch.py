from __future__ import annotations

from calibagent.eval.task_mismatch import TaskMismatchConfig, _evaluation_tasks


def _config() -> dict[str, object]:
    return {
        "source_config": "source.json",
        "source_trace": "trace.csv",
        "output_dir": "output",
        "methods": ["active", "active_no_task", "d_opt", "lhs"],
        "baselines": ["active_no_task", "d_opt", "lhs"],
        "budgets": [18, 24],
        "evaluation_grid_size": 32,
        "evaluation_grid_seed": 17,
        "bootstrap_draws": 100,
        "bootstrap_seed": 23,
        "task_centers": [[0.5, 0.0, 0.0], [0.3, 0.0, 0.7]],
        "task_scales": [[0.1, 0.1, 0.2], [0.1, 0.1, 0.2]],
        "distributions": [
            {"id": "declared", "mixture_weights": [0.7, 0.3]},
            {"id": "uniform", "uniform": True},
        ],
        "gates": {},
    }


def test_task_mismatch_config_builds_distinct_normalized_tasks() -> None:
    config = TaskMismatchConfig.from_dict(_config())
    tasks = _evaluation_tasks(config)
    assert set(tasks) == {"declared", "uniform"}
    assert len(tasks["declared"].commands) == 32
    assert tasks["declared"].weights.sum() == 1.0
    assert tasks["uniform"].weights.sum() == 1.0
    assert not (tasks["declared"].weights == tasks["uniform"].weights).all()


def test_task_mismatch_rejects_ambiguous_distribution() -> None:
    value = _config()
    value["distributions"] = [
        {"id": "declared", "uniform": True, "mixture_weights": [0.5, 0.5]}
    ]
    try:
        TaskMismatchConfig.from_dict(value)
    except ValueError as error:
        assert "exactly one weighting rule" in str(error)
    else:
        raise AssertionError("ambiguous distribution was accepted")
