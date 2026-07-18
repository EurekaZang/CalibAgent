from __future__ import annotations

import numpy as np
import pytest

from calibagent.core.models.features import BasisTransformer, FeatureStandardizer


def test_m2_feature_names_and_shape(m2_transformer) -> None:
    assert m2_transformer.n_features == 13
    transformed = m2_transformer.transform(np.zeros((4, 3)))
    assert transformed.shape == (4, 13)
    np.testing.assert_allclose(transformed[:, 0], 1.0)


def test_hinges_are_directional() -> None:
    transformer = BasisTransformer()
    positive = transformer.raw_features(np.asarray([0.5, 0.0, 0.0]))
    negative = transformer.raw_features(np.asarray([-0.5, 0.0, 0.0]))
    assert positive[7] > 0 and positive[8] == 0
    assert negative[7] == 0 and negative[8] > 0


def test_standardizer_requires_fit() -> None:
    with pytest.raises(RuntimeError):
        FeatureStandardizer().transform(np.ones((2, 3)))


def test_transformer_serialization_preserves_features(m2_transformer) -> None:
    restored = BasisTransformer.from_dict(m2_transformer.to_dict())
    commands = np.asarray([[0.2, -0.1, 0.5], [-0.4, 0.2, -0.7]])
    np.testing.assert_allclose(restored.transform(commands), m2_transformer.transform(commands))
