"""Paired-block P8 analysis with deterministic bootstrap intervals."""

import csv
import json
import math
from collections import defaultdict

import numpy as np


def _rows(path):  # type: (Path) -> List[Dict[str, str]]
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _float(value):  # type: (Any) -> float
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def bootstrap_ci(values, seed=88031, samples=10000):  # type: (Sequence[float], int, int) -> List[float]
    data = np.asarray([value for value in values if math.isfinite(value)], dtype=np.float64)
    if not len(data):
        return [float("nan"), float("nan")]
    rng = np.random.RandomState(seed)
    indices = rng.randint(0, len(data), size=(samples, len(data)))
    means = data[indices].mean(axis=1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def analyze_nav(run_dir):  # type: (Path) -> Dict[str, Any]
    episodes = _rows(run_dir / "navigation_episodes.csv")
    trials = _rows(run_dir / "trials.csv")
    block_metrics = []  # type: List[Dict[str, Any]]
    grouped = defaultdict(list)
    for row in episodes:
        grouped[(row["block_id"], row["method_id"], row["map_id"])].append(row)
    for (block, method, map_id), values in sorted(grouped.items()):
        row = values[-1]
        block_metrics.append(
            {
                "block_id": block,
                "method_id": method,
                "map_id": map_id,
                "success": int(str(row.get("success", "")).lower() in ("1", "true")),
                "collision": int(str(row.get("collision", "")).lower() in ("1", "true")),
                "completion_time_s": _float(row.get("duration_s")),
                "path_length_m": _float(row.get("path_length_m")),
            }
        )
    validation = defaultdict(list)
    for row in trials:
        if row.get("stage") == "validation" and row.get("valid", "").lower() in ("1", "true"):
            validation[(row["block_id"], row["method_id"])].append(
                _float(row.get("validation_rmse"))
            )
    for metric in block_metrics:
        values = validation[(metric["block_id"], metric["method_id"])]
        metric["velocity_rmse"] = float(np.nanmean(values)) if values else float("nan")
    comparisons = []  # type: List[Dict[str, Any]]
    for baseline in (
        "B0_raw",
        "B1_dense",
        "B2_lhs",
        "B3_sobol",
        "B4_d_opt",
        "B5_active_no_task",
        "B6_random",
    ):
        for map_id in sorted({row["map_id"] for row in block_metrics}):
            full = {
                row["block_id"]: row
                for row in block_metrics
                if row["method_id"] == "B8_full" and row["map_id"] == map_id
            }
            base = {
                row["block_id"]: row
                for row in block_metrics
                if row["method_id"] == baseline and row["map_id"] == map_id
            }
            common = sorted(set(full) & set(base))
            for metric_name in (
                "success",
                "collision",
                "completion_time_s",
                "path_length_m",
                "velocity_rmse",
            ):
                differences = [
                    float(full[key][metric_name]) - float(base[key][metric_name]) for key in common
                ]
                comparisons.append(
                    {
                        "comparison": f"B8_full-{baseline}",
                        "map_id": map_id,
                        "metric": metric_name,
                        "n_blocks": len(differences),
                        "mean_difference": float(np.mean(differences))
                        if differences
                        else float("nan"),
                        "ci95": bootstrap_ci(differences),
                    }
                )
    return {"protocol": "nav", "block_metrics": block_metrics, "paired_comparisons": comparisons}


def analyze_shift(run_dir):  # type: (Path) -> Dict[str, Any]
    trials = _rows(run_dir / "trials.csv")
    sequences = _rows(run_dir / "shift_sequences.csv")
    metrics = []  # type: List[Dict[str, Any]]
    for sequence in sequences:
        sequence_id = sequence["planned_unit_id"]
        rows = [
            row for row in trials if row.get("planned_unit_id", "").startswith(sequence_id + "_")
        ]
        pre = [row for row in rows if row.get("stage") == "pre_monitor"]
        validation = [row for row in rows if row.get("stage") == "recovery_validation"]
        by_index = {
            int(row["recovery_index"]): _float(row.get("validation_rmse"))
            for row in validation
            if row.get("recovery_index")
        }
        early = [by_index[index] for index in range(1, 5) if index in by_index]
        terminal = [by_index[index] for index in range(9, 13) if index in by_index]
        false_alarm = any(
            str(row.get("detector_alarm", "")).lower() in ("1", "true") for row in pre
        )
        metrics.append(
            {
                "shift_id": sequence["shift_id"],
                "block_id": sequence["block_id"],
                "method_id": sequence["method_id"],
                "false_alarm": int(false_alarm),
                "detected": int(str(sequence.get("alarm", "")).lower() in ("1", "true")),
                "detection_index": _float(sequence.get("detection_index")),
                "early_rmse": float(np.nanmean(early)) if early else float("nan"),
                "terminal_rmse": float(np.nanmean(terminal)) if terminal else float("nan"),
            }
        )
    comparisons = []  # type: List[Dict[str, Any]]
    for shift_id in sorted({row["shift_id"] for row in metrics}):
        full = {
            row["block_id"]: row
            for row in metrics
            if row["shift_id"] == shift_id and row["method_id"] == "full"
        }
        passive = {
            row["block_id"]: row
            for row in metrics
            if row["shift_id"] == shift_id and row["method_id"] == "passive"
        }
        common = sorted(set(full) & set(passive))
        for metric_name in ("early_rmse", "terminal_rmse"):
            differences = [
                float(full[key][metric_name]) - float(passive[key][metric_name]) for key in common
            ]
            comparisons.append(
                {
                    "comparison": "full-passive",
                    "shift_id": shift_id,
                    "metric": metric_name,
                    "n_blocks": len(differences),
                    "mean_difference": float(np.mean(differences)) if differences else float("nan"),
                    "ci95": bootstrap_ci(differences),
                }
            )
    return {"protocol": "shift", "sequence_metrics": metrics, "paired_comparisons": comparisons}


def analyze(run_dir):  # type: (Path) -> Dict[str, Any]
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    result = analyze_nav(run_dir) if manifest["protocol"] == "nav" else analyze_shift(run_dir)
    output = run_dir / "analysis" / "summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
