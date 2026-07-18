from __future__ import annotations

import numpy as np
import pytest

from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.interfaces.types import RobotContext, TrialObservation, VelocityCommand


@pytest.fixture
def context() -> RobotContext:
    return RobotContext("flat", 0.0, 1.0, "trot", "test-session")


@pytest.fixture
def command_space() -> CommandSpace:
    return CommandSpace(np.asarray([[-1.0, 1.0], [-0.5, 0.5], [-1.5, 1.5]]), 1.0)


@pytest.fixture
def candidate_pool(command_space: CommandSpace) -> CandidatePool:
    return CandidatePool.generate(command_space, 128, seed=42)


@pytest.fixture
def m2_transformer(candidate_pool: CandidatePool) -> BasisTransformer:
    return BasisTransformer().fit(candidate_pool.commands)


def observation(
    command: np.ndarray,
    target: np.ndarray,
    context: RobotContext,
    variance: float = 1e-3,
    valid: bool = True,
) -> TrialObservation:
    return TrialObservation(
        VelocityCommand.from_array(command),
        target,
        np.eye(3) * variance,
        (0.0, 2.0),
        context,
        {"valid": valid},
    )
