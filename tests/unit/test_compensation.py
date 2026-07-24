from __future__ import annotations

import numpy as np
import pytest

from calibagent.core.compensation import ConstrainedInverseCompensator
from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.safety import HardSafetyFilter, SafetyEnvelope
from calibagent.interfaces.types import Candidate, PriorState, RobotState, VelocityCommand


def _identity_model(pool: CandidatePool) -> BayesianBasisModel:
    transformer = BasisTransformer("m1_affine").fit(pool.commands)
    features = transformer.transform(pool.commands)
    identity = np.linalg.lstsq(features, pool.commands, rcond=None)[0].T
    model = BayesianBasisModel(
        transformer,
        prior_scale=0.01,
        noise_variance=[0.001, 0.001, 0.001],
    )
    model.initialize(PriorState(mean=identity))
    return model


def test_constrained_inverse_selects_safe_near_identity_command() -> None:
    space = CommandSpace(
        np.asarray([[-0.4, 0.4], [-0.3, 0.3], [-0.7, 0.7]]),
        max_linear_norm=0.45,
    )
    pool = CandidatePool.generate(space, count=256, seed=81)
    model = _identity_model(pool)
    safety = HardSafetyFilter(
        SafetyEnvelope(
            command_bounds=((-0.4, 0.4), (-0.3, 0.3), (-0.7, 0.7)),
            max_linear_norm=0.45,
            max_coupled_load=1.45,
        )
    )
    compensator = ConstrainedInverseCompensator(
        pool,
        safety,
        regularization=0.01,
        risk_weight=0.0,
    )
    state = RobotState(0.0, (0.0, 0.0), 0.0, 0.0, 0.0, 0.4, (0.0, 0.0, 0.0))

    result = compensator.solve(
        np.asarray([0.25, 0.05, 0.1]),
        model,
        state,
        np.zeros(3),
    )

    assert np.linalg.norm(result.predicted_velocity - np.asarray([0.25, 0.05, 0.1])) < 0.12
    assert safety.evaluate(
        # The selected output remains independently checkable by the hard filter.
        Candidate(
            VelocityCommand.from_array(result.command, duration_s=0.1),
            0.0,
            0.0,
            0.0,
        ),
        state,
        [np.zeros(3)],
    ).accepted


def test_constrained_inverse_rejects_nonfinite_input() -> None:
    space = CommandSpace(np.asarray([[-0.4, 0.4], [-0.3, 0.3], [-0.7, 0.7]]))
    pool = CandidatePool.generate(space, count=32)
    compensator = ConstrainedInverseCompensator(
        pool,
        HardSafetyFilter(),
    )
    state = RobotState(0.0, (0.0, 0.0), 0.0, 0.0, 0.0, 0.4, (0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="finite"):
        compensator.solve(
            np.asarray([np.nan, 0.0, 0.0]),
            _identity_model(pool),
            state,
            np.zeros(3),
        )


def test_robust_inverse_uses_lower_confidence_only_on_selected_axes() -> None:
    space = CommandSpace(
        np.asarray([[-0.4, 0.4], [-0.3, 0.3], [-0.7, 0.7]]),
        max_linear_norm=0.45,
    )
    pool = CandidatePool.generate(space, count=256, seed=87)
    model = _identity_model(pool)
    state = RobotState(
        0.0,
        (0.0, 0.0),
        0.0,
        0.0,
        0.0,
        0.4,
        (0.0, 0.0, 0.0),
    )
    forward_nominal = ConstrainedInverseCompensator(
        pool,
        HardSafetyFilter(),
        risk_weight=0.0,
    ).solve(np.asarray([0.25, 0.0, 0.0]), model, state, np.zeros(3))
    forward_robust = ConstrainedInverseCompensator(
        pool,
        HardSafetyFilter(),
        risk_weight=0.0,
        undertracking_confidence_weights=[0.0, 1.0, 1.0],
    ).solve(np.asarray([0.25, 0.0, 0.0]), model, state, np.zeros(3))
    yaw_nominal = ConstrainedInverseCompensator(
        pool,
        HardSafetyFilter(),
        risk_weight=0.0,
    ).solve(np.asarray([0.0, 0.0, 0.25]), model, state, np.zeros(3))
    yaw_robust = ConstrainedInverseCompensator(
        pool,
        HardSafetyFilter(),
        risk_weight=0.0,
        undertracking_confidence_weights=[0.0, 1.0, 1.0],
    ).solve(np.asarray([0.0, 0.0, 0.25]), model, state, np.zeros(3))

    assert forward_robust.candidate_index == forward_nominal.candidate_index
    assert yaw_robust.predicted_velocity[2] >= yaw_nominal.predicted_velocity[2]


def test_constrained_inverse_limits_commands_on_inactive_axes() -> None:
    space = CommandSpace(
        np.asarray([[-0.4, 0.4], [-0.3, 0.3], [-0.7, 0.7]]),
        max_linear_norm=0.45,
    )
    pool = CandidatePool.generate(space, count=512, seed=89)
    model = _identity_model(pool)
    compensator = ConstrainedInverseCompensator(
        pool,
        HardSafetyFilter(),
        risk_weight=0.0,
        inactive_axis_command_limits=[0.08, 0.06, 0.12],
    )
    state = RobotState(0.0, (0.0, 0.0), 0.0, 0.0, 0.0, 0.4, (0.0, 0.0, 0.0))

    result = compensator.solve(
        np.asarray([0.25, 0.0, 0.0]),
        model,
        state,
        np.zeros(3),
    )

    assert abs(result.command[1]) <= 0.06
    assert abs(result.command[2]) <= 0.12


def test_constrained_inverse_can_preserve_task_axis_signs() -> None:
    space = CommandSpace(
        np.asarray([[-0.4, 0.4], [-0.3, 0.3], [-0.7, 0.7]]),
        max_linear_norm=0.45,
    )
    pool = CandidatePool.generate(space, count=256, seed=91)
    transformer = BasisTransformer("m1_affine").fit(pool.commands)
    features = transformer.transform(pool.commands)
    inverse_identity = np.linalg.lstsq(features, -pool.commands, rcond=None)[0].T
    model = BayesianBasisModel(transformer, prior_scale=0.01)
    model.initialize(PriorState(mean=inverse_identity))
    compensator = ConstrainedInverseCompensator(
        pool,
        HardSafetyFilter(),
        regularization=0.0,
        risk_weight=0.0,
        enforce_axis_signs=True,
    )
    state = RobotState(0.0, (0.0, 0.0), 0.0, 0.0, 0.0, 0.4, (0.0, 0.0, 0.0))
    desired = np.asarray([0.20, -0.10, 0.20])

    result = compensator.solve(desired, model, state, np.zeros(3))

    assert np.all(result.command * desired >= 0.0)
