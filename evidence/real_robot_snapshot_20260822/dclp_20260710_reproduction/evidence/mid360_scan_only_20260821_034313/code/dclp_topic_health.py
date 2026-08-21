#!/usr/bin/env python3
"""Short-lived ROS2 topic freshness/rate checker for DCLP bringup."""

from __future__ import annotations

import argparse
import importlib
import math
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy


def _load_msg_type(type_name: str):
    parts = str(type_name).split("/")
    if len(parts) != 3 or parts[1] != "msg":
        raise ValueError("message type must look like package/msg/Type, got %r" % type_name)
    module = importlib.import_module(parts[0] + ".msg")
    return getattr(module, parts[2])


class TopicHealthNode(Node):
    def __init__(self, topic: str, msg_type, reliability: str):
        super().__init__("dclp_topic_health_check")
        rel = ReliabilityPolicy.RELIABLE if reliability == "reliable" else ReliabilityPolicy.BEST_EFFORT
        qos = QoSProfile(reliability=rel, history=HistoryPolicy.KEEP_LAST, depth=10)
        self.count = 0
        self.first_mono = None
        self.last_mono = None
        self.ages_ms = []
        self.last_age_ms = None
        self.last_extra = ""
        self.valid_beam_counts = []
        self.create_subscription(msg_type, topic, self._cb, qos)

    def _cb(self, msg):
        now_mono = time.monotonic()
        if self.count == 0:
            self.first_mono = now_mono
        self.count += 1
        self.last_mono = now_mono
        header = getattr(msg, "header", None)
        if header is not None:
            stamp = getattr(header, "stamp", None)
            if stamp is not None:
                stamp_sec = float(stamp.sec) + float(stamp.nanosec) * 1e-9
                if stamp_sec > 0.0:
                    now_ros = self.get_clock().now().nanoseconds * 1e-9
                    age_ms = (now_ros - stamp_sec) * 1000.0
                    self.ages_ms.append(age_ms)
                    self.last_age_ms = age_ms
            frame = getattr(header, "frame_id", "")
            self.last_extra = "frame=%s" % frame
        if hasattr(msg, "ranges"):
            range_min = float(getattr(msg, "range_min", 0.0))
            range_max = float(getattr(msg, "range_max", float("inf")))
            valid_beams = sum(
                1
                for value in msg.ranges
                if math.isfinite(float(value)) and range_min <= float(value) <= range_max
            )
            self.valid_beam_counts.append(valid_beams)
            self.last_extra += " beams=%d valid=%d" % (len(msg.ranges), valid_beams)
        elif hasattr(msg, "width") and hasattr(msg, "height"):
            self.last_extra += " points=%d" % (int(msg.width) * int(msg.height))

    def rate_hz(self) -> float:
        if self.count <= 1 or self.first_mono is None or self.last_mono is None:
            return 0.0
        elapsed = max(self.last_mono - self.first_mono, 1e-9)
        return float(self.count - 1) / elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a ROS2 topic has fresh messages.")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--type", required=True, dest="type_name")
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--min-rate", type=float, default=1.0)
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--max-age-ms", type=float, default=0.0)
    parser.add_argument(
        "--min-valid-beams",
        type=int,
        default=0,
        help="Require every recent LaserScan frame to contain at least this many finite beams.",
    )
    parser.add_argument(
        "--recent-window",
        type=int,
        default=10,
        help="Use only the newest N timestamped messages for freshness; ignores startup backlog.",
    )
    parser.add_argument("--reliability", choices=("best_effort", "reliable"), default="best_effort")
    args = parser.parse_args()

    msg_type = _load_msg_type(args.type_name)
    rclpy.init()
    node = TopicHealthNode(args.topic, msg_type, args.reliability)
    try:
        end = time.monotonic() + max(float(args.duration), 0.1)
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.05)
        rate = node.rate_hz()
        recent_n = max(int(args.recent_window), 1)
        recent_ages = node.ages_ms[-recent_n:]
        max_age = max(node.ages_ms) if node.ages_ms else None
        recent_max_age = max(recent_ages) if recent_ages else None
        recent_avg_age = (sum(recent_ages) / len(recent_ages)) if recent_ages else None
        ok = node.count >= int(args.min_count) and rate >= float(args.min_rate)
        if args.max_age_ms > 0.0:
            ok = ok and node.last_age_ms is not None and node.last_age_ms <= float(args.max_age_ms)
            ok = ok and recent_max_age is not None and recent_max_age <= float(args.max_age_ms)
        recent_beams = node.valid_beam_counts[-recent_n:]
        if args.min_valid_beams > 0:
            ok = (
                ok
                and bool(recent_beams)
                and min(recent_beams) >= int(args.min_valid_beams)
            )
        age_text = "age_ms=n/a"
        if recent_max_age is not None:
            age_text = "age_ms recent_avg=%.1f recent_max=%.1f last=%.1f all_max=%.1f" % (
                recent_avg_age,
                recent_max_age,
                node.last_age_ms,
                max_age,
            )
        beam_text = ""
        if node.valid_beam_counts:
            ordered_beams = sorted(node.valid_beam_counts)
            beam_text = "valid_beams recent_min=%d p50=%d all_min=%d zero=%d" % (
                min(recent_beams),
                ordered_beams[len(ordered_beams) // 2],
                min(ordered_beams),
                sum(value == 0 for value in node.valid_beam_counts),
            )
        print(
            "%s count=%d rate=%.2fHz %s %s %s"
            % (
                "OK" if ok else "BAD",
                node.count,
                rate,
                age_text,
                node.last_extra.strip(),
                beam_text,
            )
        )
        return 0 if ok else 2
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
