"""Sequential three-output Bayesian linear regression for the M2 basis."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from calibagent.core.models.features import BasisTransformer
from calibagent.interfaces.types import (
    PredictiveDistribution,
    PriorState,
    RobotContext,
    TrialObservation,
)

FloatArray = NDArray[np.float64]


class BayesianBasisModel:
    """Independent-output BLR with per-observation measurement uncertainty."""

    model_id = "M2_basis_blr"

    def __init__(
        self,
        transformer: BasisTransformer,
        prior_scale: float = 1.0,
        noise_variance: NDArray[np.floating[Any]] | Sequence[float] = (0.01, 0.01, 0.01),
    ) -> None:
        if prior_scale <= 0:
            raise ValueError("prior_scale must be positive")
        noise = np.asarray(noise_variance, dtype=np.float64)
        if noise.shape != (3,) or np.any(noise <= 0):
            raise ValueError("noise_variance must contain three positive values")
        # Fitted standardizer validation happens here, before any posterior state exists.
        transformer.transform(np.zeros(3))
        self.transformer = transformer
        self.prior_scale = float(prior_scale)
        self.noise_variance = noise
        self.posterior_version = 0
        self.initialize(PriorState())

    def initialize(self, prior: PriorState) -> None:
        size = self.transformer.n_features
        if prior.mean is None:
            means = np.zeros((3, size), dtype=np.float64)
        else:
            means = np.asarray(prior.mean, dtype=np.float64)
            if means.shape != (3, size):
                raise ValueError(f"prior mean must have shape {(3, size)}")
        if prior.covariance is None:
            covariances = np.repeat((np.eye(size) * self.prior_scale**2)[None, :, :], 3, axis=0)
        else:
            covariance = np.asarray(prior.covariance, dtype=np.float64)
            if covariance.shape == (size, size):
                covariances = np.repeat(covariance[None, :, :], 3, axis=0)
            elif covariance.shape == (3, size, size):
                covariances = covariance.copy()
            else:
                raise ValueError("prior covariance has incompatible shape")
        self._precision = np.asarray([np.linalg.inv(cov) for cov in covariances])
        self._eta = np.einsum("aij,aj->ai", self._precision, means)
        self._means = means.copy()
        self._covariances = covariances.copy()
        self.posterior_version = 0

    @property
    def posterior_means(self) -> FloatArray:
        return self._means.copy()

    @property
    def posterior_covariances(self) -> FloatArray:
        return self._covariances.copy()

    def _update_feature(
        self, feature: FloatArray, target: FloatArray, variances: FloatArray
    ) -> None:
        outer = np.outer(feature, feature)
        for axis in range(3):
            weight = 1.0 / variances[axis]
            self._precision[axis] += weight * outer
            self._eta[axis] += weight * feature * target[axis]
            self._covariances[axis] = np.linalg.inv(self._precision[axis])
            self._covariances[axis] = 0.5 * (self._covariances[axis] + self._covariances[axis].T)
            self._means[axis] = self._covariances[axis] @ self._eta[axis]

    def update(self, obs: TrialObservation) -> None:
        if not obs.valid:
            raise ValueError("invalid observations must not update the posterior")
        feature = self.transformer.transform(obs.command.as_array())
        variances = self.noise_variance + np.maximum(np.diag(obs.covariance), 0.0)
        self._update_feature(feature, obs.mean_velocity, variances)
        self.posterior_version += 1

    def update_batch(
        self,
        commands: NDArray[np.floating[Any]],
        targets: NDArray[np.floating[Any]],
        measurement_covariances: NDArray[np.floating[Any]] | None = None,
    ) -> None:
        u = np.asarray(commands, dtype=np.float64)
        y = np.asarray(targets, dtype=np.float64)
        if u.ndim != 2 or u.shape[1] != 3 or y.shape != u.shape:
            raise ValueError("commands and targets must both have shape (n, 3)")
        if measurement_covariances is None:
            covariances = np.zeros((len(u), 3, 3))
        else:
            covariances = np.asarray(measurement_covariances, dtype=np.float64)
            if covariances.shape != (len(u), 3, 3):
                raise ValueError("measurement_covariances must have shape (n, 3, 3)")
        for command, target, covariance in zip(u, y, covariances, strict=True):
            feature = self.transformer.transform(command)
            self._update_feature(feature, target, self.noise_variance + np.diag(covariance))
            self.posterior_version += 1

    def predict(
        self, command: NDArray[np.floating[Any]], context: RobotContext | None = None
    ) -> PredictiveDistribution:
        del context
        feature = self.transformer.transform(command)
        mean = self._means @ feature
        epistemic = np.einsum("i,aij,j->a", feature, self._covariances, feature)
        covariance = np.diag(np.maximum(epistemic + self.noise_variance, 0.0))
        return PredictiveDistribution(mean, covariance, self.model_id, self.posterior_version)

    def predict_batch(
        self, commands: NDArray[np.floating[Any]], include_noise: bool = True
    ) -> tuple[FloatArray, FloatArray]:
        features = self.transformer.transform(commands)
        means = features @ self._means.T
        variances = np.column_stack(
            [
                np.einsum("ni,ij,nj->n", features, covariance, features)
                for covariance in self._covariances
            ]
        )
        if include_noise:
            variances += self.noise_variance
        return means, np.maximum(variances, 0.0)

    def hypothetical_update(
        self,
        command: NDArray[np.floating[Any]],
        measurement_cov: NDArray[np.floating[Any]],
    ) -> BayesianBasisModel:
        clone = copy.deepcopy(self)
        feature = clone.transformer.transform(command)
        covariance = np.asarray(measurement_cov, dtype=np.float64)
        if covariance.shape != (3, 3):
            raise ValueError("measurement_cov must have shape (3, 3)")
        # The covariance update is independent of the unobserved target. Using
        # the current mean leaves eta/mean coherent without fantasy outcome bias.
        target = clone._means @ feature
        clone._update_feature(feature, target, clone.noise_variance + np.diag(covariance))
        clone.posterior_version += 1
        return clone

    def inflate_posterior(self, factor: float) -> None:
        """Inflate epistemic covariance while preserving the posterior mean.

        This is the warm-start response to a confirmed context shift.  The
        information form is rebuilt so subsequent Bayesian updates remain
        coherent; merely multiplying the exposed covariance would not do so.
        """

        if not np.isfinite(factor) or factor <= 1.0:
            raise ValueError("posterior inflation factor must be finite and > 1")
        self._covariances *= float(factor)
        self._precision = np.asarray(
            [np.linalg.inv(covariance) for covariance in self._covariances]
        )
        self._eta = np.einsum("aij,aj->ai", self._precision, self._means)
        self.posterior_version += 1

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "model_id": self.model_id,
            "prior_scale": self.prior_scale,
            "posterior_version": self.posterior_version,
            "transformer": self.transformer.to_dict(),
        }
        np.savez_compressed(
            path,
            means=self._means,
            covariances=self._covariances,
            precision=self._precision,
            eta=self._eta,
            noise_variance=self.noise_variance,
            metadata=np.asarray(json.dumps(metadata)),
        )

    @classmethod
    def load_state(cls, path: Path) -> BayesianBasisModel:
        with np.load(path, allow_pickle=False) as state:
            metadata = json.loads(str(state["metadata"]))
            transformer = BasisTransformer.from_dict(metadata["transformer"])
            model = cls(transformer, metadata["prior_scale"], state["noise_variance"])
            model._means = state["means"].copy()
            model._covariances = state["covariances"].copy()
            model._precision = state["precision"].copy()
            model._eta = state["eta"].copy()
            model.posterior_version = int(metadata["posterior_version"])
        return model
