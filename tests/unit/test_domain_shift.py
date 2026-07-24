from __future__ import annotations

import numpy as np
import pytest

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.shift import DomainShiftConfig, DomainShiftDetector
from calibagent.interfaces.types import PriorState


def test_cusum_ignores_isolated_outlier_and_detects_persistent_shift() -> None:
    detector = DomainShiftDetector(
        DomainShiftConfig(
            allowance=0.5,
            alarm_threshold=4.0,
            minimum_consecutive=3,
            minimum_dwell_trials=3,
        )
    )
    covariance = np.eye(3)
    nominal = [
        detector.update(np.asarray([0.2, 0.1, 0.0]), covariance, trial=trial)
        for trial in range(1, 5)
    ]
    outlier = detector.update(np.asarray([4.0, 0.0, 0.0]), covariance, trial=5)
    recovery = detector.update(np.zeros(3), covariance, trial=6)
    shifted = [
        detector.update(np.asarray([3.0, 3.0, 3.0]), covariance, trial=trial)
        for trial in range(7, 10)
    ]

    assert not any(item.alarm for item in nominal)
    assert not outlier.alarm
    assert recovery.positive_streak == 0
    assert [item.alarm for item in shifted] == [False, False, True]
    assert detector.latched


def test_shift_detector_rejects_bad_covariance_and_trial_order() -> None:
    detector = DomainShiftDetector()
    with pytest.raises(ValueError, match="positive semidefinite"):
        detector.update(np.ones(3), np.diag([1.0, 1.0, -1.0]), trial=1)
    detector.update(np.zeros(3), np.eye(3), trial=1)
    with pytest.raises(ValueError, match="increase strictly"):
        detector.update(np.zeros(3), np.eye(3), trial=1)
    detector.reset()
    assert detector.statistic == 0.0
    assert not detector.latched


def test_shift_detector_tolerates_one_borderline_sample() -> None:
    detector = DomainShiftDetector(
        DomainShiftConfig(
            allowance=0.5,
            alarm_threshold=4.0,
            minimum_consecutive=3,
            minimum_dwell_trials=3,
        )
    )
    covariance = np.eye(3)
    energies = [4.0, 4.0, 1.4, 4.0, 4.0]
    results = [
        detector.update(
            np.full(3, np.sqrt(energy)),
            covariance,
            trial=trial,
        )
        for trial, energy in enumerate(energies, start=1)
    ]

    assert not any(item.alarm for item in results[:4])
    assert results[4].alarm


def test_posterior_inflation_preserves_mean_and_scales_covariance() -> None:
    reference = np.asarray(
        [
            [-0.4, 0.0, 0.0],
            [0.4, 0.0, 0.0],
            [0.0, -0.3, 0.0],
            [0.0, 0.3, 0.0],
            [0.0, 0.0, -0.7],
            [0.0, 0.0, 0.7],
        ]
    )
    transformer = BasisTransformer("m1_affine").fit(reference)
    model = BayesianBasisModel(transformer, prior_scale=0.2)
    model.initialize(PriorState(mean=np.zeros((3, transformer.n_features))))
    means = model.posterior_means
    covariance = model.posterior_covariances
    version = model.posterior_version

    model.inflate_posterior(6.0)

    np.testing.assert_allclose(model.posterior_means, means)
    np.testing.assert_allclose(model.posterior_covariances, covariance * 6.0)
    assert model.posterior_version == version + 1
    with pytest.raises(ValueError, match="> 1"):
        model.inflate_posterior(1.0)
