"""Exact task-weighted integrated variance reduction with greedy fantasy batches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.planning.candidates import CandidatePool
from calibagent.core.planning.task import TaskDistribution
from calibagent.interfaces.types import Candidate, VelocityCommand


@dataclass(frozen=True)
class PlannerDiagnostics:
    commands: NDArray[np.float64]
    information_gain: NDArray[np.float64]
    cost: NDArray[np.float64]
    score: NDArray[np.float64]


class IntegratedVariancePlanner:
    def __init__(
        self,
        candidate_pool: CandidatePool | None = None,
        risk_weight: float = 0.0,
        distance_weight: float = 0.0,
        duplicate_distance: float = 0.03,
        duration_s: float = 2.0,
    ) -> None:
        if risk_weight < 0 or distance_weight < 0 or duplicate_distance < 0:
            raise ValueError("planner costs and distance must be nonnegative")
        self.candidate_pool = candidate_pool
        self.risk_weight = risk_weight
        self.distance_weight = distance_weight
        self.duplicate_distance = duplicate_distance
        self.duration_s = duration_s
        self.last_diagnostics: PlannerDiagnostics | None = None

    @staticmethod
    def _information_scores(
        candidate_features: NDArray[np.float64],
        task_features: NDArray[np.float64],
        task_weights: NDArray[np.float64],
        covariances: NDArray[np.float64],
        noise_variance: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        scores = np.zeros(len(candidate_features))
        for axis in range(3):
            covariance = covariances[axis]
            cross = task_features @ covariance @ candidate_features.T
            denominator = noise_variance[axis] + np.einsum(
                "ni,ij,nj->n", candidate_features, covariance, candidate_features
            )
            scores += np.sum(task_weights[:, None] * cross**2, axis=0) / np.maximum(
                denominator, 1e-15
            )
        return scores

    @staticmethod
    def _fantasy_covariance_update(
        covariances: NDArray[np.float64], feature: NDArray[np.float64], noise: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        updated = covariances.copy()
        for axis in range(3):
            covariance_feature = updated[axis] @ feature
            denominator = noise[axis] + feature @ covariance_feature
            updated[axis] -= np.outer(covariance_feature, covariance_feature) / denominator
            updated[axis] = 0.5 * (updated[axis] + updated[axis].T)
        return updated

    def propose(
        self,
        posterior: BayesianBasisModel,
        task_distribution: TaskDistribution,
        history: Sequence[NDArray[np.floating[Any]] | VelocityCommand],
        k: int = 1,
    ) -> list[Candidate]:
        if self.candidate_pool is None:
            raise RuntimeError("candidate_pool is required")
        if k < 1 or k > len(self.candidate_pool.commands):
            raise ValueError("invalid batch size")
        commands = self.candidate_pool.commands
        candidate_features = posterior.transformer.transform(commands)
        task_features = posterior.transformer.transform(task_distribution.commands)
        normalized = self.candidate_pool.command_space.normalized(commands)
        risk = np.linalg.norm(normalized, axis=1) / np.sqrt(3.0)
        execution_cost = np.linalg.norm(normalized[:, :2], axis=1)
        cost = self.risk_weight * risk + self.distance_weight * execution_cost
        history_arrays = [
            item.as_array() if isinstance(item, VelocityCommand) else np.asarray(item)
            for item in history
        ]
        disallowed = np.zeros(len(commands), dtype=bool)
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
            information = self._information_scores(
                candidate_features,
                task_features,
                task_distribution.weights,
                covariances,
                posterior.noise_variance,
            )
            score = information - cost
            score[disallowed] = -np.inf
            index = int(np.argmax(score))
            if not np.isfinite(score[index]):
                raise RuntimeError("no non-duplicate candidate remains")
            command = VelocityCommand.from_array(commands[index], duration_s=self.duration_s)
            selected.append(
                Candidate(
                    command,
                    float(score[index]),
                    float(information[index]),
                    float(cost[index]),
                    rank=rank,
                )
            )
            disallowed[index] = True
            if self.duplicate_distance > 0:
                distance = np.linalg.norm(normalized - normalized[index], axis=1)
                disallowed |= distance < self.duplicate_distance
            covariances = self._fantasy_covariance_update(
                covariances, candidate_features[index], posterior.noise_variance
            )
            if rank == 0:
                self.last_diagnostics = PlannerDiagnostics(
                    commands.copy(), information.copy(), cost.copy(), score.copy()
                )
        return selected
