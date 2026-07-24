from __future__ import annotations

import numpy as np

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.planning.ivr import IntegratedVariancePlanner
from calibagent.core.planning.task import TaskDistribution
from calibagent.interfaces.types import PriorState


def line_problem() -> tuple[BayesianBasisModel, CandidatePool]:
    reference = np.column_stack([np.linspace(-1, 1, 101), np.zeros(101), np.zeros(101)])
    transformer = BasisTransformer("m1_affine").fit(reference)
    model = BayesianBasisModel(transformer)
    space = CommandSpace(np.asarray([[-1, 1], [-0.5, 0.5], [-0.5, 0.5]]), 1.0)
    pool = CandidatePool(reference, space)
    return model, pool


def test_one_dimensional_planner_selects_endpoint() -> None:
    model, pool = line_problem()
    task = TaskDistribution.uniform(pool.commands)
    selected = IntegratedVariancePlanner(pool).propose(model, task, [], k=1)[0]
    assert abs(selected.command.vx) == 1.0


def test_scores_are_sign_symmetric_for_symmetric_problem() -> None:
    model, pool = line_problem()
    task = TaskDistribution.uniform(pool.commands)
    planner = IntegratedVariancePlanner(pool)
    planner.propose(model, task, [], k=1)
    diagnostics = planner.last_diagnostics
    assert diagnostics is not None
    np.testing.assert_allclose(diagnostics.score, diagnostics.score[::-1], atol=1e-12)


def test_task_weight_moves_candidate_to_weighted_region() -> None:
    model, pool = line_problem()
    weights = np.exp(-0.5 * ((pool.commands[:, 0] - 0.8) / 0.12) ** 2)
    task = TaskDistribution(pool.commands, weights)
    selected = IntegratedVariancePlanner(pool).propose(model, task, [], k=1)[0]
    assert selected.command.vx >= 0.75


def test_risk_cost_demotes_boundary() -> None:
    model, pool = line_problem()
    # Make the intercept known, leaving slope uncertainty; endpoint has higher IV.
    covariance = np.repeat(np.diag([1e-4, 1.0, 1e-4, 1e-4])[None], 3, axis=0)
    model.initialize(PriorState(covariance=covariance))
    task = TaskDistribution.uniform(pool.commands)
    safe = IntegratedVariancePlanner(pool, risk_weight=0.0).propose(model, task, [], k=1)[0]
    cautious = IntegratedVariancePlanner(pool, risk_weight=5.0).propose(model, task, [], k=1)[0]
    assert abs(safe.command.vx) > abs(cautious.command.vx)


def test_greedy_fantasy_batch_has_no_duplicates(candidate_pool, m2_transformer) -> None:
    model = BayesianBasisModel(m2_transformer)
    task = TaskDistribution.uniform(candidate_pool.commands[:50])
    selected = IntegratedVariancePlanner(candidate_pool).propose(model, task, [], k=6)
    commands = np.vstack([candidate.command.as_array() for candidate in selected])
    assert len(np.unique(commands, axis=0)) == 6


def test_sequential_task_support_selection_remains_unique() -> None:
    model, reference_pool = line_problem()
    support = reference_pool.commands[[55, 60, 65, 70, 75, 80, 85]]
    pool = CandidatePool(support, reference_pool.command_space)
    task = TaskDistribution.uniform(support)
    planner = IntegratedVariancePlanner(pool, duplicate_distance=0.02)
    history: list[np.ndarray] = []

    for _ in range(6):
        command = planner.propose(model, task, history, k=1)[0].command.as_array()
        history.append(command)

    assert len(np.unique(np.vstack(history), axis=0)) == 6
    assert all(any(np.array_equal(command, item) for item in support) for command in history)


def test_information_scores_equal_direct_formula() -> None:
    candidate_features = np.asarray([[1.0, -1.0], [1.0, 0.5]])
    task_features = np.asarray([[1.0, 0.2], [1.0, 0.8]])
    weights = np.asarray([0.4, 0.6])
    covariance = np.repeat(np.asarray([[[0.7, 0.1], [0.1, 0.4]]]), 3, axis=0)
    noise = np.asarray([0.1, 0.2, 0.3])
    actual = IntegratedVariancePlanner._information_scores(
        candidate_features, task_features, weights, covariance, noise
    )
    expected = []
    for candidate in candidate_features:
        score = 0.0
        for axis in range(3):
            sigma = covariance[axis]
            reduction = [
                (task @ sigma @ candidate) ** 2 / (noise[axis] + candidate @ sigma @ candidate)
                for task in task_features
            ]
            score += weights @ reduction
        expected.append(score)
    np.testing.assert_allclose(actual, expected)
