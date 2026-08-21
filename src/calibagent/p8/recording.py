"""Crash-consistent append-only P8 records and artifact export."""

import csv
import json
import os
import subprocess
import time
from pathlib import Path


def json_default(value):  # type: (Any) -> Any
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {value!r}")


class JsonlTrace:
    def __init__(self, path):  # type: (Path) -> None
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.stream = path.open("a", encoding="utf-8", buffering=1)

    def write(self, value):  # type: (Dict[str, Any]) -> None
        self.stream.write(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=json_default) + "\n"
        )
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self):  # type: () -> None
        self.stream.close()


class AppendCsv:
    def __init__(self, path, fields):  # type: (Path, Sequence[str]) -> None
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.fields = list(fields)

    def append(self, row):  # type: (Dict[str, Any]) -> None
        exists = self.path.is_file() and self.path.stat().st_size > 0
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.fields, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow({key: _cell(row.get(key, "")) for key in self.fields})
            stream.flush()
            os.fsync(stream.fileno())

    def rows(self):  # type: () -> List[Dict[str, str]]
        if not self.path.is_file():
            return []
        with self.path.open("r", encoding="utf-8", newline="") as stream:
            return [dict(row) for row in csv.DictReader(stream)]


def _cell(value):  # type: (Any) -> Any
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=json_default)
    return value


TRIAL_FIELDS = (
    "run_id",
    "planned_unit_id",
    "attempt_id",
    "block_id",
    "method_id",
    "map_id",
    "shift_id",
    "stage",
    "trial_index",
    "command_id",
    "planned_command",
    "sent_command",
    "measured_velocity",
    "covariance",
    "valid",
    "reason",
    "update_enabled",
    "update_applied",
    "posterior_before",
    "posterior_after",
    "posterior_path",
    "measure_start",
    "measure_end",
    "sample_count",
    "reference_max_age_ms",
    "scan_max_age_ms",
    "detector_statistic",
    "detector_alarm",
    "recovery_index",
    "validation_rmse",
    "bag_path",
    "status",
    "terminal_reason",
    "created_at",
)
EPISODE_FIELDS = (
    "run_id",
    "planned_unit_id",
    "attempt_id",
    "block_id",
    "method_id",
    "map_id",
    "route_order",
    "posterior_path",
    "start_pose_error_m",
    "start_yaw_error_deg",
    "start_reference_age_ms",
    "start_scan_age_ms",
    "start_stable_samples",
    "status",
    "terminal_reason",
    "success",
    "route_reached",
    "data_quality_valid",
    "data_quality_reason",
    "freshness_rule_version",
    "collision",
    "duration_s",
    "path_length_m",
    "final_goal_distance_m",
    "route_goal_count",
    "waypoints_reached",
    "trace_ticks",
    "planned_action_rate_hz",
    "reference_rate_hz",
    "scan_rate_hz",
    "max_scan_age_ms",
    "max_reference_age_ms",
    "max_sent_action_age_ms",
    "max_reference_source_age_ms",
    "max_reference_receive_gap_ms",
    "max_scan_receive_gap_ms",
    "max_planned_action_receive_gap_ms",
    "max_active_action_receive_gap_ms",
    "max_active_action_receive_age_ms",
    "bag_path",
    "created_at",
)
SEQUENCE_FIELDS = (
    "run_id",
    "planned_unit_id",
    "attempt_id",
    "block_id",
    "method_id",
    "shift_id",
    "status",
    "alarm",
    "detection_index",
    "posterior_path",
    "bag_path",
    "created_at",
)


