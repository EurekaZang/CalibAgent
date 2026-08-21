#!/usr/bin/env python3
"""Convert Unitree /uwbstate messages into PoseStamped policy goals."""

import argparse
import math
import os
import sys
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from unitree_go.msg import UwbState


def env_float(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_str(name, default):
    return os.environ.get(name, default)


def env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def angle_to_radians(value, units):
    angle = float(value)
    units = units.lower()
    if units == "deg" or (units == "auto" and abs(angle) > 2.0 * math.pi):
        angle = math.radians(angle)
    return angle


def normalize_yaw(value, units):
    yaw = angle_to_radians(value, units)
    return (yaw + math.pi) % (2.0 * math.pi) - math.pi


def yaw_to_quat(yaw):
    half = yaw * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


def yaw_from_quat(q):
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


def get_msg_float(msg, field_name, default=0.0):
    try:
        return float(getattr(msg, field_name))
    except Exception:
        return float(default)


def reliability_policy(name):
    value = str(name).strip().lower()
    if value in ("best_effort", "besteffort", "best-effort", "sensor"):
        return ReliabilityPolicy.BEST_EFFORT
    if value in ("reliable", ""):
        return ReliabilityPolicy.RELIABLE
    raise ValueError("unsupported reliability: %s" % name)


class Go2UwbRosGoalBridge(Node):
    def __init__(self, args):
        super().__init__("go2_uwb_ros_goal_bridge")
        self.args = args
        self.goal_frame = args.goal_frame.lstrip("/") or "base_link"

        uwb_qos = QoSProfile(
            reliability=reliability_policy(args.uwb_reliability),
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
        )
        odom_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=20,
        )
        goal_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.pub = self.create_publisher(PoseStamped, args.goal_topic, goal_qos)
        self.create_subscription(UwbState, args.uwb_topic, self._uwb_cb, uwb_qos)
        self.create_subscription(Odometry, args.odom_topic, self._odom_cb, odom_qos)
        self.timer = self.create_timer(1.0 / max(args.rate_hz, 1e-3), self._publish_goal)

        self.latest = None
        self.latest_time = None
        self.latest_goal = None
        self.latest_odom_pose = None
        self.last_published = None
        self.last_publish_time = 0.0
        self.last_log_time = 0.0
        self.packet_count = 0

    def _uwb_cb(self, msg):
        self.latest = msg
        self.latest_time = time.monotonic()
        self.packet_count += 1
        self.latest_goal = self._compute_goal(msg)

    def _odom_cb(self, msg):
        pose = msg.pose.pose
        self.latest_odom_pose = (
            float(pose.position.x),
            float(pose.position.y),
            yaw_from_quat(pose.orientation),
        )

    def _valid_distance(self, msg):
        distance = float(msg.distance_est) * self.args.distance_scale
        if not math.isfinite(distance):
            return False, distance
        if distance > self.args.max_distance:
            return False, distance
        if self.args.require_enabled and int(msg.enabled_from_app) == 0:
            return False, distance
        if int(msg.error_state) != 0 and not self.args.allow_error_state:
            return False, distance
        return True, distance

    def _compute_goal(self, msg):
        ok, distance_3d = self._valid_distance(msg)
        if not ok:
            self._warn_throttle(
                "ignore UWB distance_3d=%.3f error_state=%d enabled=%d"
                % (distance_3d, int(msg.error_state), int(msg.enabled_from_app))
            )
            return None

        raw_orientation = float(msg.orientation_est)
        raw_pitch = float(msg.pitch_est)
        yaw = normalize_yaw(raw_orientation * self.args.yaw_sign, self.args.yaw_units)
        pitch = angle_to_radians(raw_pitch, self.args.yaw_units)
        distance_xy = abs(distance_3d * math.cos(pitch)) if math.isfinite(pitch) else distance_3d
        if distance_xy < self.args.min_distance:
            distance_xy = 0.0

        rel_x = distance_xy * math.cos(yaw)
        rel_y = distance_xy * math.sin(yaw)
        goal_yaw = yaw
        frame = self.goal_frame
        x = rel_x
        y = rel_y

        if frame == "odom":
            if self.latest_odom_pose is None:
                self._warn_throttle("waiting odom for odom-frame UWB goal")
                return None
            odom_x, odom_y, odom_yaw = self.latest_odom_pose
            cos_yaw = math.cos(odom_yaw)
            sin_yaw = math.sin(odom_yaw)
            x = odom_x + cos_yaw * rel_x - sin_yaw * rel_y
            y = odom_y + sin_yaw * rel_x + cos_yaw * rel_y
            goal_yaw = normalize_yaw(odom_yaw + yaw, "rad")
        elif frame != "base_link":
            self._warn_throttle("unsupported UWB goal frame=%s; use base_link or odom" % frame)
            return None

        return {
            "frame": frame,
            "x": x,
            "y": y,
            "yaw": goal_yaw,
            "rel_x": rel_x,
            "rel_y": rel_y,
            "rel_yaw": yaw,
            "distance_xy": distance_xy,
            "distance_3d": distance_3d,
            "pitch": pitch,
            "raw_orientation": raw_orientation,
            "raw_pitch": raw_pitch,
            "base_yaw": get_msg_float(msg, "base_yaw", float("nan")),
            "tag_yaw": get_msg_float(msg, "tag_yaw", float("nan")),
        }

    def _publish_goal(self):
        msg_time = self.latest_time
        now = time.monotonic()
        if self.latest is None or msg_time is None:
            self._warn_throttle("waiting UWB")
            return
        if self.args.stale_timeout > 0.0 and now - msg_time > self.args.stale_timeout:
            self._warn_throttle("UWB stale age=%.3fs packets=%d" % (now - msg_time, self.packet_count))
            return
        goal = self.latest_goal
        if goal is None:
            return

        x = goal["x"]
        y = goal["y"]
        yaw = goal["yaw"]
        if not self._should_publish(x, y, yaw, now):
            return

        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = goal["frame"]
        pose.pose.position.x = x
        pose.pose.position.y = y
        qx, qy, qz, qw = yaw_to_quat(yaw)
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
        self.pub.publish(pose)
        self.last_published = (x, y, yaw)
        self.last_publish_time = now

        if now - self.last_log_time >= self.args.log_period:
            self.last_log_time = now
            self.get_logger().info(
                "UWB goal %s: frame=%s x=%.3f y=%.3f rel_x=%.3f rel_y=%.3f "
                "dist_xy=%.3f dist_3d=%.3f yaw=%.3f rel_yaw=%.3f pitch=%.3f "
                "orientation_est=%.3f pitch_est=%.3f base_yaw=%.3f tag_yaw=%.3f packets=%d"
                % (
                    self.args.goal_topic,
                    goal["frame"],
                    x,
                    y,
                    goal["rel_x"],
                    goal["rel_y"],
                    goal["distance_xy"],
                    goal["distance_3d"],
                    yaw,
                    goal["rel_yaw"],
                    goal["pitch"],
                    goal["raw_orientation"],
                    goal["raw_pitch"],
                    goal["base_yaw"],
                    goal["tag_yaw"],
                    self.packet_count,
                )
            )

    def _should_publish(self, x, y, yaw, now):
        if self.last_published is None:
            return True
        last_x, last_y, last_yaw = self.last_published
        moved = math.hypot(x - last_x, y - last_y)
        yaw_delta = abs((yaw - last_yaw + math.pi) % (2.0 * math.pi) - math.pi)
        if moved >= self.args.position_epsilon:
            return True
        if yaw_delta >= self.args.yaw_epsilon:
            return True
        if self.args.republish_period > 0.0 and now - self.last_publish_time >= self.args.republish_period:
            return True
        return False

    def _warn_throttle(self, text):
        now = time.monotonic()
        if now - self.last_log_time >= self.args.log_period:
            self.last_log_time = now
            self.get_logger().warn(text)


