#!/usr/bin/env python3
"""Publish an AMCL initial pose with a slightly backdated ROS timestamp."""

import argparse
import math
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped


def build_msg(node, args):
    msg = PoseWithCovarianceStamped()
    stamp = node.get_clock().now() + rclpy.duration.Duration(seconds=args.stamp_offset)
    msg.header.stamp = stamp.to_msg()
    msg.header.frame_id = args.frame
    msg.pose.pose.position.x = args.x
    msg.pose.pose.position.y = args.y
    msg.pose.pose.position.z = 0.0
    msg.pose.pose.orientation.z = math.sin(args.yaw * 0.5)
    msg.pose.pose.orientation.w = math.cos(args.yaw * 0.5)
    msg.pose.covariance = [
        args.xy_cov, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, args.xy_cov, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, args.yaw_cov,
    ]
    return msg


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/initialpose")
    parser.add_argument("--frame", default="map")
    parser.add_argument("--x", type=float, default=-0.338)
    parser.add_argument("--y", type=float, default=-0.535)
    parser.add_argument("--yaw", type=float, default=-1.189)
    parser.add_argument("--xy-cov", type=float, default=0.25)
    parser.add_argument("--yaw-cov", type=float, default=0.0685)
    parser.add_argument("--stamp-offset", type=float, default=-0.2)
    parser.add_argument("--times", type=int, default=5)
    parser.add_argument("--rate", type=float, default=1.0)
    return parser.parse_args()


def main():
    args = parse_args()
    rclpy.init()
    node = rclpy.create_node("go2_initialpose_publisher")
    pub = node.create_publisher(PoseWithCovarianceStamped, args.topic, 10)
    period = 1.0 / max(args.rate, 1e-6)
    try:
        for idx in range(args.times):
            msg = build_msg(node, args)
            pub.publish(msg)
            node.get_logger().info(
                "published initial pose %d/%d: frame=%s x=%.3f y=%.3f yaw=%.3f stamp_offset=%.3f"
                % (idx + 1, args.times, args.frame, args.x, args.y, args.yaw, args.stamp_offset)
            )
            rclpy.spin_once(node, timeout_sec=0.05)
            if idx + 1 < args.times:
                time.sleep(period)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
