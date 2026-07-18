"""Greedy Bayesian D-optimal design baseline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.planning.candidates import CandidatePool
from calibagent.core.planning.ivr import PlannerDiagnostics
from calibagent.interfaces.types import Candidate, VelocityCommand


class DOptimalPlanner:
    """Select commands maximizing posterior log-determinant reduction."""

    def __init__(
        self,
        candidate_pool: CandidatePool,
        duplicate_distance: float = 0.03,
        duration_s: float = 2.0,
    ) -> None:
        if duplicate_distance < 0:
            raise ValueError("duplicate_distance must be nonnegative")
        self.candidate_pool = candidate_pool
        self.duplicate_distance = duplicate_distance
        self.duration_s = duration_s
        self.last_diagnostics: PlannerDiagnostics | None = None

    def propose(
        self,
        posterior: BayesianBasisModel,
        history: Sequence[NDArray[np.floating[Any]] | VelocityCommand],
        k: int = 1,
    ) -> list[Candidate]:
        commands = self.candidate_pool.commands
        if k < 1 or k > len(commands):
            raise ValueError("invalid batch size")
        features = posterior.transformer.transform(commands)
        normalized = self.candidate_pool.command_space.normalized(commands)
        disallowed = np.zeros(len(commands), dtype=bool)
        history_arrays = [
            item.as_array() if isinstance(item, VelocityCommand) else np.asarray(item)
            for item in history
        ]
        if history_arrays:
            history_matrix = np.vstack(history_arrays)
            distances = np.linalg.norm(
                normalized[:, None, :]
                - self.candidate_pool.command_space.normalized(history_matrix)[None, :, :],
                axis=2,
            )
            disallowed |= np.min(distances, axis=1) < self.duplicate_distance

        covariances = posterior.posterior_covariances
        selected: list[Candidate] = []
        for rank in range(k):
            information = np.zeros(len(commands), dtype=np.float64)
            for axis in range(3):
                leverage = np.einsum("ni,ij,nj->n", features, covariances[axis], features)
                information += np.log1p(leverage / posterior.noise_variance[axis])
            score = information.copy()
            score[disallowed] = -np.inf
            index = int(np.argmax(score))
            if not np.isfinite(score[index]):
                raise RuntimeError("no non-duplicate candidate remains")
            selected.append(
                Candidate(
                    VelocityCommand.from_array(commands[index], self.duration_s),
                    float(score[index]),
                    float(information[index]),
                    0.0,
                    rank=rank,
                )
            )
            disallowed[index] = True
            if self.duplicate_distance > 0:
                distances = np.linalg.norm(normalized - normalized[index], axis=1)
                disallowed |= distances < self.duplicate_distance
            covariances = self._fantasy_update(
                covariances, features[index], posterior.noise_variance
            )
            if rank == 0:
                self.last_diagnostics = PlannerDiagnostics(
                    commands.copy(), information.copy(), np.zeros(len(commands)), score.copy()
                )
        return selected

    @staticmethod
    def _fantasy_update(
        covariances: NDArray[np.float64],
        feature: NDArray[np.float64],
        noise: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        updated = covariances.copy()
        for axis in range(3):
            covariance_feature = updated[axis] @ feature
            denominator = noise[axis] + feature @ covariance_feature
            updated[axis] -= np.outer(covariance_feature, covariance_feature) / denominator
            updated[axis] = 0.5 * (updated[axis] + updated[axis].T)
        return updated
