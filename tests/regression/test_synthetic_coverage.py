from __future__ import annotations

import numpy as np

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.samplers import sobol
from calibagent.eval.metrics import interval_coverage
from calibagent.eval.synthetic import SyntheticDistortion, make_observation


def test_affine_synthetic_coverage_is_reasonable() -> None:
    bounds = np.asarray([[-1, 1], [-0.5, 0.5], [-1.5, 1.5]], dtype=float)
    reference = sobol(512, bounds, 8)
    transformer = BasisTransformer("m1_affine").fit(reference)
    distortion = SyntheticDistortion.from_seed("affine", 10)
    model = BayesianBasisModel(
        transformer, prior_scale=1.0, noise_variance=distortion.base_noise_std**2
    )
    rng = np.random.default_rng(123)
    for trial, command in enumerate(sobol(60, bounds, 21)):
        model.update(make_observation(distortion, command, rng, trial))
    evaluation = sobol(1000, bounds, 99)
    noisy_rng = np.random.default_rng(456)
    noisy_targets, _ = distortion.sample(evaluation, noisy_rng)
    mean, variance = model.predict_batch(evaluation)
    coverage, _ = interval_coverage(mean, variance, noisy_targets)
    assert 0.88 <= coverage <= 0.99


def test_synthetic_noise_is_charged_exactly_once() -> None:
    distortion = SyntheticDistortion.from_seed("heteroscedastic", 10)
    command = np.asarray([0.7, -0.2, 0.8])
    observation = make_observation(distortion, command, np.random.default_rng(123), 0)
    effective = distortion.base_noise_std**2 + np.diag(observation.covariance)
    np.testing.assert_allclose(effective, distortion.noise_std(command) ** 2)
