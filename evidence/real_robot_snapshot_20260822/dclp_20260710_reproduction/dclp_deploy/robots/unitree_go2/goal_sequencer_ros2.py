#!/usr/bin/env python3
"""ROS2 goal sequencer for Unitree Go2.

Reads the same yaml shape as deploy/goals_example.yaml, publishes PoseStamped
goals, and waits for the neural controller status topic to report reached.
"""

import argparse
import math
import os
import sys
import time
from threading import Lock

import rclpy
import yaml
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from std_msgs.msg import String


def yaw_to_quat(yaw: float):
    half = yaw * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


class GoalSequencerRos2(Node):
    def __init__(self, args):
        super().__init__("go2_goal_sequencer")
        self.args = args
        self.status_pub = self.create_publisher(String, args.status_topic, 1)
        self.topic_pub = self.create_publisher(PoseStamped, args.topic, 1)
        self.lock = Lock()
        self.latest_policy_status = None
        self.create_subscription(String, args.policy_status_topic, self._policy_status_cb, 10)

    def _policy_status_cb(self, msg: String):
        with self.lock:
            self.latest_policy_status = msg.data

    def _set_status(self, status: str):
        self.status_pub.publish(String(data=status))
        self.get_logger().info(status)

    def _make_pose(self, x: float, y: float, yaw: float, frame: str) -> PoseStamped:
        pose = PoseStamped()
        # Static map goals should use latest TF, not the time they were sent.
        pose.header.stamp.sec = 0
        pose.header.stamp.nanosec = 0
        pose.header.frame_id = frame
        pose.pose.position.x = x
        pose.pose.position.y = y
        qx, qy, qz, qw = yaw_to_quat(yaw)
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
        return pose

    def _wait_for_goal_subscriber(self, timeout_sec: float = 2.0):
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            if self.topic_pub.get_subscription_count() > 0:
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        self.get_logger().warn(
            f"no subscriber discovered on {self.args.topic}; publishing goal anyway"
        )
        return False

    def _send_policy_goal(self, pose: PoseStamped, timeout_sec: float) -> bool:
        with self.lock:
            self.latest_policy_status = None
        self._wait_for_goal_subscriber()
        self.topic_pub.publish(pose)
        deadline = time.monotonic() + timeout_sec
        next_republish = time.monotonic() + 1.0
        reached_values = {"reached", "REACHED", "Reached"}
        received_values = {
            "NAVIGATING",
            "WAITING_FOR_TF",
            "WAITING_FOR_SCAN",
            "WAITING_FOR_ODOM",
            "SAFE_STOP",
        }
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            with self.lock:
                status = self.latest_policy_status
            if status in reached_values:
                return True
            if status not in received_values and time.monotonic() >= next_republish:
                self.topic_pub.publish(pose)
                self.get_logger().info(
                    f"republished policy goal to {self.args.topic}; policy_status={status}"
                )
                next_republish = time.monotonic() + 1.0
        self.get_logger().warn(f"policy goal timed out after {timeout_sec:.1f}s")
        return False

    def run(self, cfg):
        frame = cfg.get("frame", "map")
        dwell_sec = float(cfg.get("dwell_sec", 2.0))
        timeout_sec = float(cfg.get("timeout_sec", self.args.timeout))
        auto_start = bool(cfg.get("auto_start", False)) or self.args.auto_start
        goals = cfg.get("goals", [])
        if not goals:
            raise RuntimeError("goals list is empty")

        self.get_logger().info(
            f"loaded {len(goals)} goals, frame={frame} dwell={dwell_sec:.1f}s "
            f"timeout={timeout_sec:.1f}s mode=policy"
        )

        if not auto_start:
            self._set_status("WAITING_FOR_ENTER")
            input("Press Enter to start goal sequence...")

        for idx, goal in enumerate(goals):
            x = float(goal["x"])
            y = float(goal["y"])
            yaw = float(goal.get("yaw", 0.0))
            self._set_status(f"GOING_TO_{idx}_({x:+.2f},{y:+.2f})")
            pose = self._make_pose(x, y, yaw, frame)

            ok = self._send_policy_goal(pose, timeout_sec)

            if ok:
                self._set_status(f"REACHED_{idx}")
                time.sleep(dwell_sec)
            else:
                self._set_status(f"FAILED_{idx}")
                if self.args.stop_on_failure:
                    return 1

        self._set_status("DONE")
        return 0

def build_parser():
    parser = argparse.ArgumentParser(description="Run Go2 ROS2 goal sequence")
    parser.add_argument("--goal-list", required=True)
    parser.add_argument("--topic", default="/move_base_simple/goal")
    parser.add_argument("--status-topic", default="/goal_sequencer/status")
    parser.add_argument("--policy-status-topic", default="/nav_status")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--auto-start", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not os.path.isfile(args.goal_list):
        print(f"goal list does not exist: {args.goal_list}", file=sys.stderr)
        return 1
    with open(args.goal_list, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    rclpy.init()
    node = GoalSequencerRos2(args)
    try:
        return node.run(cfg)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