class RunRecorder:
    def __init__(self, run_dir, run_id):  # type: (Path, str) -> None
        self.run_dir = run_dir
        self.run_id = run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for name in ("configs", "bags", "video", "posterior", "analysis"):
            (run_dir / name).mkdir(exist_ok=True)
        self.trials = AppendCsv(run_dir / "trials.csv", TRIAL_FIELDS)
        self.episodes = AppendCsv(run_dir / "navigation_episodes.csv", EPISODE_FIELDS)
        self.sequences = AppendCsv(run_dir / "shift_sequences.csv", SEQUENCE_FIELDS)
        self.trace = JsonlTrace(run_dir / "navigation_trace.jsonl")
        self.decisions = JsonlTrace(run_dir / "planner_decisions.jsonl")

    def completed(self, kind):  # type: (str) -> Set[str]
        table = (
            self.trials
            if kind == "trial"
            else self.episodes
            if kind == "episode"
            else self.sequences
        )
        terminal_statuses = {
            "trial": {"SUCCESS"},
            "episode": {"SUCCESS", "RESULT"},
            "sequence": {"SUCCESS"},
        }[kind]
        return {
            row["planned_unit_id"]
            for row in table.rows()
            if row.get("status") in terminal_statuses
        }

    def attempt_id(self, planned_unit_id, kind):  # type: (str, str) -> str
        table = (
            self.trials
            if kind == "trial"
            else self.episodes
            if kind == "episode"
            else self.sequences
        )
        count = sum(1 for row in table.rows() if row.get("planned_unit_id") == planned_unit_id)
        return f"{planned_unit_id}_attempt_{count + 1:02d}"

    def close(self):  # type: () -> None
        self.trace.close()
        self.decisions.close()


class BagSession:
    """One rosbag per method/sequence, not one bag per four-second trial."""

    def __init__(self, output, topics, enabled):  # type: (Path, Sequence[str], bool) -> None
        self.output = output
        self.topics = list(topics)
        self.enabled = bool(enabled)
        self.process = None  # type: Optional[subprocess.Popen]

    def __enter__(self):
        if self.enabled:
            if self.output.exists():
                raise FileExistsError("rosbag output already exists: {}".format(self.output))
            self.output.parent.mkdir(parents=True, exist_ok=True)
            command = ["ros2", "bag", "record", "-o", str(self.output), *self.topics]
            self.process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
            )
            time.sleep(1.0)
            return_code = self.process.poll()
            if return_code is not None:
                raise RuntimeError(
                    "ros2 bag record exited during startup with code {}: {}".format(
                        return_code, self.output
                    )
                )
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.process is not None:
            self.process.send_signal(2)
            try:
                self.process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5.0)

    @property
    def path(self):  # type: () -> str
        return str(self.output) if self.enabled else ""


def next_bag_path(directory, stem):  # type: (Path, str) -> Path
    """Return a new append-only rosbag part path, including after a resume."""
    index = 1
    while True:
        candidate = directory / ("{}_part_{:02d}".format(stem, index))
        if not candidate.exists():
            return candidate
        index += 1


def git_commit(root):  # type: (Path) -> str
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "UNKNOWN"


def write_manifest(path, payload):  # type: (Path, Dict[str, Any]) -> None
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(
            payload, stream, ensure_ascii=False, indent=2, sort_keys=True, default=json_default
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def export_jsonl(run_dir):  # type: (Path) -> Dict[str, str]
    outputs = {}  # type: Dict[str, str]
    for source_name, target_name in (
        ("navigation_trace.jsonl", "navigation_trace.csv"),
        ("planner_decisions.jsonl", "planner_decisions.csv"),
    ):
        source = run_dir / source_name
        if not source.is_file():
            continue
        rows = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not rows:
            continue
        fields = sorted({key for row in rows for key in row})
        target = run_dir / target_name
        with target.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _cell(row.get(key, "")) for key in fields})
        outputs[target_name] = str(target)
        try:
            import pandas as pd

            frame = pd.read_csv(target)
            parquet = target.with_suffix(".parquet")
            frame.to_parquet(parquet, index=False)
            outputs[parquet.name] = str(parquet)
        except (ImportError, ValueError, OSError):
            pass
    return outputs
