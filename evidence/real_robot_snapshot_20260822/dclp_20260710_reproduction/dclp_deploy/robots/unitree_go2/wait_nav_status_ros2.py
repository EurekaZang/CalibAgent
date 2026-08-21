#!/usr/bin/env python3
"""Wait for a terminal DCLP navigation status with matching ROS 2 QoS."""

import argparse
import os
import signal
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import String


EXIT_REACHED = 0
EXIT_SAFE_STOP = 10
EXIT_MONITOR_ERROR = 2
EXIT_TIMEOUT = 124
EXIT_INTERRUPTED = 130


class NavStatusWaiter(Node):
    def __init__(self, topic):
        super().__init__("dclp_nav_status_waiter")
        self.last_status = ""
        self.terminal_status = ""
        self.armed = False
        self.navigating_seen = False
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.subscription = self.create_subscription(
            String, topic, self._status_callback, qos
        )

    def _status_callback(self, msg):
        status = str(msg.data).strip()
        if not status:
            return
        if status != self.last_status:
            self.last_status = status
            print("[nav-status] %s" % status, file=sys.stderr, flush=True)
        if not self.armed:
            return
        if status == "NAVIGATING":
            self.navigating_seen = True
        elif self.navigating_seen and status in ("REACHED", "SAFE_STOP"):
            self.terminal_status = status

    def arm(self):
        self.terminal_status = ""
        self.navigating_seen = False
        self.armed = True


def build_parser():
    parser = argparse.ArgumentParser(
        description="Wait for REACHED or SAFE_STOP on a DCLP String status topic"
    )
    parser.add_argument("--topic", default="/nav_status")
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--ready-timeout", type=float, default=10.0)
    return parser


def write_ready_file(path):
    tmp_path = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp_path, "w", encoding="utf-8") as stream:
        stream.write("ready\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp_path, path)


def interrupt_on_signal(_signum, _frame):
    raise KeyboardInterrupt


def main():
    args = build_parser().parse_args()
    if args.timeout <= 0.0 or args.ready_timeout <= 0.0:
        print("timeouts must be positive", file=sys.stderr)
        return EXIT_MONITOR_ERROR

    node = None
    try:
        signal.signal(signal.SIGINT, interrupt_on_signal)
        signal.signal(signal.SIGTERM, interrupt_on_signal)
        rclpy.init(args=[])
        node = NavStatusWaiter(args.topic)

        ready_deadline = time.monotonic() + args.ready_timeout
        while rclpy.ok():
            remaining = ready_deadline - time.monotonic()
            if remaining <= 0.0:
                print(
                    "status monitor ready timeout: publisher_count=%d last_status=%s"
                    % (node.count_publishers(args.topic), node.last_status or "unknown"),
                    file=sys.stderr,
                )
                return EXIT_MONITOR_ERROR
            rclpy.spin_once(node, timeout_sec=min(0.2, remaining))
            if node.count_publishers(args.topic) > 0 and node.last_status:
                break

        if not rclpy.ok():
            print("ROS context stopped before status monitor became ready", file=sys.stderr)
            return EXIT_MONITOR_ERROR
        if node.last_status == "NAVIGATING":
            print(
                "refusing to arm from an already-NAVIGATING baseline",
                file=sys.stderr,
            )
            return EXIT_MONITOR_ERROR

        # Arm before exposing readiness so a post-ready transition cannot be
        # lost between the shell handshake and goal publication.
        node.arm()
        write_ready_file(args.ready_file)

        deadline = time.monotonic() + args.timeout
        while rclpy.ok() and not node.terminal_status:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                break
            rclpy.spin_once(node, timeout_sec=min(0.2, remaining))

        if not rclpy.ok():
            print("ROS context stopped while waiting for terminal status", file=sys.stderr)
            return EXIT_MONITOR_ERROR

        status = node.terminal_status or node.last_status
        print(status, flush=True)
        if node.terminal_status == "REACHED":
            return EXIT_REACHED
        if node.terminal_status == "SAFE_STOP":
            return EXIT_SAFE_STOP
        return EXIT_TIMEOUT
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except Exception as exc:
        print("status monitor error: %s" % exc, file=sys.stderr)
        return EXIT_MONITOR_ERROR
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
