from __future__ import annotations

import numpy as np
import pytest
from tests.conftest import observation

from calibagent.core.models.bayesian import BayesianBasisModel


def test_sequential_update_matches_weighted_closed_form(m2_transformer, context) -> None:
    rng = np.random.default_rng(7)
    commands = rng.uniform([-0.8, -0.4, -1.0], [0.8, 0.4, 1.0], size=(24, 3))
    features = m2_transformer.transform(commands)
    true_weights = rng.normal(scale=0.2, size=(3, m2_transformer.n_features))
    targets = features @ true_weights.T
    noise = np.asarray([0.02, 0.03, 0.04])
    measurement = np.asarray([0.01, 0.02, 0.01])
    model = BayesianBasisModel(m2_transformer, prior_scale=1.3, noise_variance=noise)
    for command, target in zip(commands, targets, strict=True):
        model.update(observation(command, target, context, variance=0.0))
    for axis in range(3):
        precision = np.eye(features.shape[1]) / 1.3**2 + features.T @ features / noise[axis]
        covariance = np.linalg.inv(precision)
        mean = covariance @ (features.T @ targets[:, axis] / noise[axis])
        np.testing.assert_allclose(model.posterior_covariances[axis], covariance, atol=1e-10)
        np.testing.assert_allclose(model.posterior_means[axis], mean, atol=1e-10)
    # Exercise weighted measurement covariance separately.
    weighted = BayesianBasisModel(m2_transformer, noise_variance=noise)
    weighted.update_batch(
        commands, targets, np.repeat(np.diag(measurement)[None], len(commands), axis=0)
    )
    assert np.all(np.linalg.eigvalsh(weighted.posterior_covariances) > 0)


def test_covariance_is_psd_and_nonincreasing(m2_transformer, context) -> None:
    model = BayesianBasisModel(m2_transformer)
    before = model.posterior_covariances
    model.update(observation(np.asarray([0.4, 0.1, -0.2]), np.zeros(3), context))
    after = model.posterior_covariances
    for axis in range(3):
        assert np.min(np.linalg.eigvalsh(after[axis])) >= -1e-12
        assert np.max(np.linalg.eigvalsh(after[axis] - before[axis])) <= 1e-10


def test_hypothetical_update_reduces_variance_without_changing_mean(m2_transformer) -> None:
    model = BayesianBasisModel(m2_transformer)
    command = np.asarray([0.5, 0.1, 0.3])
    prediction_before = model.predict(command)
    hypothetical = model.hypothetical_update(command, np.eye(3) * 1e-3)
    prediction_after = hypothetical.predict(command)
    np.testing.assert_allclose(prediction_before.mean, prediction_after.mean, atol=1e-12)
    assert np.all(np.diag(prediction_after.covariance) < np.diag(prediction_before.covariance))
    assert model.posterior_version == 0


def test_serialization_preserves_prediction(m2_transformer, context, tmp_path) -> None:
    model = BayesianBasisModel(m2_transformer)
    model.update(observation(np.asarray([0.2, 0.1, -0.4]), np.asarray([0.1, 0.05, -0.3]), context))
    path = tmp_path / "posterior.npz"
    model.save_state(path)
    restored = BayesianBasisModel.load_state(path)
    command = np.asarray([-0.2, 0.3, 0.7])
    np.testing.assert_allclose(restored.predict(command).mean, model.predict(command).mean)
    np.testing.assert_allclose(
        restored.predict(command).covariance, model.predict(command).covariance
    )
    assert restored.posterior_version == model.posterior_version


def test_invalid_observation_never_updates(m2_transformer, context) -> None:
    model = BayesianBasisModel(m2_transformer)
    with pytest.raises(ValueError, match="invalid"):
        model.update(observation(np.zeros(3), np.zeros(3), context, valid=False))
    assert model.posterior_version == 0
