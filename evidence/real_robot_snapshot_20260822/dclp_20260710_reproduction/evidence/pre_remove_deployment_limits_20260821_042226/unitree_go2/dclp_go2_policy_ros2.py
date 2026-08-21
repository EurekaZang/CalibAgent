#!/usr/bin/env python3
"""ROS2 DCLP controller for Unitree Go2.

This node keeps the tested Go2 hardware chain:
  /scan + /odom + /move_base_simple/goal -> policy -> /go2_policy/cmd_vel + ZMQ

Policy-facing logic follows DCLP:
  real scan -> 548-D DCLP observation -> normalized action -> DCLP cmd_vel mapping.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import math
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import sys
import time
from threading import Lock

import numpy as np
import rclpy
import tf2_ros
import zmq
from geometry_msgs.msg import Point, PoseStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String


ROBOT_DIR = os.path.dirname(os.path.abspath(__file__))
DEPLOY_ROOT = os.path.abspath(os.path.join(ROBOT_DIR, "../.."))
REPO_ROOT = os.path.abspath(os.path.join(DEPLOY_ROOT, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if ROBOT_DIR not in sys.path:
    sys.path.insert(0, ROBOT_DIR)

try:
    from velocity_compensation import compensate_velocity
    _HAS_COMPENSATION = True
except ImportError:
    _HAS_COMPENSATION = False
    compensate_velocity = None

from dclp_deploy.dclp_deploy_core import (
    DEFAULT_RANGE_FILL,
    DclpRobotContext,
    build_dclp_laser_features_from_points,
    build_dclp_observation,
    build_target_tail,
    clean_scan_ranges,
    transform_scan_points_to_base,
    wrap_to_pi,
)
from dclp_deploy.dclp_policy_backend import (
    DclpPolicyBackend,
)
from dclp_deploy.dclp_schema import CONTROL_PERIOD_SEC, OBS_DIM


def env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


class DclpGo2PolicyRos2(Node):
    def __init__(self):
        super().__init__("dclp_go2_policy_ros2")
        self.lock = Lock()
        self.control_lock = Lock()

        self.model_path = env_str("POLICY_MODEL_PATH", env_str("MODEL_PATH", ""))
        self.policy_backend = env_str("POLICY_BACKEND", "pth")
        self.policy_device = env_str("POLICY_DEVICE", "cpu")
        self.gpu_mem_frac = env_float("POLICY_GPU_MEM_FRAC", 0.1)
        self.policy_deterministic = env_bool("POLICY_DETERMINISTIC", True)

        self.scan_topic = env_str("POLICY_SCAN_TOPIC", env_str("SCAN_TOPIC", "/scan"))
        self.odom_topic = env_str("POLICY_ODOM_TOPIC", env_str("ODOM_TOPIC", "/odom"))
        self.goal_topic = env_str("POLICY_GOAL_TOPIC", env_str("GOAL_TOPIC", "/move_base_simple/goal"))
        self.relative_goal_topic = env_str("POLICY_RELATIVE_GOAL_TOPIC", "/dclp_relative_goal")
        self.status_topic = env_str("POLICY_STATUS_TOPIC", "/nav_status")
        self.cmd_vel_topic = env_str("POLICY_CMD_VEL_TOPIC", "/go2_policy/cmd_vel")
        self.enable_topic = env_str("POLICY_ENABLE_TOPIC", "")
        self.base_frame = env_str("POLICY_BASE_FRAME", env_str("BASE_FRAME", "base_link"))
        self.global_frame = env_str("POLICY_GLOBAL_FRAME", "odom")
        self.zmq_bind_addr = env_str("POLICY_ZMQ_BIND", "tcp://*:5596")
        self.zmq_include_meta = env_bool("POLICY_ZMQ_INCLUDE_META", True)

        self.control_rate_hz = env_float("POLICY_RATE_HZ", 5.0)
        self.control_period_sec = env_float("POLICY_CONTROL_PERIOD_SEC", CONTROL_PERIOD_SEC)
        self.scan_timeout = env_float("POLICY_SCAN_TIMEOUT", 0.7)
        self.scan_stamp_timeout = env_float("POLICY_SCAN_STAMP_TIMEOUT", self.scan_timeout)
        self.odom_timeout = env_float("POLICY_ODOM_TIMEOUT", 0.7)
        self.odom_stamp_timeout = env_float("POLICY_ODOM_STAMP_TIMEOUT", self.odom_timeout)
        self.goal_timeout = env_float("POLICY_GOAL_TIMEOUT", 0.0)
        self.tf_timeout = env_float("POLICY_TF_TIMEOUT", 0.05)
        self.enabled = env_bool("POLICY_ENABLED_ON_START", True)
        self.stop_when_reached = env_bool("POLICY_STOP_WHEN_REACHED", True)
        self.goal_reach_distance = env_float("POLICY_GOAL_TOLERANCE", 0.4)
        self.min_obstacle_distance = env_float("POLICY_MIN_OBSTACLE_DISTANCE", 0.0)
        self.timing_warn_ms = env_float("POLICY_TIMING_WARN_MS", 180.0)

        self.speed_scale = env_float("POLICY_SPEED_SCALE", 1.0)
        requested_compensation = env_bool("POLICY_COMPENSATE", False)
        default_compensation_mode = "guarded" if requested_compensation else "off"
        self.compensation_mode = env_str(
            "POLICY_COMPENSATION_MODE", default_compensation_mode
        ).strip().lower()
        if self.compensation_mode not in ("off", "raw", "guarded"):
            raise ValueError(
                "POLICY_COMPENSATION_MODE must be off, raw, or guarded, got %r"
                % self.compensation_mode
            )
        self.use_compensation = self.compensation_mode != "off"
        self.action_mapping_mode = env_str("POLICY_ACTION_MAPPING", "range").strip().lower()
        if self.action_mapping_mode not in ("range", "legacy_floor"):
            raise ValueError(
                "POLICY_ACTION_MAPPING must be range or legacy_floor, got %r"
                % self.action_mapping_mode
            )
        self.accel_limiter_mode = env_str(
            "POLICY_ACCEL_LIMITER_MODE", "last_cmd_dt"
        ).strip().lower()
        if self.accel_limiter_mode not in ("last_cmd_dt", "last_cmd_fixed", "odom_fixed"):
            raise ValueError(
                "POLICY_ACCEL_LIMITER_MODE must be last_cmd_dt, last_cmd_fixed, or odom_fixed, got %r"
                % self.accel_limiter_mode
            )
        self.experiment_id = env_str("POLICY_EXPERIMENT_ID", "")
        self.experiment_profile = env_str("POLICY_EXPERIMENT_PROFILE", "")
        self.effective_config_path = env_str("POLICY_EFFECTIVE_CONFIG_PATH", "")
        self.scan_invalid_fill = env_float("POLICY_SCAN_INVALID_FILL", DEFAULT_RANGE_FILL)
        self.scan_min_value = env_float("POLICY_SCAN_MIN_VALUE", 0.2)
        self.straighten_front_goal_angle = env_float("POLICY_STRAIGHTEN_FRONT_GOAL_ANGLE", 0.20)
        self.straighten_front_clear_angle = env_float("POLICY_STRAIGHTEN_FRONT_CLEAR_ANGLE", 0.35)
        self.straighten_front_clear_range = env_float("POLICY_STRAIGHTEN_FRONT_CLEAR_RANGE", 1.2)
        self.straighten_front_goal_w_limit = env_float("POLICY_STRAIGHTEN_FRONT_GOAL_W_LIMIT", 0.0)
        self.cmd_vel_v_cap = env_float("POLICY_CMD_VEL_V_CAP", env_float("POLICY_MAX_LINEAR", 0.66))
        self.cmd_vel_w_cap = env_float("POLICY_CMD_VEL_W_CAP", env_float("POLICY_MAX_ANGULAR", 0.56))
        self.cmd_vel_v_min = env_float("POLICY_CMD_VEL_V_MIN", env_float("POLICY_CMD_VEL_V_FLOOR", 0.0))
        self.cmd_vel_w_min = env_float("POLICY_CMD_VEL_W_MIN", env_float("POLICY_CMD_VEL_W_FLOOR", 0.0))
        self.cmd_vel_v_floor = env_float("POLICY_CMD_VEL_V_FLOOR", self.cmd_vel_v_min)
        self.cmd_vel_w_floor = env_float("POLICY_CMD_VEL_W_FLOOR", self.cmd_vel_w_min)
        self.robot = DclpRobotContext(
            length1=env_float("DCLP_LENGTH1", 0.504),
            length2=env_float("DCLP_LENGTH2", 0.504),
            width=env_float("DCLP_WIDTH", 0.4464),
            max_linear_speed=env_float("POLICY_MAX_LINEAR", 0.66),
            max_angular_speed=env_float("POLICY_MAX_ANGULAR", 0.56),
            max_linear_acc=env_float("POLICY_MAX_LINEAR_ACC", 2.0),
            max_angular_acc=env_float("POLICY_MAX_ANGULAR_ACC", 2.0),
        )

        self.trajectory_log_enabled = env_bool("POLICY_TRAJECTORY_LOG_ENABLED", True)
        self.trajectory_log_dir = env_str(
            "POLICY_TRAJECTORY_LOG_DIR",
            os.path.join(DEPLOY_ROOT, "trajectory_logs"),
        )
        self.trajectory_log_basename = env_str("POLICY_TRAJECTORY_LOG_BASENAME", "")
        self.trajectory_log_rate_hz = env_float("POLICY_TRAJECTORY_LOG_RATE_HZ", 2.0)

        try:
            import torch
            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
        except Exception:
            pass
        self.backend = DclpPolicyBackend(
            model_path=self.model_path,
            backend_type=self.policy_backend,
            device=self.policy_device,
            gpu_mem_frac=self.gpu_mem_frac,
            deterministic=self.policy_deterministic,
        )

        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        status_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.create_subscription(LaserScan, self.scan_topic, self._scan_cb, sensor_qos)
        self.create_subscription(Odometry, self.odom_topic, self._odom_cb, sensor_qos)
        self.create_subscription(PoseStamped, self.goal_topic, self._goal_cb, 10)
        self.create_subscription(Point, self.relative_goal_topic, self._relative_goal_cb, 10)
        if self.enable_topic:
            self.create_subscription(Bool, self.enable_topic, self._enable_cb, 10)

        self.status_pub = self.create_publisher(String, self.status_topic, status_qos)
        self.cmd_vel_pub = self.create_publisher(Twist, self.cmd_vel_topic, 1)
        self.tf_buffer = tf2_ros.Buffer(cache_time=Duration(seconds=10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.zmq_context = zmq.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.PUB)
        self.zmq_socket.bind(self.zmq_bind_addr)

        self.latest_scan = None
        self.latest_scan_time = None
        self.latest_scan_seq = 0
        self.last_control_scan_seq = -1
        self.latest_odom = None
        self.latest_odom_time = None
        self.latest_goal = None
        self.latest_goal_time = None
        self.last_cmd = np.zeros(2, dtype=np.float32)
        self.last_control_time = time.monotonic()
        self._scan_rx_count = 0
        self._odom_rx_count = 0
        self._loop_count = 0
        self._cmd_seq = 0
        self.status = ""
        self._last_warn_time = {}
        self._last_info_time = {}

        self.trajectory_log_path = None
        self._trajectory_log_file = None
        self._trajectory_log_writer = None
        self._trajectory_log_seq = 0
        self._last_trajectory_log_time = None
        self._init_trajectory_logger()

        if self.use_compensation and not _HAS_COMPENSATION:
            raise RuntimeError(
                "compensation mode %s requested but velocity_compensation.py is unavailable"
                % self.compensation_mode
            )

        self.effective_config = self._build_effective_config()
        self._write_effective_config()

        self.timer = self.create_timer(1.0 / max(self.control_rate_hz, 1e-3), self._control_loop)
        self.get_logger().info(
            "Go2 DCLP policy ready: backend=%s scan=%s odom=%s goal=%s rel_goal=%s global=%s zmq=%s rate=%.1fHz scan_stamp_timeout=%.2fs experiment=%s profile=%s compensation=%s mapping=%s limiter=%s config=%s"
            % (
                json.dumps(self.backend.summary(), sort_keys=True),
                self.scan_topic,
                self.odom_topic,
                self.goal_topic,
                self.relative_goal_topic,
                self.global_frame,
                self.zmq_bind_addr,
                self.control_rate_hz,
                self.scan_stamp_timeout,
                self.experiment_id or "<unset>",
                self.experiment_profile or "<unset>",
                self.compensation_mode,
                self.action_mapping_mode,
                self.accel_limiter_mode,
                json.dumps(self.effective_config, sort_keys=True, separators=(",", ":")),
            )
        )
        self._set_status("IDLE")

    @staticmethod
    def _sha256_file(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _build_effective_config(self):
        model_path = os.path.realpath(os.path.expanduser(self.model_path))
        core_path = os.path.join(DEPLOY_ROOT, "dclp_deploy_core.py")
        compensation_path = os.path.join(ROBOT_DIR, "velocity_compensation.py")
        return {
            "schema_version": 1,
            "written_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(),
            "experiment_id": self.experiment_id,
            "experiment_profile": self.experiment_profile,
            "policy_source": os.path.realpath(__file__),
            "policy_source_sha256": self._sha256_file(__file__),
            "deploy_core_source": os.path.realpath(core_path),
            "deploy_core_source_sha256": self._sha256_file(core_path),
            "compensation_source": os.path.realpath(compensation_path),
            "compensation_source_sha256": self._sha256_file(compensation_path),
            "model_path": model_path,
            "model_sha256": self._sha256_file(model_path),
            "backend": self.backend.summary(),
            "compensation_mode": self.compensation_mode,
            "compensation_available": bool(_HAS_COMPENSATION),
            "action_mapping_mode": self.action_mapping_mode,
            "accel_limiter_mode": self.accel_limiter_mode,
            "scan_topic": self.scan_topic,
            "odom_topic": self.odom_topic,
            "goal_topic": self.goal_topic,
            "relative_goal_topic": self.relative_goal_topic,
            "control_rate_hz": self.control_rate_hz,
            "control_period_sec": self.control_period_sec,
            "scan_timeout": self.scan_timeout,
            "scan_stamp_timeout": self.scan_stamp_timeout,
            "odom_timeout": self.odom_timeout,
            "odom_stamp_timeout": self.odom_stamp_timeout,
            "speed_scale": self.speed_scale,
            "max_linear": self.robot.max_linear_speed,
            "max_angular": self.robot.max_angular_speed,
            "min_linear": self.cmd_vel_v_min,
            "min_angular": self.cmd_vel_w_min,
            "floor_linear": self.cmd_vel_v_floor,
            "floor_angular": self.cmd_vel_w_floor,
            "cap_linear": self.cmd_vel_v_cap,
            "cap_angular": self.cmd_vel_w_cap,
            "max_linear_acc": self.robot.max_linear_acc,
            "max_angular_acc": self.robot.max_angular_acc,
            "dclp_length1": self.robot.length1,
            "dclp_length2": self.robot.length2,
            "dclp_width": self.robot.width,
            "straighten_front_goal_angle": self.straighten_front_goal_angle,
            "straighten_front_clear_angle": self.straighten_front_clear_angle,
            "straighten_front_clear_range": self.straighten_front_clear_range,
            "straighten_front_goal_w_limit": self.straighten_front_goal_w_limit,
            "trajectory_log_path": self.trajectory_log_path,
        }

    def _write_effective_config(self):
        if not self.effective_config_path:
            return
        path = os.path.realpath(os.path.expanduser(self.effective_config_path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = path + ".tmp.%d" % os.getpid()
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self.effective_config, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)

    def _scan_cb(self, msg):
        with self.lock:
            self.latest_scan = msg
            self.latest_scan_time = time.monotonic()
            self._scan_rx_count += 1
            self.latest_scan_seq = self._scan_rx_count
            count = self._scan_rx_count
        if count == 1:
            self.get_logger().info(
                "received first scan: frame=%s beams=%d" % (msg.header.frame_id, len(msg.ranges))
            )

    def _odom_cb(self, msg):
        with self.lock:
            self.latest_odom = msg
            self.latest_odom_time = time.monotonic()
            self._odom_rx_count += 1
            count = self._odom_rx_count
        if count == 1:
            self.get_logger().info(
                "received first odom: frame=%s child=%s" % (msg.header.frame_id, msg.child_frame_id)
            )

    def _goal_cb(self, msg):
        goal = PoseStamped()
        goal.header = msg.header
        if not goal.header.frame_id:
            goal.header.frame_id = self.global_frame
        goal.header.stamp = Time(seconds=0).to_msg()
        goal.pose = msg.pose
        with self.lock:
            self.latest_goal = goal
            self.latest_goal_time = time.monotonic()
        self.last_cmd[:] = 0.0
        self.last_control_time = time.monotonic()
        self._set_status("NAVIGATING")
        self.get_logger().info(
            "received goal: frame=%s x=%.3f y=%.3f"
            % (goal.header.frame_id, goal.pose.position.x, goal.pose.position.y)
        )

    def _relative_goal_cb(self, msg):
        """Accept relative goal in robot body frame: x=right, y=forward (meters).

        ROS convention: x=forward, y=left, z=up.
        Body frame: forward=(cos,sin), right=(sin,-cos), left=(-sin,cos).
        """
        right = float(msg.x)
        forward = float(msg.y)
        robot_pose = self._lookup_transform_2d(self.global_frame, self.base_frame)
        if robot_pose is None:
            self.get_logger().warn(
                "relative goal ignored: cannot get robot pose in %s" % self.global_frame
            )
            return
        rx, ry, ryaw = robot_pose
        # forward:  (cos(ryaw), sin(ryaw))
        # right:    (sin(ryaw), -cos(ryaw))   — ROS y轴指向左，右=负y
        gx = rx + forward * math.cos(ryaw) + right * math.sin(ryaw)
        gy = ry + forward * math.sin(ryaw) - right * math.cos(ryaw)

        goal = PoseStamped()
        goal.header.frame_id = self.global_frame
        goal.header.stamp = Time(seconds=0).to_msg()
        goal.pose.position.x = gx
        goal.pose.position.y = gy
        goal.pose.position.z = 0.0
        goal.pose.orientation.w = 1.0
        with self.lock:
            self.latest_goal = goal
            self.latest_goal_time = time.monotonic()
        self.last_cmd[:] = 0.0
        self.last_control_time = time.monotonic()
        self._set_status("NAVIGATING")
        self.get_logger().info(
            "received relative goal: right=%.3f forward=%.3f -> global=(%.3f, %.3f) frame=%s"
            % (right, forward, gx, gy, self.global_frame)
        )

    def _enable_cb(self, msg):
        self.enabled = bool(msg.data)
        self._set_status("IDLE" if self.enabled else "DISABLED")

    @staticmethod
    def _yaw_from_quaternion(q):
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        return float(math.atan2(siny_cosp, cosy_cosp))

    def _lookup_transform_2d(self, target_frame, source_frame, stamp=None):
        source_frame = (source_frame or "").lstrip("/")
        target_frame = (target_frame or "").lstrip("/")
        if not source_frame:
            return None
        if source_frame == target_frame:
            return 0.0, 0.0, 0.0
        lookup_stamp = stamp if stamp is not None else Time()
        try:
            tf_msg = self.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                lookup_stamp,
                timeout=Duration(seconds=self.tf_timeout),
            )
        except Exception as first_exc:
            requested_latest = stamp is None or getattr(stamp, "nanoseconds", 0) == 0
            if requested_latest:
                self._warn_throttle(
                    "tf:%s:%s" % (target_frame, source_frame),
                    "TF lookup %s <- %s failed: %s" % (target_frame, source_frame, first_exc),
                    2.0,
                )
                return None
            try:
                tf_msg = self.tf_buffer.lookup_transform(
                    target_frame,
                    source_frame,
                    Time(),
                    timeout=Duration(seconds=self.tf_timeout),
                )
            except Exception as exc:
                self._warn_throttle(
                    "tf:%s:%s" % (target_frame, source_frame),
                    "TF lookup %s <- %s failed: %s" % (target_frame, source_frame, exc),
                    2.0,
                )
                return None
        tx = float(tf_msg.transform.translation.x)
        ty = float(tf_msg.transform.translation.y)
        yaw = self._yaw_from_quaternion(tf_msg.transform.rotation)
        return tx, ty, yaw

    def _transform_goal_to_base(self, goal_msg):
        source_frame = goal_msg.header.frame_id or self.global_frame
        tf_2d = self._lookup_transform_2d(self.base_frame, source_frame)
        if tf_2d is None:
            return None
        tx, ty, yaw = tf_2d
        gx = float(goal_msg.pose.position.x)
        gy = float(goal_msg.pose.position.y)
        return np.array(
            [
                tx + math.cos(yaw) * gx - math.sin(yaw) * gy,
                ty + math.sin(yaw) * gx + math.cos(yaw) * gy,
            ],
            dtype=np.float32,
        )

    def _transform_goal_to_global(self, goal_msg):
        source_frame = goal_msg.header.frame_id or self.global_frame
        gx = float(goal_msg.pose.position.x)
        gy = float(goal_msg.pose.position.y)
        if source_frame.lstrip("/") == self.global_frame.lstrip("/"):
            return np.array([gx, gy], dtype=np.float32)
        tf_2d = self._lookup_transform_2d(self.global_frame, source_frame)
        if tf_2d is None:
            return None
        tx, ty, yaw = tf_2d
        return np.array(
            [
                tx + math.cos(yaw) * gx - math.sin(yaw) * gy,
                ty + math.sin(yaw) * gx + math.cos(yaw) * gy,
            ],
            dtype=np.float32,
        )

    def _scan_points_in_base(self, scan_msg):
        raw = np.asarray(scan_msg.ranges, dtype=np.float32).reshape(-1)
        if raw.size == 0:
            return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)
        scan_range_min = max(float(getattr(scan_msg, "range_min", 0.0)), self.scan_min_value)
        scan_range_max = float(getattr(scan_msg, "range_max", self.scan_invalid_fill))
        clean = clean_scan_ranges(
            raw,
            scan_range_min=scan_range_min,
            scan_range_max=scan_range_max,
            fill_range=self.scan_invalid_fill,
        )
        stamp = Time.from_msg(scan_msg.header.stamp)
        if stamp.nanoseconds == 0:
            stamp = None
        tf_2d = self._lookup_transform_2d(self.base_frame, scan_msg.header.frame_id, stamp)
        if tf_2d is None:
            return None, None
        sensor_angles = (
            float(scan_msg.angle_min)
            + np.arange(clean.size, dtype=np.float32) * float(scan_msg.angle_increment)
        )
        return transform_scan_points_to_base(
            ranges=clean,
            sensor_angles=sensor_angles,
            transform_2d=tf_2d,
        )

    @staticmethod
    def _odom_speed(odom_msg):
        return np.array(
            [
                float(odom_msg.twist.twist.linear.x),
                float(odom_msg.twist.twist.angular.z),
            ],
            dtype=np.float32,
        )

    def _init_trajectory_logger(self):
        if not self.trajectory_log_enabled:
            return
        log_dir = os.path.expanduser(str(self.trajectory_log_dir))
        if not os.path.isabs(log_dir):
            log_dir = os.path.join(DEPLOY_ROOT, log_dir)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        basename = str(self.trajectory_log_basename or "trajectory_{}.csv".format(timestamp))
        if not basename.endswith(".csv"):
            basename += ".csv"
        path = os.path.join(log_dir, basename)
        try:
            os.makedirs(log_dir, exist_ok=True)
            need_header = (not os.path.exists(path)) or os.path.getsize(path) == 0
            self._trajectory_log_file = open(path, "a", buffering=1, newline="")
            self._trajectory_log_writer = csv.writer(self._trajectory_log_file)
            if need_header:
                self._trajectory_log_writer.writerow(
                    [
                        "schema_version",
                        "seq",
                        "wall_time",
                        "ros_time",
                        "status",
                        "global_frame",
                        "base_frame",
                        "robot_x",
                        "robot_y",
                        "robot_yaw",
                        "goal_x",
                        "goal_y",
                        "goal_frame",
                        "goal_raw_x",
                        "goal_raw_y",
                        "goal_in_base_x",
                        "goal_in_base_y",
                        "target_dist",
                        "target_angle",
                        "obs_dim",
                        "coverage_count",
                        "empty_group_count",
                        "min_pooled_range",
                        "normalized_action_linear",
                        "normalized_action_angular",
                        "cmd_published_linear",
                        "cmd_published_angular",
                        "experiment_id",
                        "experiment_profile",
                        "compensation_mode",
                        "action_mapping_mode",
                        "accel_limiter_mode",
                        "cmd_target_linear",
                        "cmd_target_angular",
                        "cmd_desired_linear",
                        "cmd_desired_angular",
                        "cmd_compensated_raw_linear",
                        "cmd_compensated_raw_angular",
                        "compensation_linear_accepted",
                        "compensation_angular_accepted",
                        "compensation_linear_reason",
                        "compensation_angular_reason",
                        "front_straightening_active",
                    ]
                )
            self.trajectory_log_path = path
            self.get_logger().info(
                "trajectory log enabled: %s (rate=%.2f Hz)"
                % (path, self.trajectory_log_rate_hz)
            )
        except Exception as exc:
            self.trajectory_log_enabled = False
            self._trajectory_log_file = None
            self._trajectory_log_writer = None
            self.get_logger().warn("trajectory log disabled: %s" % exc)

    def _write_trajectory_sample(
        self,
        now,
        goal_msg,
        goal_in_base,
        target_tail,
        obs_dim,
        scan_diag,
        normalized_action,
        published_cmd,
        status,
        cmd_diag=None,
        force=False,
    ):
        if not self.trajectory_log_enabled or self._trajectory_log_writer is None:
            return
        force_status_transition = force and self.status != status
        if (
            not force_status_transition
            and self.trajectory_log_rate_hz > 0.0
            and self._last_trajectory_log_time is not None
        ):
            min_dt = 1.0 / self.trajectory_log_rate_hz
            if now - self._last_trajectory_log_time < min_dt:
                return
        robot_pose = self._lookup_transform_2d(self.global_frame, self.base_frame)
        goal_global = self._transform_goal_to_global(goal_msg)
        if robot_pose is None or goal_global is None:
            self._warn_throttle(
                "traj",
                "trajectory skipped: cannot transform robot or goal into %s" % self.global_frame,
                5.0,
            )
            return
        robot_x, robot_y, robot_yaw = robot_pose
        source_frame = goal_msg.header.frame_id or self.global_frame
        ros_time = self.get_clock().now().nanoseconds * 1e-9
        cmd_diag = cmd_diag or {}
        target_cmd = np.asarray(cmd_diag.get("target_cmd", (float("nan"), float("nan"))))
        desired_cmd = np.asarray(cmd_diag.get("desired_cmd", (float("nan"), float("nan"))))
        raw_comp = np.asarray(cmd_diag.get("raw_comp", (float("nan"), float("nan"))))
        try:
            self._trajectory_log_writer.writerow(
                [
                    2,
                    int(self._trajectory_log_seq),
                    datetime.datetime.now().isoformat(timespec="milliseconds"),
                    "%.9f" % ros_time,
                    str(status),
                    str(self.global_frame),
                    str(self.base_frame),
                    "%.6f" % robot_x,
                    "%.6f" % robot_y,
                    "%.6f" % robot_yaw,
                    "%.6f" % float(goal_global[0]),
                    "%.6f" % float(goal_global[1]),
                    str(source_frame),
                    "%.6f" % float(goal_msg.pose.position.x),
                    "%.6f" % float(goal_msg.pose.position.y),
                    "%.6f" % float(goal_in_base[0]),
                    "%.6f" % float(goal_in_base[1]),
                    "%.6f" % float(target_tail[0]),
                    "%.6f" % float(target_tail[1]),
                    int(obs_dim),
                    int(scan_diag.get("coverage_count", -1)),
                    int(scan_diag.get("empty_group_count", -1)),
                    "%.6f" % float(scan_diag.get("min_pooled_range", float("nan"))),
                    "%.6f" % float(normalized_action[0]),
                    "%.6f" % float(normalized_action[1]),
                    "%.6f" % float(published_cmd[0]),
                    "%.6f" % float(published_cmd[1]),
                    str(self.experiment_id),
                    str(self.experiment_profile),
                    str(self.compensation_mode),
                    str(self.action_mapping_mode),
                    str(self.accel_limiter_mode),
                    "%.6f" % float(target_cmd[0]),
                    "%.6f" % float(target_cmd[1]),
                    "%.6f" % float(desired_cmd[0]),
                    "%.6f" % float(desired_cmd[1]),
                    "%.6f" % float(raw_comp[0]),
                    "%.6f" % float(raw_comp[1]),
                    int(bool(cmd_diag.get("comp_v_accepted", False))),
                    int(bool(cmd_diag.get("comp_w_accepted", False))),
                    str(cmd_diag.get("comp_v_reason", "not_evaluated")),
                    str(cmd_diag.get("comp_w_reason", "not_evaluated")),
                    int(bool(cmd_diag.get("straighten_front_goal", False))),
                ]
            )
            self._trajectory_log_file.flush()
            self._trajectory_log_seq += 1
            self._last_trajectory_log_time = now
        except Exception as exc:
            self._warn_throttle("traj_write", "trajectory write failed: %s" % exc, 5.0)

    def close_trajectory_logger(self):
        if self._trajectory_log_file is None:
            return
        try:
            self._trajectory_log_file.flush()
            self._trajectory_log_file.close()
        except Exception:
            pass
        self._trajectory_log_file = None
        self._trajectory_log_writer = None

    def _set_status(self, status):
        if self.status == status:
            return
        self.status = status
        self.status_pub.publish(String(data=status))

    def _warn_throttle(self, key, msg, period=2.0):
        now = time.monotonic()
        if now - self._last_warn_time.get(key, 0.0) >= period:
            self._last_warn_time[key] = now
            self.get_logger().warn(msg)

    def _info_throttle(self, key, msg, period=1.0):
        now = time.monotonic()
        if now - self._last_info_time.get(key, 0.0) >= period:
            self._last_info_time[key] = now
            self.get_logger().info(msg)

    def _message_stamp_age_ms(self, msg, ros_now_sec=None):
        if msg is None or not hasattr(msg, "header"):
            return None
        stamp = getattr(msg.header, "stamp", None)
        if stamp is None:
            return None
        stamp_sec = float(stamp.sec) + float(stamp.nanosec) * 1e-9
        if stamp_sec <= 0.0:
            return None
        if ros_now_sec is None:
            ros_now_sec = self.get_clock().now().nanoseconds * 1e-9
        return (float(ros_now_sec) - stamp_sec) * 1000.0

    def _send_cmd(
        self,
        linear,
        angular,
        *,
        scan_msg=None,
        scan_rx_mono=None,
        odom_msg=None,
        odom_rx_mono=None,
        loop_start_mono=None,
    ):
        linear = float(linear)
        angular = float(angular)
        twist = Twist()
        twist.linear.x = linear
        twist.angular.z = angular
        self.cmd_vel_pub.publish(twist)
        if self.zmq_include_meta:
            now_mono = time.monotonic()
            payload = {
                "linear": linear,
                "angular": angular,
                "seq": int(self._cmd_seq),
                "send_monotonic": now_mono,
            }
            self._cmd_seq += 1
            if loop_start_mono is not None:
                payload["loop_to_send_ms"] = (now_mono - float(loop_start_mono)) * 1000.0
            ros_now_sec = self.get_clock().now().nanoseconds * 1e-9
            if scan_msg is not None:
                scan_age_ms = self._message_stamp_age_ms(scan_msg, ros_now_sec)
                if scan_age_ms is not None:
                    payload["scan_age_ms"] = scan_age_ms
                payload["scan_frame"] = scan_msg.header.frame_id
            if scan_rx_mono is not None:
                payload["scan_rx_age_ms"] = (now_mono - float(scan_rx_mono)) * 1000.0
            if odom_msg is not None:
                odom_age_ms = self._message_stamp_age_ms(odom_msg, ros_now_sec)
                if odom_age_ms is not None:
                    payload["odom_age_ms"] = odom_age_ms
            if odom_rx_mono is not None:
                payload["odom_rx_age_ms"] = (now_mono - float(odom_rx_mono)) * 1000.0
            if "scan_age_ms" in payload and "odom_age_ms" in payload:
                payload["sensor_stamp_skew_ms"] = abs(
                    float(payload["scan_age_ms"]) - float(payload["odom_age_ms"])
                )
            self.zmq_socket.send_string(json.dumps(payload, separators=(",", ":")))
        else:
            self.zmq_socket.send_string(json.dumps([linear, angular]))

    def _stop(self, reason):
        self._send_cmd(0.0, 0.0)
        self.last_cmd[:] = 0.0
        self.last_control_time = time.monotonic()
        self._warn_throttle("stop", "DCLP stop: %s" % reason, 2.0)

    def _ready(self, now, scan_msg, scan_time, odom_msg, odom_time, goal_msg, goal_time):
        if not self.enabled:
            return False, "DISABLED", "controller disabled"
        if scan_msg is None or scan_time is None:
            return False, "WAITING_FOR_SCAN", "waiting scan"
        if odom_msg is None or odom_time is None:
            return False, "WAITING_FOR_ODOM", "waiting odom"
        if goal_msg is None or goal_time is None:
            return False, "IDLE", "waiting goal"
        if self.scan_timeout > 0.0 and now - scan_time > self.scan_timeout:
            return False, "WAITING_FOR_SCAN", "scan timeout"
        if self.odom_timeout > 0.0 and now - odom_time > self.odom_timeout:
            return False, "WAITING_FOR_ODOM", "odom timeout"
        if self.goal_timeout > 0.0 and now - goal_time > self.goal_timeout:
            return False, "IDLE", "goal timeout"
        if self.scan_stamp_timeout > 0.0:
            age_ms = self._message_stamp_age_ms(scan_msg)
            if age_ms is None:
                return False, "WAITING_FOR_SCAN", "scan stamp missing"
            age = age_ms * 1e-3
            if age > self.scan_stamp_timeout:
                return False, "WAITING_FOR_SCAN", "scan stamp stale %.3fs" % age
            if age < -0.1:
                return False, "WAITING_FOR_SCAN", "scan stamp %.3fs in future" % (-age)
        if self.odom_stamp_timeout > 0.0:
            age_ms = self._message_stamp_age_ms(odom_msg)
            if age_ms is None:
                return False, "WAITING_FOR_ODOM", "odom stamp missing"
            age = age_ms * 1e-3
            if age > self.odom_stamp_timeout:
                return False, "WAITING_FOR_ODOM", "odom stamp stale %.3fs" % age
            if age < -0.1:
                return False, "WAITING_FOR_ODOM", "odom stamp %.3fs in future" % (-age)
        return True, "NAVIGATING", ""

    @staticmethod
    def _scale_signed_action(value, min_speed, max_speed):
        action = max(-1.0, min(1.0, float(value)))
        if abs(action) <= 1e-6:
            return 0.0
        lo = abs(float(min_speed))
        hi = abs(float(max_speed))
        if hi < lo:
            lo, hi = hi, lo
        magnitude = lo + abs(action) * (hi - lo)
        return (1.0 if action > 0.0 else -1.0) * magnitude

    def _scale_action_to_cmd(self, normalized_action):
        action = np.asarray(normalized_action, dtype=np.float32).reshape(-1)
        if action.shape[0] < 2:
            raise ValueError("DCLP normalized action must contain at least 2 values, got %d" % action.shape[0])
        return np.asarray(
            [
                self._scale_signed_action(action[0], self.cmd_vel_v_min, self.robot.max_linear_speed),
                self._scale_signed_action(action[1], self.cmd_vel_w_min, self.robot.max_angular_speed),
            ],
            dtype=np.float32,
        )

    def _legacy_action_target(self, normalized_action):
        action = np.clip(np.asarray(normalized_action, dtype=np.float32).reshape(-1)[:2], -1.0, 1.0)
        if action.shape[0] < 2:
            raise ValueError("DCLP normalized action must contain at least 2 values")
        return np.asarray(
            [
                float(action[0]) * float(self.robot.max_linear_speed),
                float(action[1]) * float(self.robot.max_angular_speed),
            ],
            dtype=np.float32,
        )

    @staticmethod
    def _keep_compensation_in_range(desired, compensated, min_speed, max_speed):
        value, _, _ = DclpGo2PolicyRos2._guard_compensation_axis(
            desired, compensated, min_speed, max_speed
        )
        return value

    @staticmethod
    def _guard_compensation_axis(desired, compensated, min_speed, max_speed):
        desired = float(desired)
        compensated = float(compensated)
        if abs(desired) <= 1e-6:
            return 0.0, False, "zero_desired"
        if not np.isfinite(compensated):
            return desired, False, "nonfinite"
        sign = 1.0 if desired > 0.0 else -1.0
        if compensated * sign <= 0.0:
            return desired, False, "sign_flip"
        lo = abs(float(min_speed))
        hi = abs(float(max_speed))
        if hi < lo:
            lo, hi = hi, lo
        comp_mag = abs(compensated)
        # Compensation is allowed only while it stays inside the same configured
        # min/max speed range. If it would exceed the range, keep the policy's
        # own scaled value instead of clipping to a constant cap.
        if comp_mag < lo:
            return max(-hi, min(hi, desired)), False, "below_min"
        if comp_mag > hi:
            return max(-hi, min(hi, desired)), False, "above_max"
        return sign * comp_mag, True, "accepted"

    def _compensate_cmd_in_range(self, desired_cmd):
        desired = np.asarray(desired_cmd, dtype=np.float32).reshape(-1)
        if desired.shape[0] < 2:
            raise ValueError("desired_cmd must contain linear and angular speed")
        raw_v, raw_w = compensate_velocity(float(desired[0]), float(desired[1]))
        return np.asarray(
            [
                self._keep_compensation_in_range(
                    desired[0], raw_v, self.cmd_vel_v_min, self.robot.max_linear_speed
                ),
                self._keep_compensation_in_range(
                    desired[1], raw_w, self.cmd_vel_w_min, self.robot.max_angular_speed
                ),
            ],
            dtype=np.float32,
        )

    def _apply_compensation(self, desired_cmd):
        desired = np.asarray(desired_cmd, dtype=np.float32).reshape(-1)
        if self.compensation_mode == "off":
            return desired.copy(), np.full(2, np.nan, dtype=np.float32), (False, False), ("off", "off")
        raw = np.asarray(
            compensate_velocity(float(desired[0]), float(desired[1])), dtype=np.float32
        )
        if self.compensation_mode == "raw":
            return raw, raw.copy(), (True, True), ("raw", "raw")
        out_v, accept_v, reason_v = self._guard_compensation_axis(
            desired[0], raw[0], self.cmd_vel_v_min, self.robot.max_linear_speed
        )
        out_w, accept_w, reason_w = self._guard_compensation_axis(
            desired[1], raw[1], self.cmd_vel_w_min, self.robot.max_angular_speed
        )
        return (
            np.asarray([out_v, out_w], dtype=np.float32),
            raw,
            (accept_v, accept_w),
            (reason_v, reason_w),
        )

    def _limit_cmd_accel(self, target_cmd, now):
        target = np.asarray(target_cmd, dtype=np.float32).reshape(-1)
        if target.shape[0] < 2:
            raise ValueError("target_cmd must contain linear and angular speed")
        current = np.asarray(self.last_cmd, dtype=np.float32).reshape(-1)
        dt = max(float(now) - float(self.last_control_time), 1e-3)
        max_v_delta = max(float(self.robot.max_linear_acc), 0.0) * dt
        max_w_delta = max(float(self.robot.max_angular_acc), 0.0) * dt
        v = float(target[0]) if max_v_delta <= 0.0 else float(
            np.clip(target[0], current[0] - max_v_delta, current[0] + max_v_delta)
        )
        w = float(target[1]) if max_w_delta <= 0.0 else float(
            np.clip(target[1], current[1] - max_w_delta, current[1] + max_w_delta)
        )
        return np.array([v, w], dtype=np.float32)

    def _limit_cmd_accel_fixed(self, target_cmd, current_cmd):
        target = np.asarray(target_cmd, dtype=np.float32).reshape(-1)
        current = np.asarray(current_cmd, dtype=np.float32).reshape(-1)
        period = max(float(self.control_period_sec), 0.0)
        max_v_delta = max(float(self.robot.max_linear_acc), 0.0) * period
        max_w_delta = max(float(self.robot.max_angular_acc), 0.0) * period
        return np.asarray(
            [
                np.clip(target[0], current[0] - max_v_delta, current[0] + max_v_delta),
                np.clip(target[1], current[1] - max_w_delta, current[1] + max_w_delta),
            ],
            dtype=np.float32,
        )

    def _clip_cmd(self, cmd):
        v = float(cmd[0])
        w = float(cmd[1])
        v = max(-self.cmd_vel_v_cap, min(self.cmd_vel_v_cap, v))
        w = max(-self.cmd_vel_w_cap, min(self.cmd_vel_w_cap, w))
        return np.array([v, w], dtype=np.float32)

    def _apply_legacy_floors(self, cmd, *, apply_w_floor=True):
        v = float(cmd[0])
        w = float(cmd[1])
        if self.cmd_vel_v_floor > 0.0 and abs(v) > 1e-6:
            v = math.copysign(max(abs(v), self.cmd_vel_v_floor), v)
        if apply_w_floor and self.cmd_vel_w_floor > 0.0 and abs(w) > 1e-6:
            w = math.copysign(max(abs(w), self.cmd_vel_w_floor), w)
        return self._clip_cmd((v, w))

    def _is_front_sector_clear(self, scan_diag):
        angle_limit = max(float(self.straighten_front_clear_angle), 0.0)
        if angle_limit <= 0.0:
            return True
        range_limit = max(float(self.straighten_front_clear_range), 0.0)
        if range_limit <= 0.0:
            return True
        pooled = scan_diag.get("pooled_ranges") if isinstance(scan_diag, dict) else None
        centers = scan_diag.get("ros_group_centers") if isinstance(scan_diag, dict) else None
        if pooled is None or centers is None:
            return False
        ranges = np.asarray(pooled, dtype=np.float32).reshape(-1)
        angles = wrap_to_pi(np.asarray(centers, dtype=np.float32).reshape(-1))
        if ranges.shape != angles.shape or ranges.size == 0:
            return False
        front = np.abs(angles) <= np.float32(angle_limit)
        if not np.any(front):
            return True
        return bool(np.all(ranges[front] >= np.float32(range_limit)))

    def _should_straighten_front_goal(self, target_tail, scan_diag):
        goal_angle_limit = max(float(self.straighten_front_goal_angle), 0.0)
        if goal_angle_limit <= 0.0:
            return False
        if abs(float(target_tail[1])) > goal_angle_limit:
            return False
        return self._is_front_sector_clear(scan_diag)

    def _control_loop(self):
        if not self.control_lock.acquire(blocking=False):
            return
        try:
            self._control_loop_impl()
        finally:
            self.control_lock.release()

    def _control_loop_impl(self):
        t = {}  # per-step perf_counter timestamps
        t["loop"] = time.perf_counter()
        now = time.monotonic()
        with self.lock:
            scan_msg = self.latest_scan
            scan_time = self.latest_scan_time
            scan_seq = self.latest_scan_seq
            odom_msg = self.latest_odom
            odom_time = self.latest_odom_time
            goal_msg = self.latest_goal
            goal_time = self.latest_goal_time

        ready, status, reason = self._ready(
            now,
            scan_msg,
            scan_time,
            odom_msg,
            odom_time,
            goal_msg,
            goal_time,
        )
        if not ready:
            self._stop(reason)
            self._set_status(status)
            return
        if scan_seq == self.last_control_scan_seq:
            return
        self.last_control_scan_seq = scan_seq

        t["goal_tf"] = time.perf_counter()
        goal_in_base = self._transform_goal_to_base(goal_msg)
        if goal_in_base is None:
            self._stop("goal TF unavailable")
            self._set_status("WAITING_FOR_TF")
            return

        current_vw = self._odom_speed(odom_msg)
        t["tail"] = time.perf_counter()
        target_tail = build_target_tail(
            goal_in_base=goal_in_base,
            current_vw=current_vw,
            robot=self.robot,
        )
        if float(target_tail[0]) <= self.goal_reach_distance:
            if self.stop_when_reached:
                self._stop("goal reached")
            self._set_status("REACHED")
            zero = np.zeros(2, dtype=np.float32)
            self._write_trajectory_sample(
                now,
                goal_msg,
                goal_in_base,
                target_tail,
                OBS_DIM,
                {"coverage_count": -1, "empty_group_count": -1, "min_pooled_range": float("nan")},
                zero,
                zero,
                "REACHED",
                force=True,
            )
            return

        t["scan_tf"] = time.perf_counter()
        ranges, angles = self._scan_points_in_base(scan_msg)
        if ranges is None:
            self._stop("scan TF unavailable")
            self._set_status("WAITING_FOR_TF")
            return

        t["features"] = time.perf_counter()
        laser_features, scan_diag = build_dclp_laser_features_from_points(
            ranges=ranges,
            angles=angles,
            robot=self.robot,
            range_fill=self.scan_invalid_fill,
        )
        if self.min_obstacle_distance > 0.0:
            nearest = float(scan_diag["min_pooled_range"])
            if nearest < self.min_obstacle_distance:
                self._stop("obstacle %.3f < %.3f" % (nearest, self.min_obstacle_distance))
                self._set_status("SAFE_STOP")
                return

        obs = build_dclp_observation(laser_features, target_tail)
        t["inference"] = time.perf_counter()
        normalized_action = self.backend.act(obs)
        t["cmd_conv"] = time.perf_counter()
        if self.action_mapping_mode == "legacy_floor":
            target_cmd = self._legacy_action_target(normalized_action)
        else:
            target_cmd = self._scale_action_to_cmd(normalized_action)

        if self.accel_limiter_mode == "odom_fixed":
            cmd = self._limit_cmd_accel_fixed(target_cmd, current_vw)
        elif self.accel_limiter_mode == "last_cmd_fixed":
            cmd = self._limit_cmd_accel_fixed(target_cmd, self.last_cmd)
        else:
            cmd = self._limit_cmd_accel(target_cmd, now)
        v = float(cmd[0]) * float(self.speed_scale)
        w = float(cmd[1]) * float(self.speed_scale)

        straighten_front_goal = self._should_straighten_front_goal(target_tail, scan_diag)
        if straighten_front_goal:
            if self.straighten_front_goal_w_limit > 0.0:
                w = max(
                    -float(self.straighten_front_goal_w_limit),
                    min(float(self.straighten_front_goal_w_limit), w),
                )
            else:
                w = 0.0

        desired_cmd = np.asarray([v, w], dtype=np.float32)
        compensated_cmd, raw_comp, comp_accepted, comp_reasons = self._apply_compensation(
            desired_cmd
        )
        v = float(compensated_cmd[0])
        w = float(compensated_cmd[1])
        if self.use_compensation:
            if straighten_front_goal:
                if self.straighten_front_goal_w_limit > 0.0:
                    w = max(
                        -float(self.straighten_front_goal_w_limit),
                        min(float(self.straighten_front_goal_w_limit), w),
                    )
                else:
                    w = 0.0

        cmd = self._clip_cmd((v, w))
        if self.action_mapping_mode == "legacy_floor":
            cmd = self._apply_legacy_floors(
                cmd, apply_w_floor=not straighten_front_goal
            )
        t["send"] = time.perf_counter()

        self._send_cmd(
            cmd[0],
            cmd[1],
            scan_msg=scan_msg,
            scan_rx_mono=scan_time,
            odom_msg=odom_msg,
            odom_rx_mono=odom_time,
            loop_start_mono=now,
        )
        self.last_cmd = cmd.copy()
        self.last_control_time = now
        self._set_status("NAVIGATING")
        self._write_trajectory_sample(
            now,
            goal_msg,
            goal_in_base,
            target_tail,
            obs.shape[0],
            scan_diag,
            normalized_action,
            cmd,
            "NAVIGATING",
            cmd_diag={
                "target_cmd": target_cmd,
                "desired_cmd": desired_cmd,
                "raw_comp": raw_comp,
                "comp_v_accepted": comp_accepted[0],
                "comp_w_accepted": comp_accepted[1],
                "comp_v_reason": comp_reasons[0],
                "comp_w_reason": comp_reasons[1],
                "straighten_front_goal": straighten_front_goal,
            },
        )

        # ---- 延迟报告 ----
        t["end"] = time.perf_counter()
        times_ms = {k: (t[k] - t.get(prev, t["loop"])) * 1000.0
                     for k, prev in [("goal_tf", "loop"), ("tail", "goal_tf"),
                                     ("scan_tf", "tail"), ("features", "scan_tf"),
                                     ("inference", "features"), ("cmd_conv", "inference"),
                                     ("send", "cmd_conv"), ("end", "send")]}
        total_ms = (t["end"] - t["loop"]) * 1000.0

        # 端到端: 从 scan header.stamp 到 cmd_vel 发布
        if scan_msg is not None:
            scan_stamp_sec = scan_msg.header.stamp.sec + scan_msg.header.stamp.nanosec * 1e-9
            now_sec = self.get_clock().now().nanoseconds * 1e-9
            e2e_ms = (now_sec - scan_stamp_sec) * 1000.0
        else:
            e2e_ms = 0.0

        self._loop_count += 1
        if self._loop_count % 10 == 1:
            self.get_logger().info(
                "⏱ v=%.3f w=%.3f dist=%.2f | total=%.1fms "
                "(tf=%.1f feat=%.1f infer=%.1f conv=%.1f) | e2e_scan→cmd=%.1fms | cov=%d/90"
                % (
                    cmd[0], cmd[1], target_tail[0],
                    total_ms,
                    times_ms["goal_tf"] + times_ms["scan_tf"],
                    times_ms["features"], times_ms["inference"], times_ms["cmd_conv"],
                    e2e_ms,
                    scan_diag["coverage_count"],
                ),
            )

        if total_ms > self.timing_warn_ms:
            self._warn_throttle(
                "timing",
                "DCLP policy loop slow: %.1f ms total (infer=%.1f feat=%.1f scan_tf=%.1f)"
                % (total_ms, times_ms["inference"], times_ms["features"], times_ms["scan_tf"]),
                1.0,
            )

    def shutdown(self):
        try:
            self._send_cmd(0.0, 0.0)
        except Exception:
            pass
        self.close_trajectory_logger()
        self.backend.close()
        try:
            self.zmq_socket.close(0)
            self.zmq_context.term()
        except Exception:
            pass


def main():
    rclpy.init()
    node = DclpGo2PolicyRos2()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
