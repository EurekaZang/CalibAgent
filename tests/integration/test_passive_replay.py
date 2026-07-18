from __future__ import annotations

import numpy as np
from tests.conftest import observation

from calibagent.eval.replay import run_passive_replay_baseline, session_grouped_split
from calibagent.interfaces.types import RobotContext


def make_dense_observations() -> list:
    rng = np.random.default_rng(91)
    matrix = np.asarray([[0.85, 0.25, 0.05], [-0.18, 0.9, 0.08], [0.1, -0.05, 0.8]])
    observations = []
    for session in range(5):
        context = RobotContext("flat", 0.0, 1.0, "trot", f"session-{session}")
        commands = rng.uniform([-1, -0.5, -1.5], [1, 0.5, 1.5], size=(40, 3))
        targets = commands @ matrix.T + rng.normal(scale=0.005, size=commands.shape)
        observations.extend(
            observation(command, target, context)
            for command, target in zip(commands, targets, strict=True)
        )
    return observations


def test_session_split_has_no_identity_leakage() -> None:
    training, validation, _ = session_grouped_split(make_dense_observations(), 0.2, 4)
    training_sessions = {item.context.session_id for item in training}
    validation_sessions = {item.context.session_id for item in validation}
    assert training_sessions.isdisjoint(validation_sessions)


def test_passive_report_shows_coupling_advantage(tmp_path) -> None:
    metrics = run_passive_replay_baseline(make_dense_observations(), tmp_path, budget=30)
    m0 = metrics[(metrics["sampler"] == "lhs") & (metrics["model"] == "M0_diagonal_affine")]
    m1 = metrics[(metrics["sampler"] == "lhs") & (metrics["model"] == "M1_full_affine")]
    assert float(m1["validation_rmse"].iloc[0]) < float(m0["validation_rmse"].iloc[0]) * 0.2
    assert (tmp_path / "manifest.json").is_file()
