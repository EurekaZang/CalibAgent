#!/usr/bin/env python3
"""Run the frozen Go2 P1 velocity plan and export measure-window poses.

This runner follows p1_go2_real_data_collection_handoff_zh.md:
- reads the frozen plan.csv without changing session/trial IDs or commands;
- publishes smooth ramp/settle/measure/ramp-out cmd_vel commands;
- records only independent /Odometry samples from the measure window to
  exported/go2_raw_trials.csv;
- computes measured body-frame velocity from the pose samples in a separate
  metadata/trial_velocity_summary.csv;
- returns the robot to the start pose after each trial by default so a small
  field is not exhausted.

Start the localization stack and the Go2 cmd_vel bridge before running this.
Use --arm only when the robot is in a clear, supervised, emergency-stop-ready
field.

This is a tracked P1 reference implementation, not a completed P8 backend.
P8 developers should reuse its trial, topic-health, ledger, and fail-closed
patterns while following docs/p8_go2_implementation_guide_zh.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String

PLAN_SHA256 = "7393222a654e488132be235cffef81d13776d5b6f93f2bb844fa7dc5401f821c"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLAN = REPOSITORY_ROOT / "evidence" / "p1_capture" / "plan.csv"
DEFAULT_MANIFEST = REPOSITORY_ROOT / "evidence" / "p1_capture" / "plan.manifest.json"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "outputs" / "p1_go2_real_delivery"

REQUIRED_PLAN_COLUMNS = {
    "session_id",
    "trial_id",
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "design_source",
    "ramp_in_s",
    "settle_s",
    "measure_s",
    "ramp_out_s",
    "sample_rate_hz",
}
RAW_FIELDS = [
    "trial_id",
    "session_id",
    "timestamp",
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "pose_x",
    "pose_y",
    "pose_yaw",
    "terrain_id",
    "payload_kg",
    "battery_ratio",
    "gait_id",
]
ATTEMPT_FIELDS = [
    "timestamp",
    "phase",
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "pose_x",
    "pose_y",
    "pose_yaw",
    "loc_ready",
    "frame_id",
    "child_frame_id",
]
LEDGER_FIELDS = [
    "session_id",
    "trial_id",
    "attempt_id",
    "execution_order",
    "bag_path",
    "measure_start_timestamp",
    "measure_end_timestamp",
    "status",
    "exclusion_reason",
    "selected_for_csv",
    "safety_event",
    "reference_valid",
    "operator_notes",
]
VELOCITY_FIELDS = [
    "session_id",
    "trial_id",
    "attempt_id",
    "samples",
    "duration_s",
    "median_hz",
    "max_gap_s",
    "cmd_vx",
    "cmd_vy",
    "cmd_wz",
    "est_vx_body",
    "est_vy_body",
    "est_wz",
    "start_x",
    "start_y",
    "start_yaw",
    "end_x",
    "end_y",
    "end_yaw",
]


@dataclass(frozen=True)
class PlanRow:
    session_id: str
    trial_id: str
    cmd_vx: float
    cmd_vy: float
    cmd_wz: float
    design_source: str
    ramp_in_s: float
    settle_s: float
    measure_s: float
    ramp_out_s: float
    sample_rate_hz: float


@dataclass(frozen=True)
class PoseSample:
    timestamp: float
    x: float
    y: float
    yaw: float
    frame_id: str
    child_frame_id: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def wrap_to_pi(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def yaw_from_quat(q) -> float:
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


def stamp_to_sec(stamp) -> float:
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def clamp(v: float, limit: float) -> float:
    return max(-limit, min(limit, v))


def finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def parse_trial_filter(text: Optional[str]) -> Optional[set]:
    if not text:
        return None
    selected = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a)
            end = int(b)
            if end < start:
                raise ValueError(f"bad trial range: {part}")
            selected.update(str(i) for i in range(start, end + 1))
        else:
            selected.add(str(int(part)))
    return selected


def load_plan(path: Path) -> List[PlanRow]:
    actual_sha = sha256_file(path)
    if actual_sha != PLAN_SHA256:
        raise RuntimeError(
            f"plan.csv SHA-256 mismatch: got {actual_sha}, expected {PLAN_SHA256}. "
            "Do not run a modified capture plan."
        )

    rows: List[PlanRow] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = sorted(REQUIRED_PLAN_COLUMNS - set(reader.fieldnames or []))
        if missing:
            raise RuntimeError(f"plan.csv missing columns: {missing}")
        for raw in reader:
            row = PlanRow(
                session_id=str(raw["session_id"]),
                trial_id=str(int(raw["trial_id"])),
                cmd_vx=float(raw["cmd_vx"]),
                cmd_vy=float(raw["cmd_vy"]),
                cmd_wz=float(raw["cmd_wz"]),
                design_source=str(raw["design_source"]),
                ramp_in_s=float(raw["ramp_in_s"]),
                settle_s=float(raw["settle_s"]),
                measure_s=float(raw["measure_s"]),
                ramp_out_s=float(raw["ramp_out_s"]),
                sample_rate_hz=float(raw["sample_rate_hz"]),
            )
            validate_plan_row(row)
            rows.append(row)
    if len(rows) != 183:
        raise RuntimeError(f"plan.csv contains {len(rows)} rows, expected 183")
    return rows


def validate_plan_row(row: PlanRow) -> None:
    if not (-0.60 <= row.cmd_vx <= 0.60):
        raise RuntimeError(f"{row.session_id}/{row.trial_id}: cmd_vx out of frozen bounds")
    if not (-0.30 <= row.cmd_vy <= 0.30):
        raise RuntimeError(f"{row.session_id}/{row.trial_id}: cmd_vy out of frozen bounds")
    if not (-0.80 <= row.cmd_wz <= 0.80):
        raise RuntimeError(f"{row.session_id}/{row.trial_id}: cmd_wz out of frozen bounds")
    if math.hypot(row.cmd_vx, row.cmd_vy) > 0.65 + 1e-12:
        raise RuntimeError(f"{row.session_id}/{row.trial_id}: translational norm out of frozen bounds")
    for name in ("ramp_in_s", "settle_s", "measure_s", "ramp_out_s", "sample_rate_hz"):
        value = getattr(row, name)
        if not finite(value) or value <= 0.0:
            raise RuntimeError(f"{row.session_id}/{row.trial_id}: invalid {name}={value}")


def filter_plan(rows: Sequence[PlanRow], sessions: Optional[Sequence[str]], trial_filter: Optional[set]) -> List[PlanRow]:
    session_set = set(sessions or [])
    selected = []
    for row in rows:
        if session_set and row.session_id not in session_set:
            continue
        if trial_filter is not None and row.trial_id not in trial_filter:
            continue
        selected.append(row)
    return selected


def append_csv(path: Path, fields: Sequence[str], rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_csv(path: Path, fields: Sequence[str], rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def unwrap_yaws(yaws: Sequence[float]) -> List[float]:
    if not yaws:
        return []
    unwrapped = [yaws[0]]
    for yaw in yaws[1:]:
        unwrapped.append(unwrapped[-1] + wrap_to_pi(yaw - unwrapped[-1]))
    return unwrapped


def linear_slope(t: Sequence[float], y: Sequence[float]) -> float:
    n = len(t)
    if n < 2:
        return float("nan")
    mt = sum(t) / n
    my = sum(y) / n
    denom = sum((ti - mt) ** 2 for ti in t)
    if denom <= 0.0:
        return float("nan")
    return sum((ti - mt) * (yi - my) for ti, yi in zip(t, y)) / denom


def median(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def summarize_velocity(row: PlanRow, attempt_id: int, measure_rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    t = [float(r["timestamp"]) for r in measure_rows]
    x = [float(r["pose_x"]) for r in measure_rows]
    y = [float(r["pose_y"]) for r in measure_rows]
    yaw = [float(r["pose_yaw"]) for r in measure_rows]
    cmd_vx = [float(r["cmd_vx"]) for r in measure_rows]
    cmd_vy = [float(r["cmd_vy"]) for r in measure_rows]
    cmd_wz = [float(r["cmd_wz"]) for r in measure_rows]
    yaw_u = unwrap_yaws(yaw)
    dt = [b - a for a, b in zip(t[:-1], t[1:])]
    sx = linear_slope(t, x)
    sy = linear_slope(t, y)
    sw = linear_slope(t, yaw_u)
    mean_yaw = sum(yaw_u) / len(yaw_u) if yaw_u else float("nan")
    vx_body = math.cos(mean_yaw) * sx + math.sin(mean_yaw) * sy if finite(mean_yaw, sx, sy) else float("nan")
    vy_body = -math.sin(mean_yaw) * sx + math.cos(mean_yaw) * sy if finite(mean_yaw, sx, sy) else float("nan")
    mean_cmd_vx = sum(cmd_vx) / len(cmd_vx) if cmd_vx else row.cmd_vx
    mean_cmd_vy = sum(cmd_vy) / len(cmd_vy) if cmd_vy else row.cmd_vy
    mean_cmd_wz = sum(cmd_wz) / len(cmd_wz) if cmd_wz else row.cmd_wz
    return {
        "session_id": row.session_id,
        "trial_id": row.trial_id,
        "attempt_id": attempt_id,
        "samples": len(measure_rows),
        "duration_s": f"{(t[-1] - t[0]) if len(t) >= 2 else 0.0:.6f}",
        "median_hz": f"{(1.0 / median(dt)) if dt and median(dt) > 0 else 0.0:.6f}",
        "max_gap_s": f"{max(dt) if dt else float('inf'):.6f}",
        "cmd_vx": f"{mean_cmd_vx:.6f}",
        "cmd_vy": f"{mean_cmd_vy:.6f}",
        "cmd_wz": f"{mean_cmd_wz:.6f}",
        "est_vx_body": f"{vx_body:.6f}",
        "est_vy_body": f"{vy_body:.6f}",
        "est_wz": f"{sw:.6f}",
        "start_x": f"{x[0]:.6f}" if x else "",
        "start_y": f"{y[0]:.6f}" if y else "",
        "start_yaw": f"{yaw[0]:.6f}" if yaw else "",
        "end_x": f"{x[-1]:.6f}" if x else "",
        "end_y": f"{y[-1]:.6f}" if y else "",
        "end_yaw": f"{yaw[-1]:.6f}" if yaw else "",
    }


def quality_error(measure_rows: Sequence[Dict[str, object]], min_samples: int, row: PlanRow) -> Optional[str]:
    if len(measure_rows) < min_samples:
        return f"samples {len(measure_rows)} < {min_samples}"
    t = [float(r["timestamp"]) for r in measure_rows]
    if any(b <= a for a, b in zip(t[:-1], t[1:])):
        return "timestamp not strictly increasing"
    gaps = [b - a for a, b in zip(t[:-1], t[1:])]
    if gaps and max(gaps) > 0.10:
        return f"max timestamp gap {max(gaps):.3f}s > 0.10s"
    numeric_fields = ["timestamp", "cmd_vx", "cmd_vy", "cmd_wz", "pose_x", "pose_y", "pose_yaw"]
    for r in measure_rows:
        for key in numeric_fields:
            if not finite(float(r[key])):
                return f"non-finite {key}"

    cmd = [[float(r["cmd_vx"]), float(r["cmd_vy"]), float(r["cmd_wz"])] for r in measure_rows]
    means = [sum(c[i] for c in cmd) / len(cmd) for i in range(3)]
    max_dev = max(math.sqrt(sum((c[i] - means[i]) ** 2 for i in range(3))) for c in cmd)
    if max_dev >= 1e-3:
        return f"actual command not constant: max deviation {max_dev:.6g} >= 1e-3"
    plan = [row.cmd_vx, row.cmd_vy, row.cmd_wz]
    for name, actual, expected in zip(("cmd_vx", "cmd_vy", "cmd_wz"), means, plan):
        if abs(actual - expected) > 1e-3:
            return f"{name} actual {actual:.6f} does not match plan {expected:.6f} within 1e-3"
    return None


class CaptureNode(Node):
    def __init__(self, args: argparse.Namespace):
        super().__init__("go2_plan_capture_runner")
        self.args = args
        self._lock = threading.Lock()
        self.last_pose: Optional[PoseSample] = None
        self.pose_recent_stamps: List[float] = []
        self.loc_seen = False
        self.loc_ready = False
        self.loc_text = ""
        self.actual_cmd_seen = False
        self.last_actual_cmd_stamp = 0.0
        self.last_actual_cmd_recv_time = 0.0
        self.last_actual_cmd = (0.0, 0.0, 0.0)
        self.current_phase = "idle"
        self.current_cmd = (0.0, 0.0, 0.0)
        self.current_row: Optional[PlanRow] = None
        self.measure_rows: List[Dict[str, object]] = []
        self.attempt_rows: List[Dict[str, object]] = []
        self.measure_started_at: Optional[float] = None
        self.measure_ended_at: Optional[float] = None

        qos_sensor = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=100,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.cmd_pub = self.create_publisher(Twist, args.cmd_topic, 10)
        self.marker_pub = self.create_publisher(String, args.marker_topic, 10)
        self.create_subscription(Odometry, args.odom_topic, self._odom_cb, qos_sensor)
        self.create_subscription(String, args.loc_health_topic, self._health_cb, 10)
        self.create_subscription(TwistStamped, args.actual_cmd_topic, self._actual_cmd_cb, 10)

    def _odom_cb(self, msg: Odometry) -> None:
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        timestamp = stamp_to_sec(msg.header.stamp)
        if timestamp <= 0.0:
            timestamp = self.get_clock().now().nanoseconds * 1e-9
        yaw = yaw_from_quat(q)
        if not finite(timestamp, p.x, p.y, yaw):
            return
        pose = PoseSample(timestamp, float(p.x), float(p.y), float(yaw), msg.header.frame_id, msg.child_frame_id)

        with self._lock:
            self.last_pose = pose
            self.pose_recent_stamps.append(timestamp)
            if len(self.pose_recent_stamps) > 1000:
                self.pose_recent_stamps = self.pose_recent_stamps[-1000:]

            if self.current_row is None or self.current_phase == "idle":
                return

            vx, vy, wz = self.current_cmd
            now_s = self.get_clock().now().nanoseconds * 1e-9
            actual_age = (now_s - self.last_actual_cmd_recv_time) if self.actual_cmd_seen else float("inf")
            if self.args.use_actual_cmd and self.actual_cmd_seen and actual_age <= self.args.actual_cmd_timeout_s:
                vx, vy, wz = self.last_actual_cmd
            loc_ready = self._loc_ready_locked()
            attempt_row = {
                "timestamp": f"{timestamp:.9f}",
                "phase": self.current_phase,
                "cmd_vx": f"{vx:.6f}",
                "cmd_vy": f"{vy:.6f}",
                "cmd_wz": f"{wz:.6f}",
                "pose_x": f"{pose.x:.9f}",
                "pose_y": f"{pose.y:.9f}",
                "pose_yaw": f"{pose.yaw:.9f}",
                "loc_ready": str(loc_ready).lower(),
                "frame_id": pose.frame_id,
                "child_frame_id": pose.child_frame_id,
            }
            self.attempt_rows.append(attempt_row)
            if self.current_phase == "measure":
                row = {
                    "trial_id": self.current_row.trial_id,
                    "session_id": self.current_row.session_id,
                    "timestamp": f"{timestamp:.9f}",
                    "cmd_vx": f"{vx:.6f}",
                    "cmd_vy": f"{vy:.6f}",
                    "cmd_wz": f"{wz:.6f}",
                    "pose_x": f"{pose.x:.9f}",
                    "pose_y": f"{pose.y:.9f}",
                    "pose_yaw": f"{pose.yaw:.9f}",
                    "terrain_id": self.args.terrain_id,
                    "payload_kg": f"{self.args.payload_kg:.3f}",
                    "battery_ratio": f"{self.args.battery_ratio:.3f}",
                    "gait_id": self.args.gait_id,
                }
                self.measure_rows.append(row)

    def _health_cb(self, msg: String) -> None:
        with self._lock:
            self.loc_seen = True
            self.loc_text = msg.data
            self.loc_ready = msg.data.startswith("READY|") or msg.data == "READY"

    def _actual_cmd_cb(self, msg: TwistStamped) -> None:
        stamp = stamp_to_sec(msg.header.stamp)
        if stamp <= 0.0:
            stamp = self.get_clock().now().nanoseconds * 1e-9
        cmd = (float(msg.twist.linear.x), float(msg.twist.linear.y), float(msg.twist.angular.z))
        with self._lock:
            self.actual_cmd_seen = True
            self.last_actual_cmd_stamp = stamp
            self.last_actual_cmd_recv_time = self.get_clock().now().nanoseconds * 1e-9
            self.last_actual_cmd = cmd

    def _loc_ready_locked(self) -> bool:
        if not self.args.require_ready:
            return True
        return self.loc_seen and self.loc_ready

    def is_ready(self) -> bool:
        with self._lock:
            return self._loc_ready_locked()

    def loc_status(self) -> str:
        with self._lock:
            if not self.loc_seen:
                return "not_seen"
            return self.loc_text

    def get_pose(self) -> Optional[PoseSample]:
        with self._lock:
            return self.last_pose

    def clear_recent_pose_stamps(self) -> None:
        with self._lock:
            self.pose_recent_stamps = []

    def recent_pose_stamps(self) -> List[float]:
        with self._lock:
            return list(self.pose_recent_stamps)

    def actual_cmd_ready(self) -> bool:
        if not self.args.use_actual_cmd:
            return True
        with self._lock:
            if not self.actual_cmd_seen:
                return False
            now_s = self.get_clock().now().nanoseconds * 1e-9
            return (now_s - self.last_actual_cmd_recv_time) <= self.args.actual_cmd_timeout_s

    def begin_attempt(self, row: PlanRow) -> None:
        with self._lock:
            self.current_row = row
            self.current_phase = "precheck"
            self.current_cmd = (0.0, 0.0, 0.0)
            self.measure_rows = []
            self.attempt_rows = []
            self.measure_started_at = None
            self.measure_ended_at = None
        self.publish_marker(row, "attempt_start")

    def set_phase(self, row: PlanRow, phase: str, cmd: Tuple[float, float, float]) -> None:
        with self._lock:
            prev = self.current_phase
            self.current_row = row
            self.current_phase = phase
            self.current_cmd = cmd
            if phase == "measure" and prev != "measure":
                pose = self.last_pose
                self.measure_started_at = pose.timestamp if pose else None
            if prev == "measure" and phase != "measure":
                pose = self.last_pose
                self.measure_ended_at = pose.timestamp if pose else None
        if prev != phase:
            self.publish_marker(row, phase)

    def end_attempt(self, row: PlanRow, status: str) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Optional[float], Optional[float]]:
        self.publish_marker(row, f"attempt_end:{status}")
        with self._lock:
            measure = list(self.measure_rows)
            attempt = list(self.attempt_rows)
            start = self.measure_started_at
            end = self.measure_ended_at
            self.current_row = None
            self.current_phase = "idle"
            self.current_cmd = (0.0, 0.0, 0.0)
            self.measure_rows = []
            self.attempt_rows = []
            self.measure_started_at = None
            self.measure_ended_at = None
        return measure, attempt, start, end

    def publish_marker(self, row: PlanRow, phase: str) -> None:
        msg = String()
        msg.data = (
            f"session={row.session_id},trial={row.trial_id},phase={phase},"
            f"t={self.get_clock().now().nanoseconds * 1e-9:.9f}"
        )
        self.marker_pub.publish(msg)

    def publish_cmd(self, vx: float, vy: float, wz: float) -> None:
        msg = Twist()
        msg.linear.x = float(vx)
        msg.linear.y = float(vy)
        msg.angular.z = float(wz)
        if self.args.arm or (abs(vx) < 1e-12 and abs(vy) < 1e-12 and abs(wz) < 1e-12):
            self.cmd_pub.publish(msg)

    def stop(self, repeats: int = 5) -> None:
        for _ in range(repeats):
            self.publish_cmd(0.0, 0.0, 0.0)
            time.sleep(0.02)


def wait_for_pose(node: CaptureNode, timeout_s: float) -> PoseSample:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pose = node.get_pose()
        if pose is not None:
            return pose
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {node.args.odom_topic}")


def wait_for_ready(node: CaptureNode, timeout_s: float) -> None:
    if not node.args.require_ready:
        return
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if node.is_ready():
            return
        time.sleep(0.05)
    raise RuntimeError(f"localization not READY on {node.args.loc_health_topic}: {node.loc_status()}")


def wait_for_actual_cmd(node: CaptureNode, timeout_s: float) -> None:
    if not node.args.use_actual_cmd:
        return
    deadline = time.monotonic() + timeout_s
    node.stop()
    while time.monotonic() < deadline:
        node.stop(repeats=1)
        if node.actual_cmd_ready():
            return
        time.sleep(0.05)
    raise RuntimeError(
        f"actual command topic {node.args.actual_cmd_topic} not received; "
        "rebuild/restart ws_fastlio cmd_vel_bridge or run with --no-use-actual-cmd"
    )


def measure_odom_hz(node: CaptureNode, duration_s: float) -> Tuple[int, float, float]:
    node.clear_recent_pose_stamps()
    time.sleep(duration_s)
    stamps = node.recent_pose_stamps()
    stamps = sorted(set(stamps))
    gaps = [b - a for a, b in zip(stamps[:-1], stamps[1:]) if b > a]
    med_gap = median(gaps)
    hz = 1.0 / med_gap if gaps and med_gap > 0.0 else 0.0
    max_gap = max(gaps) if gaps else float("inf")
    return len(stamps), hz, max_gap


def distance_from_home(home: PoseSample, pose: PoseSample) -> float:
    return math.hypot(pose.x - home.x, pose.y - home.y)


def check_boundary(node: CaptureNode, home: PoseSample, hard: bool = False) -> Optional[str]:
    pose = node.get_pose()
    if pose is None:
        return None
    if hard and node.args.hard_radius_m > 0.0:
        limit = node.args.hard_radius_m
    elif node.args.max_radius_m > 0.0:
        limit = node.args.max_radius_m
    else:
        return None
    dist = distance_from_home(home, pose)
    if dist > limit:
        return f"distance from home {dist:.3f}m > radius {limit:.3f}m"
    return None


def run_command_phase(
    node: CaptureNode,
    row: PlanRow,
    home: PoseSample,
    phase: str,
    duration_s: float,
    start_cmd: Tuple[float, float, float],
    end_cmd: Tuple[float, float, float],
) -> Optional[str]:
    rate = max(1.0, float(node.args.command_rate_hz))
    period = 1.0 / rate
    t0 = time.monotonic()
    while True:
        elapsed = time.monotonic() - t0
        if elapsed >= duration_s:
            break
        if node.args.require_ready and not node.is_ready():
            node.stop()
            return f"localization not READY during {phase}: {node.loc_status()}"
        if node.args.use_actual_cmd and not node.actual_cmd_ready():
            node.stop()
            return f"actual command topic stale during {phase}: {node.args.actual_cmd_topic}"
        boundary = check_boundary(node, home)
        if boundary:
            node.stop()
            return f"safety boundary during {phase}: {boundary}"
        alpha = 1.0 if duration_s <= 0.0 else max(0.0, min(1.0, elapsed / duration_s))
        vx = start_cmd[0] + (end_cmd[0] - start_cmd[0]) * alpha
        vy = start_cmd[1] + (end_cmd[1] - start_cmd[1]) * alpha
        wz = start_cmd[2] + (end_cmd[2] - start_cmd[2]) * alpha
        cmd = (vx, vy, wz)
        node.set_phase(row, phase, cmd)
        node.publish_cmd(*cmd)
        time.sleep(period)
    node.set_phase(row, phase, end_cmd)
    node.publish_cmd(*end_cmd)
    return None


def return_home(node: CaptureNode, home: PoseSample, reason: str) -> bool:
    if node.args.return_home == "never" or not node.args.arm:
        node.stop()
        return True
    print(f"[home] {reason}: returning to x={home.x:.3f}, y={home.y:.3f}, yaw={home.yaw:.3f}")
    dummy = PlanRow("home", reason, 0.0, 0.0, 0.0, "home", 0.0, 0.0, 0.0, 0.0, node.args.command_rate_hz)
    deadline = time.monotonic() + node.args.return_timeout_s
    rate = max(1.0, float(node.args.command_rate_hz))
    period = 1.0 / rate
    while time.monotonic() < deadline:
        if node.args.require_ready and not node.is_ready():
            print(f"[home] localization not READY while returning: {node.loc_status()}")
            node.stop()
            return False
        if node.args.use_actual_cmd and not node.actual_cmd_ready():
            print(f"[home] actual command topic stale while returning: {node.args.actual_cmd_topic}")
            node.stop()
            return False
        pose = node.get_pose()
        if pose is None:
            time.sleep(period)
            continue
        dx = home.x - pose.x
        dy = home.y - pose.y
        dist = math.hypot(dx, dy)
        yaw_err = wrap_to_pi(home.yaw - pose.yaw)
        if dist <= node.args.home_xy_tolerance_m and abs(yaw_err) <= node.args.home_yaw_tolerance_rad:
            node.set_phase(dummy, "return_home_done", (0.0, 0.0, 0.0))
            node.stop()
            time.sleep(node.args.home_settle_s)
            return True
        if node.args.hard_radius_m > 0.0:
            hard = check_boundary(node, home, hard=True)
            if hard:
                print(f"[home] hard boundary exceeded, stopping: {hard}")
                node.stop()
                return False

        # Map-frame error transformed to robot body frame.
        ex_body = math.cos(pose.yaw) * dx + math.sin(pose.yaw) * dy
        ey_body = -math.sin(pose.yaw) * dx + math.cos(pose.yaw) * dy
        vx = clamp(node.args.home_kp_xy * ex_body, node.args.home_max_vx)
        vy = clamp(node.args.home_kp_xy * ey_body, node.args.home_max_vy)
        wz = clamp(node.args.home_kp_yaw * yaw_err, node.args.home_max_wz)
        if dist <= node.args.home_xy_tolerance_m:
            vx = 0.0
            vy = 0.0
        node.set_phase(dummy, "return_home", (vx, vy, wz))
        node.publish_cmd(vx, vy, wz)
        time.sleep(period)
    node.stop()
    print(f"[home] timeout after {node.args.return_timeout_s:.1f}s")
    return False


def prepare_output(args: argparse.Namespace, selected_rows: Sequence[PlanRow]) -> None:
    out = args.output_dir
    raw_csv = out / "exported" / "go2_raw_trials.csv"
    ledger = out / "metadata" / "trial_ledger.csv"
    velocity = out / "metadata" / "trial_velocity_summary.csv"
    if not args.arm:
        return
    if args.overwrite:
        for path in (raw_csv, ledger, velocity):
            if path.exists():
                path.unlink()
    elif not args.append:
        existing = [str(p) for p in (raw_csv, ledger, velocity) if p.exists()]
        if existing:
            raise RuntimeError(
                "output files already exist; use --append to continue or --overwrite to start over: "
                + ", ".join(existing)
            )

    (out / "capture_plan").mkdir(parents=True, exist_ok=True)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "exported").mkdir(parents=True, exist_ok=True)
    (out / "metadata").mkdir(parents=True, exist_ok=True)
    (out / "calibration").mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.plan, out / "capture_plan" / "plan.csv")
    if args.manifest.exists():
        shutil.copy2(args.manifest, out / "capture_plan" / "plan.manifest.json")
    print(f"[output] delivery dir: {out}")
    print(f"[output] selected trials this run: {len(selected_rows)}")


def predicted_translation(row: PlanRow) -> float:
    moving_s = 0.5 * row.ramp_in_s + row.settle_s + row.measure_s + 0.5 * row.ramp_out_s
    return math.hypot(row.cmd_vx, row.cmd_vy) * moving_s


def run_trial(
    node: CaptureNode,
    row: PlanRow,
    attempt_id: int,
    execution_order: int,
    home: PoseSample,
    args: argparse.Namespace,
) -> Tuple[str, bool]:
    node.begin_attempt(row)
    target = (row.cmd_vx, row.cmd_vy, row.cmd_wz)
    status = "complete"
    exclusion = ""
    safety_event = ""
    reference_valid = True
    selected_for_csv = False
    measure_rows: List[Dict[str, object]] = []
    attempt_rows: List[Dict[str, object]] = []
    measure_start: Optional[float] = None
    measure_end: Optional[float] = None

    try:
        print(
            f"[trial] {execution_order}: {row.session_id}/{row.trial_id} "
            f"cmd=({row.cmd_vx:.6f},{row.cmd_vy:.6f},{row.cmd_wz:.6f})"
        )
        node.stop()
        if args.require_ready and not node.is_ready():
            status = "pre_measure_abort"
            exclusion = f"localization not READY before trial: {node.loc_status()}"
            reference_valid = False
            return status, False
        boundary = check_boundary(node, home)
        if boundary:
            status = "pre_measure_abort"
            exclusion = f"not at safe start: {boundary}"
            safety_event = exclusion
            return status, False

        err = run_command_phase(node, row, home, "ramp_in", row.ramp_in_s, (0.0, 0.0, 0.0), target)
        if err:
            status = "pre_measure_abort"
            exclusion = err
            reference_valid = False
            safety_event = err if "safety" in err else ""
            return status, False

        err = run_command_phase(node, row, home, "settle", row.settle_s, target, target)
        if err:
            status = "pre_measure_abort"
            exclusion = err
            reference_valid = False
            safety_event = err if "safety" in err else ""
            return status, False

        err = run_command_phase(node, row, home, "measure", row.measure_s, target, target)
        if err:
            status = "technical_abort" if "localization" in err else "safety_abort"
            exclusion = err
            reference_valid = "localization" not in err
            safety_event = err if "safety" in err else ""
            return status, False

        err = run_command_phase(node, row, home, "ramp_out", row.ramp_out_s, target, (0.0, 0.0, 0.0))
        if err:
            status = "technical_abort" if "localization" in err else "safety_abort"
            exclusion = err
            reference_valid = "localization" not in err
            safety_event = err if "safety" in err else ""
            return status, False

        node.stop()
        measure_rows, attempt_rows, measure_start, measure_end = node.end_attempt(row, status)
        qerr = quality_error(measure_rows, args.min_samples, row)
        if qerr:
            status = "technical_abort"
            exclusion = qerr
            reference_valid = False
            selected_for_csv = False
        else:
            selected_for_csv = True
        return status, selected_for_csv
    finally:
        node.stop()
        if not attempt_rows:
            measure_rows, attempt_rows, measure_start, measure_end = node.end_attempt(row, status)
        if args.arm:
            attempt_path = (
                args.output_dir
                / "raw"
                / row.session_id
                / "reference_native"
                / f"trial_{int(row.trial_id):02d}_attempt_{attempt_id:02d}.csv"
            )
            write_csv(attempt_path, ATTEMPT_FIELDS, attempt_rows)
            ledger_row = {
                "session_id": row.session_id,
                "trial_id": row.trial_id,
                "attempt_id": attempt_id,
                "execution_order": execution_order,
                "bag_path": str(attempt_path),
                "measure_start_timestamp": f"{measure_start:.9f}" if measure_start is not None else "",
                "measure_end_timestamp": f"{measure_end:.9f}" if measure_end is not None else "",
                "status": status,
                "exclusion_reason": exclusion,
                "selected_for_csv": str(selected_for_csv).lower(),
                "safety_event": safety_event,
                "reference_valid": str(reference_valid).lower(),
                "operator_notes": args.operator_notes,
            }
            append_csv(args.output_dir / "metadata" / "trial_ledger.csv", LEDGER_FIELDS, [ledger_row])
            if selected_for_csv:
                append_csv(args.output_dir / "exported" / "go2_raw_trials.csv", RAW_FIELDS, measure_rows)
                append_csv(
                    args.output_dir / "metadata" / "trial_velocity_summary.csv",
                    VELOCITY_FIELDS,
                    [summarize_velocity(row, attempt_id, measure_rows)],
                )


def run_capture(args: argparse.Namespace) -> int:
    all_rows = load_plan(args.plan)
    selected_rows = filter_plan(all_rows, args.session_id, parse_trial_filter(args.trials))
    if not selected_rows:
        raise RuntimeError("no plan rows selected")

    risky = [r for r in selected_rows if args.max_radius_m > 0 and predicted_translation(r) > args.max_radius_m]
    if risky:
        print(
            f"[warn] {len(risky)} selected trials have straight-line predicted translation larger than "
            f"--max-radius-m={args.max_radius_m:.2f}. The online boundary check will abort and home if needed."
        )

    prepare_output(args, selected_rows)
    if not args.arm:
        print("[dry-run] --arm not set: non-zero /cmd_vel commands will NOT be published and final CSV will NOT be written.")

    rclpy.init(args=None)
    node = CaptureNode(args)
    executor = rclpy.executors.MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        wait_for_ready(node, args.ready_timeout_s)
        wait_for_actual_cmd(node, args.actual_cmd_timeout_s)
        first_pose = wait_for_pose(node, args.pose_timeout_s)
        home = PoseSample(
            timestamp=first_pose.timestamp,
            x=args.home_x if args.home_x is not None else first_pose.x,
            y=args.home_y if args.home_y is not None else first_pose.y,
            yaw=args.home_yaw if args.home_yaw is not None else first_pose.yaw,
            frame_id=first_pose.frame_id,
            child_frame_id=first_pose.child_frame_id,
        )
        print(f"[home] origin x={home.x:.3f}, y={home.y:.3f}, yaw={home.yaw:.3f}")

        if not args.skip_hz_check:
            n, hz, max_gap = measure_odom_hz(node, args.hz_check_duration_s)
            print(f"[preflight] {args.odom_topic}: {n} samples, median {hz:.1f} Hz, max_gap {max_gap:.3f}s")
            if hz < args.min_odom_hz or hz > args.max_odom_hz:
                raise RuntimeError(
                    f"{args.odom_topic} median frequency {hz:.1f} Hz outside "
                    f"[{args.min_odom_hz:.1f}, {args.max_odom_hz:.1f}] Hz. "
                    "The md requires real 45-55 Hz reference samples; do not fake by interpolation."
                )
            if max_gap > 0.10:
                raise RuntimeError(f"{args.odom_topic} max gap {max_gap:.3f}s > 0.10s")

        if args.preflight_only:
            print("[preflight] checks completed; no trial executed.")
            return 0

        if args.return_home in ("before-each", "every-trial"):
            if not return_home(node, home, "before_first_trial"):
                raise RuntimeError("failed to return home before first trial")

        completed = 0
        selected = 0
        for i, row in enumerate(selected_rows, start=1):
            if args.return_home == "before-each":
                if not return_home(node, home, f"before_{row.session_id}_{row.trial_id}"):
                    raise RuntimeError("failed to return home before trial")
            status, selected_for_csv = run_trial(node, row, args.attempt_id, i, home, args)
            completed += int(status == "complete")
            selected += int(selected_for_csv)
            print(f"[trial] status={status}, selected_for_csv={selected_for_csv}")
            if args.return_home == "every-trial":
                if not return_home(node, home, f"after_{row.session_id}_{row.trial_id}"):
                    print("[home] warning: failed to return home after trial; continuing")
            if args.inter_trial_pause_s > 0.0:
                time.sleep(args.inter_trial_pause_s)

        if args.return_home in ("session", "end"):
            if not return_home(node, home, "end_of_run"):
                raise RuntimeError("failed to return home at end")
        print(f"[done] completed={completed}/{len(selected_rows)}, selected_for_csv={selected}/{len(selected_rows)}")
        return 0
    finally:
        node.stop()
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run frozen Go2 plan.csv and export measure-window /Odometry samples.")
    p.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--session-id", action="append", help="Session to run; repeat for multiple. Default: all sessions.")
    p.add_argument("--trials", help="Trial IDs to run, e.g. '0,1,5-8'. Default: all selected session trials.")
    p.add_argument("--attempt-id", type=int, default=1)
    p.add_argument("--append", action="store_true", help="Append to existing delivery CSV/ledger files.")
    p.add_argument("--overwrite", action="store_true", help="Delete existing delivery CSV/ledger files before writing.")
    p.add_argument("--arm", action="store_true", help="Publish non-zero /cmd_vel commands. Without this, no robot motion and no final CSV.")
    p.add_argument("--preflight-only", action="store_true", help="Validate plan, READY state, pose, and /Odometry Hz, then exit.")

    p.add_argument("--cmd-topic", default="/cmd_vel")
    p.add_argument("--odom-topic", default="/Odometry")
    p.add_argument("--loc-health-topic", default="/loc_health")
    p.add_argument("--marker-topic", default="/go2_capture/trial_marker")
    p.add_argument("--actual-cmd-topic", default="/go2_capture/actual_cmd_vel")
    p.add_argument("--use-actual-cmd", dest="use_actual_cmd", action="store_true", default=True)
    p.add_argument("--no-use-actual-cmd", dest="use_actual_cmd", action="store_false")
    p.add_argument("--actual-cmd-timeout-s", type=float, default=1.0)
    p.add_argument("--command-rate-hz", type=float, default=50.0)
    p.add_argument("--require-ready", dest="require_ready", action="store_true", default=True)
    p.add_argument("--no-require-ready", dest="require_ready", action="store_false")
    p.add_argument("--ready-timeout-s", type=float, default=30.0)
    p.add_argument("--pose-timeout-s", type=float, default=10.0)
    p.add_argument("--skip-hz-check", action="store_true")
    p.add_argument("--hz-check-duration-s", type=float, default=3.0)
    p.add_argument("--min-odom-hz", type=float, default=45.0)
    p.add_argument("--max-odom-hz", type=float, default=55.0)
    p.add_argument("--min-samples", type=int, default=90)

    p.add_argument("--return-home", choices=["every-trial", "before-each", "session", "end", "never"], default="every-trial")
    p.add_argument("--home-x", type=float)
    p.add_argument("--home-y", type=float)
    p.add_argument("--home-yaw", type=float)
    p.add_argument("--max-radius-m", type=float, default=1.8, help="Abort a trial and home if distance from origin exceeds this radius. <=0 disables.")
    p.add_argument("--hard-radius-m", type=float, default=2.2, help="Absolute radius checked even while returning home. <=0 disables.")
    p.add_argument("--home-xy-tolerance-m", type=float, default=0.10)
    p.add_argument("--home-yaw-tolerance-rad", type=float, default=0.20)
    p.add_argument("--return-timeout-s", type=float, default=25.0)
    p.add_argument("--home-settle-s", type=float, default=0.5)
    p.add_argument("--home-kp-xy", type=float, default=0.7)
    p.add_argument("--home-kp-yaw", type=float, default=1.0)
    p.add_argument("--home-max-vx", type=float, default=0.25)
    p.add_argument("--home-max-vy", type=float, default=0.18)
    p.add_argument("--home-max-wz", type=float, default=0.45)
    p.add_argument("--inter-trial-pause-s", type=float, default=0.5)

    p.add_argument("--terrain-id", default="lab_flat")
    p.add_argument("--payload-kg", type=float, default=0.0)
    p.add_argument("--battery-ratio", type=float, default=1.0)
    p.add_argument("--gait-id", default="unknown")
    p.add_argument("--operator-notes", default="")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.append and args.overwrite:
        parser.error("--append and --overwrite cannot be used together")
    args.plan = args.plan.expanduser().resolve()
    args.manifest = args.manifest.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    try:
        return run_capture(args)
    except KeyboardInterrupt:
        print("\n[abort] interrupted; sent zero cmd_vel in cleanup", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
