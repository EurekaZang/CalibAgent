from __future__ import annotations

import numpy as np

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.planning.d_optimal import DOptimalPlanner


def test_d_optimal_proposes_unique_information_gaining_batch(
    candidate_pool, m2_transformer
) -> None:
    model = BayesianBasisModel(m2_transformer)
    planner = DOptimalPlanner(candidate_pool)
    selected = planner.propose(model, history=[], k=3)
    commands = np.vstack([candidate.command.as_array() for candidate in selected])
    assert len(np.unique(commands, axis=0)) == 3
    assert all(candidate.information_gain > 0 for candidate in selected)
    assert planner.last_diagnostics is not None


def test_d_optimal_avoids_history(candidate_pool, m2_transformer) -> None:
    model = BayesianBasisModel(m2_transformer)
    planner = DOptimalPlanner(candidate_pool, duplicate_distance=0.01)
    first = planner.propose(model, history=[])[0].command.as_array()
    second = planner.propose(model, history=[first])[0].command.as_array()
    assert not np.allclose(first, second)
