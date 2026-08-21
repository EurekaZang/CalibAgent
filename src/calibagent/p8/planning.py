"""P8 command tables, active selection, detector, and calibration transform."""

import numpy as np

from calibagent.p8.config import read_csv


class CommandTable:
    def __init__(self, path):  # type: (Path) -> None
        rows = read_csv(path)
        self.ids = [row["command_id"] for row in rows]
        self.commands = np.asarray(
            [[float(row["cmd_vx"]), float(row["cmd_vy"]), float(row["cmd_wz"])] for row in rows],
            dtype=np.float64,
        )
        self.weights = np.asarray(
            [float(row.get("weight", 1.0) or 1.0) for row in rows], dtype=np.float64
        )
        if len(self.weights):
            self.weights /= self.weights.sum()


class ActiveSelector:
    def __init__(self, pool, task):  # type: (CommandTable, CommandTable) -> None
        self.pool = pool
        self.task = task

    def select(self, model, history, kind):  # type: (VelocityModel, Sequence[np.ndarray], str) -> Tuple[int, List[Dict[str, object]]]
        commands = self.pool.commands
        features = model.basis.transform(commands)
        disallowed = np.zeros(len(commands), dtype=bool)
        if history:
            previous = np.vstack(history)
            distance = np.linalg.norm(commands[:, None, :] - previous[None, :, :], axis=2)
            disallowed = np.min(distance, axis=1) < 1e-6
        information = np.zeros(len(commands), dtype=np.float64)
        if kind == "d_opt":
            for axis in range(3):
                leverage = np.einsum("ni,ij,nj->n", features, model.covariances[axis], features)
                information += np.log1p(leverage / model.noise[axis])
        else:
            task_features = model.basis.transform(
                self.task.commands if kind == "task_ivr" else commands
            )
            weights = (
                self.task.weights
                if kind == "task_ivr"
                else np.full(len(commands), 1.0 / len(commands))
            )
            for axis in range(3):
                cov = model.covariances[axis]
                cross = task_features.dot(cov).dot(features.T)
                denominator = model.noise[axis] + np.einsum("ni,ij,nj->n", features, cov, features)
                information += np.sum(weights[:, None] * cross**2, axis=0) / np.maximum(
                    denominator, 1e-15
                )
        scores = information.copy()
        scores[disallowed] = -np.inf
        index = int(np.argmax(scores))
        if not np.isfinite(scores[index]):
            raise RuntimeError("no untried active command remains")
        order = np.argsort(-scores, kind="stable")[: min(16, len(scores))]
        diagnostics = [
            {
                "pool_index": int(item),
                "command_id": self.pool.ids[int(item)],
                "score": float(scores[item]),
                "information": float(information[item]),
                "selected": bool(item == index),
            }
            for item in order
            if np.isfinite(scores[item])
        ]
        return index, diagnostics


class CalibrationTransform:
    """Discrete inverse model; this is the sole post-planner command transform."""

    def __init__(self, pool, regularization=0.02, risk_weight=0.05):
        # type: (CommandTable, float, float) -> None
        self.pool = pool
        self.regularization = float(regularization)
        self.risk_weight = float(risk_weight)

    def apply(self, desired, model):  # type: (Sequence[float], VelocityModel) -> Tuple[np.ndarray, Dict[str, object]]
        target = np.asarray(desired, dtype=np.float64)
        if np.array_equal(target, np.zeros(3, dtype=np.float64)):
            return target.copy(), {
                "candidate_index": -1,
                "candidate_id": "policy_zero_passthrough",
                "inverse_objective": 0.0,
                "predicted_vx": 0.0,
                "predicted_vy": 0.0,
                "predicted_wz": 0.0,
                "prediction_variance": [0.0, 0.0, 0.0],
            }
        means, variances = model.predict_batch(self.pool.commands)
        objective = np.sum((means - target[None, :]) ** 2, axis=1)
        objective += self.regularization * np.sum(
            (self.pool.commands - target[None, :]) ** 2, axis=1
        )
        objective += self.risk_weight * np.sum(variances, axis=1)
        index = int(np.argmin(objective))
        return self.pool.commands[index].copy(), {
            "candidate_index": index,
            "candidate_id": self.pool.ids[index],
            "inverse_objective": float(objective[index]),
            "predicted_vx": float(means[index, 0]),
            "predicted_vy": float(means[index, 1]),
            "predicted_wz": float(means[index, 2]),
            "prediction_variance": [float(value) for value in variances[index]],
        }


class ResidualDetector:
    def __init__(self, threshold, consecutive):  # type: (float, int) -> None
        self.threshold = float(threshold)
        self.consecutive = int(consecutive)
        self.run = 0
        self.alarm = False
        self.first_alarm_index = None  # type: Optional[int]

    def observe(self, command, measured, covariance, model, index):
        # type: (Sequence[float], Sequence[float], np.ndarray, VelocityModel, int) -> Tuple[float, bool]
        mean, variance = model.predict(command)
        residual = np.asarray(measured, dtype=np.float64) - mean
        total = np.maximum(variance + np.maximum(np.diag(covariance), 0.0), 1e-9)
        statistic = float(np.sqrt(np.sum(residual**2 / total)))
        self.run = self.run + 1 if statistic >= self.threshold else 0
        if not self.alarm and self.run >= self.consecutive:
            self.alarm = True
            self.first_alarm_index = int(index)
        return statistic, self.alarm


def apply_shift_matrix(command, matrix):  # type: (Sequence[float], Sequence[Sequence[float]]) -> np.ndarray
    """Apply the declared R1 experimental context change without clipping."""
    return np.asarray(matrix, dtype=np.float64).dot(np.asarray(command, dtype=np.float64))