def build_parser():
    parser = argparse.ArgumentParser(description="Unitree /uwbstate to ROS2 goal bridge")
    parser.add_argument("--uwb-topic", default=env_str("UWB_ROS_TOPIC", "/uwbstate"))
    parser.add_argument("--odom-topic", default=env_str("UWB_ODOM_TOPIC", "/odom"))
    parser.add_argument("--goal-topic", default=env_str("UWB_GOAL_TOPIC", "/move_base_simple/goal"))
    parser.add_argument("--goal-frame", choices=["base_link", "odom"], default=env_str("UWB_GOAL_FRAME", "odom"))
    parser.add_argument("--rate-hz", type=float, default=env_float("UWB_GOAL_RATE_HZ", 10.0))
    parser.add_argument("--stale-timeout", type=float, default=env_float("UWB_STALE_TIMEOUT", 0.5))
    parser.add_argument("--min-distance", type=float, default=env_float("UWB_MIN_DISTANCE", 0.25))
    parser.add_argument("--max-distance", type=float, default=env_float("UWB_MAX_DISTANCE", 20.0))
    parser.add_argument("--distance-scale", type=float, default=env_float("UWB_DISTANCE_SCALE", 1.0))
    parser.add_argument("--yaw-units", choices=["auto", "rad", "deg"], default=env_str("UWB_YAW_UNITS", "auto"))
    parser.add_argument("--yaw-sign", type=float, default=env_float("UWB_YAW_SIGN", 1.0))
    parser.add_argument("--uwb-reliability", default=env_str("UWB_RELIABILITY", "reliable"))
    parser.add_argument("--position-epsilon", type=float, default=env_float("UWB_GOAL_POSITION_EPSILON", 0.05))
    parser.add_argument("--yaw-epsilon", type=float, default=env_float("UWB_GOAL_YAW_EPSILON", 0.05))
    parser.add_argument("--republish-period", type=float, default=env_float("UWB_GOAL_REPUBLISH_PERIOD", 0.2))
    parser.add_argument("--log-period", type=float, default=env_float("UWB_LOG_PERIOD", 1.0))
    parser.add_argument("--require-enabled", action="store_true", default=env_bool("UWB_REQUIRE_ENABLED", False))
    parser.add_argument("--allow-error-state", action="store_true", default=env_bool("UWB_ALLOW_ERROR_STATE", False))
    return parser


def main():
    args = build_parser().parse_args()
    rclpy.init()
    node = Go2UwbRosGoalBridge(args)
    node.get_logger().info(
        "UWB ROS goal bridge ready: uwb=%s goal=%s frame=%s reliability=%s"
        % (args.uwb_topic, args.goal_topic, args.goal_frame, args.uwb_reliability)
    )
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
