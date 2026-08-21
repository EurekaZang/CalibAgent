"""Small dependency-light Bayesian velocity model used by the P8 field runtime."""

import json

import numpy as np


class Basis:
    def __init__(self, feature_set, reference):  # type: (str, np.ndarray) -> None
        if feature_set not in ("m1_affine", "m2_affine_cross_hinge"):
            raise ValueError(f"unknown feature set: {feature_set}")
        self.feature_set = feature_set
        raw = self.raw(np.asarray(reference, dtype=np.float64))
        self.mean = raw.mean(axis=0)
        self.scale = raw.std(axis=0)
        self.mean[0] = 0.0
        self.scale[0] = 1.0
        self.scale[self.scale < 1e-12] = 1.0

    def raw(self, commands):  # type: (np.ndarray) -> np.ndarray
        values = np.asarray(commands, dtype=np.float64)
        one = values.ndim == 1
        if one:
            values = values.reshape(1, 3)
        columns = [np.ones(len(values)), values[:, 0], values[:, 1], values[:, 2]]
        if self.feature_set == "m2_affine_cross_hinge":
            columns.extend(
                (
                    values[:, 0] * values[:, 1],
                    values[:, 0] * values[:, 2],
                    values[:, 1] * values[:, 2],
                )
            )
            for axis, threshold in enumerate((0.15, 0.10, 0.25)):
                columns.extend(
                    (
                        np.maximum(0.0, values[:, axis] - threshold),
                        np.maximum(0.0, -values[:, axis] - threshold),
                    )
                )
        output = np.column_stack(columns)
        return output[0] if one else output

    def transform(self, commands):  # type: (np.ndarray) -> np.ndarray
        return (self.raw(commands) - self.mean) / self.scale

    def state(self):  # type: () -> Dict[str, Any]
        return {
            "feature_set": self.feature_set,
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
        }

    @classmethod
    def from_state(cls, state):  # type: (Dict[str, Any]) -> "Basis"
        obj = cls.__new__(cls)
        obj.feature_set = str(state["feature_set"])
        obj.mean = np.asarray(state["mean"], dtype=np.float64)
        obj.scale = np.asarray(state["scale"], dtype=np.float64)
        return obj


class VelocityModel:
    """Three independent Bayesian linear regressors in information form."""

    def __init__(
        self, feature_set, reference, prior_scale=1.0, noise_variance=(0.0025, 0.0025, 0.005)
    ):
        # type: (str, np.ndarray, float, Sequence[float]) -> None
        self.basis = Basis(feature_set, reference)
        self.prior_scale = float(prior_scale)
        self.noise = np.asarray(noise_variance, dtype=np.float64)
        features = self.basis.transform(reference)
        identity_mean = np.linalg.lstsq(
            features, np.asarray(reference, dtype=np.float64), rcond=None
        )[0].T
        self.means = identity_mean
        size = features.shape[1]
        self.covariances = np.repeat((np.eye(size) * self.prior_scale**2)[None, :, :], 3, axis=0)
        self.precision = np.asarray([np.linalg.inv(value) for value in self.covariances])
        self.eta = np.einsum("aij,aj->ai", self.precision, self.means)
        self.posterior_version = 0

    def predict(self, command):  # type: (Sequence[float]) -> Tuple[np.ndarray, np.ndarray]
        feature = self.basis.transform(np.asarray(command, dtype=np.float64))
        mean = self.means.dot(feature)
        variance = (
            np.asarray([feature.dot(cov).dot(feature) for cov in self.covariances]) + self.noise
        )
        return mean, np.maximum(variance, 0.0)

    def predict_batch(self, commands):  # type: (np.ndarray) -> Tuple[np.ndarray, np.ndarray]
        features = self.basis.transform(np.asarray(commands, dtype=np.float64))
        means = features.dot(self.means.T)
        variances = np.column_stack(
            [np.einsum("ni,ij,nj->n", features, cov, features) for cov in self.covariances]
        )
        return means, np.maximum(variances + self.noise, 0.0)

    def update(self, command, measured, covariance):  # type: (Sequence[float], Sequence[float], np.ndarray) -> None
        feature = self.basis.transform(np.asarray(command, dtype=np.float64))
        target = np.asarray(measured, dtype=np.float64)
        variances = self.noise + np.maximum(np.diag(np.asarray(covariance, dtype=np.float64)), 0.0)
        outer = np.outer(feature, feature)
        for axis in range(3):
            weight = 1.0 / variances[axis]
            self.precision[axis] += weight * outer
            self.eta[axis] += weight * feature * target[axis]
            self.covariances[axis] = np.linalg.inv(self.precision[axis])
            self.means[axis] = self.covariances[axis].dot(self.eta[axis])
        self.posterior_version += 1

    def inflate(self, factor):  # type: (float) -> None
        if factor <= 1.0:
            raise ValueError("inflation factor must be > 1")
        self.covariances *= float(factor)
        self.precision = np.asarray([np.linalg.inv(value) for value in self.covariances])
        self.eta = np.einsum("aij,aj->ai", self.precision, self.means)
        self.posterior_version += 1

    def save(self, path):  # type: (Path) -> None
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "basis": self.basis.state(),
            "prior_scale": self.prior_scale,
            "posterior_version": self.posterior_version,
        }
        np.savez_compressed(
            path,
            means=self.means,
            covariances=self.covariances,
            precision=self.precision,
            eta=self.eta,
            noise=self.noise,
            metadata=np.asarray(json.dumps(metadata)),
        )

    @classmethod
    def load(cls, path):  # type: (Path) -> "VelocityModel"
        with np.load(path, allow_pickle=False) as state:
            metadata = json.loads(str(state["metadata"]))
            obj = cls.__new__(cls)
            obj.basis = Basis.from_state(metadata["basis"])
            obj.prior_scale = float(metadata["prior_scale"])
            obj.posterior_version = int(metadata["posterior_version"])
            obj.means = state["means"].copy()
            obj.covariances = state["covariances"].copy()
            obj.precision = state["precision"].copy()
            obj.eta = state["eta"].copy()
            obj.noise = state["noise"].copy()
        return obj
