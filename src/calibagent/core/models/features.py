"""Deterministic M0/M1/M2 basis construction and leakage-safe standardization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass
class FeatureStandardizer:
    """Column standardizer that preserves the intercept exactly."""

    mean_: FloatArray | None = None
    scale_: FloatArray | None = None

    def fit(self, features: NDArray[np.floating[Any]]) -> FeatureStandardizer:
        array = np.asarray(features, dtype=np.float64)
        if array.ndim != 2 or array.shape[1] < 1:
            raise ValueError("features must be a non-empty 2D array")
        mean = np.mean(array, axis=0)
        scale = np.std(array, axis=0)
        mean[0], scale[0] = 0.0, 1.0
        scale[scale < 1e-12] = 1.0
        self.mean_, self.scale_ = mean, scale
        return self

    def transform(self, features: NDArray[np.floating[Any]]) -> FloatArray:
        if self.mean_ is None or self.scale_ is None:
            raise RuntimeError("standardizer must be fitted before transform")
        array = np.asarray(features, dtype=np.float64)
        return (array - self.mean_) / self.scale_

    def to_dict(self) -> dict[str, list[float]]:
        if self.mean_ is None or self.scale_ is None:
            raise RuntimeError("cannot serialize an unfitted standardizer")
        return {"mean": self.mean_.tolist(), "scale": self.scale_.tolist()}

    @classmethod
    def from_dict(cls, value: dict[str, list[float]]) -> FeatureStandardizer:
        return cls(
            np.asarray(value["mean"], dtype=np.float64),
            np.asarray(value["scale"], dtype=np.float64),
        )


class BasisTransformer:
    """Feature map fixed before sequential calibration begins.

    The standardizer must be fitted on a predeclared command-space reference,
    never on held-out outcomes. This keeps active/passive comparisons free from
    outcome leakage while ensuring comparable prior scales.
    """

    VALID_FEATURE_SETS: ClassVar[set[str]] = {"m1_affine", "m2_affine_cross_hinge"}

    def __init__(
        self,
        feature_set: str = "m2_affine_cross_hinge",
        hinge_thresholds: tuple[float, float, float] = (0.15, 0.10, 0.25),
    ) -> None:
        if feature_set not in self.VALID_FEATURE_SETS:
            raise ValueError(f"unknown feature set: {feature_set}")
        self.feature_set = feature_set
        self.hinge_thresholds = hinge_thresholds
        self.standardizer = FeatureStandardizer()

    @property
    def feature_names(self) -> tuple[str, ...]:
        base = ("intercept", "vx", "vy", "wz")
        if self.feature_set == "m1_affine":
            return base
        return (
            *base,
            "vx*vy",
            "vx*wz",
            "vy*wz",
            "hinge_vx_pos",
            "hinge_vx_neg",
            "hinge_vy_pos",
            "hinge_vy_neg",
            "hinge_wz_pos",
            "hinge_wz_neg",
        )

    @property
    def n_features(self) -> int:
        return len(self.feature_names)

    def raw_features(self, commands: NDArray[np.floating[Any]]) -> FloatArray:
        u = np.asarray(commands, dtype=np.float64)
        one_dimensional = u.ndim == 1
        if one_dimensional:
            u = u[None, :]
        if u.ndim != 2 or u.shape[1] != 3:
            raise ValueError(f"commands must have shape (n, 3), got {u.shape}")
        columns: list[FloatArray] = [np.ones(len(u)), u[:, 0], u[:, 1], u[:, 2]]
        if self.feature_set == "m2_affine_cross_hinge":
            columns.extend([u[:, 0] * u[:, 1], u[:, 0] * u[:, 2], u[:, 1] * u[:, 2]])
            for axis, threshold in enumerate(self.hinge_thresholds):
                columns.extend(
                    [
                        np.maximum(0.0, u[:, axis] - threshold),
                        np.maximum(0.0, -u[:, axis] - threshold),
                    ]
                )
        output = np.column_stack(columns)
        return output[0] if one_dimensional else output

    def fit(self, command_reference: NDArray[np.floating[Any]]) -> BasisTransformer:
        features = self.raw_features(command_reference)
        if features.ndim != 2:
            raise ValueError("command_reference must contain multiple commands")
        self.standardizer.fit(features)
        return self

    def transform(self, commands: NDArray[np.floating[Any]]) -> FloatArray:
        raw = self.raw_features(commands)
        one_dimensional = raw.ndim == 1
        transformed = self.standardizer.transform(raw[None, :] if one_dimensional else raw)
        return transformed[0] if one_dimensional else transformed

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_set": self.feature_set,
            "hinge_thresholds": list(self.hinge_thresholds),
            "standardizer": self.standardizer.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> BasisTransformer:
        thresholds = cast(list[float], value["hinge_thresholds"])
        standardizer = cast(dict[str, list[float]], value["standardizer"])
        transformer = cls(
            str(value["feature_set"]),
            (float(thresholds[0]), float(thresholds[1]), float(thresholds[2])),
        )
        transformer.standardizer = FeatureStandardizer.from_dict(standardizer)
        return transformer
