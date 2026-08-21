#!/usr/bin/env python3
"""命令行设定一个固定导航目标点。

用法:
  ros2 run go2_navigation send_goal X Y [YAW度]
示例:
  ros2 run go2_navigation send_goal 2.5 -1.0          # 朝向默认 0°
  ros2 run go2_navigation send_goal 2.5 -1.0 90       # 朝向 90°
  ros2 run go2_navigation send_goal 2.5 -1.0 --frame map

目标以 PoseStamped 发布到 /goal_pose, 由 nav_goal_manager 接收并转发到 /nav_goal。
"""
import argparse
import math
import sys

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped


def main():
    parser = argparse.ArgumentParser(description='发送固定导航目标到 /goal_pose')
    parser.add_argument('x', type=float, help='目标 X (map 系, 米)')
    parser.add_argument('y', type=float, help='目标 Y (map 系, 米)')
    parser.add_argument('yaw', type=float, nargs='?', default=0.0, help='目标朝向(度), 默认 0')
    parser.add_argument('--frame', default='map', help='坐标系, 默认 map')
    parser.add_argument('--topic', default='/goal_pose', help='发布话题, 默认 /goal_pose')
    args = parser.parse_args()

    rclpy.init()
    node = Node('send_goal')
    pub = node.create_publisher(PoseStamped, args.topic, 10)

    msg = PoseStamped()
    msg.header.frame_id = args.frame
    msg.header.stamp = node.get_clock().now().to_msg()
    msg.pose.position.x = args.x
    msg.pose.position.y = args.y
    yaw = math.radians(args.yaw)
    msg.pose.orientation.z = math.sin(yaw * 0.5)
    msg.pose.orientation.w = math.cos(yaw * 0.5)

    # 重发几次, 确保订阅者(可能刚建立连接)可靠收到
    for _ in range(10):
        msg.header.stamp = node.get_clock().now().to_msg()
        pub.publish(msg)
        rclpy.spin_once(node, timeout_sec=0.05)
        import time
        time.sleep(0.05)

    node.get_logger().info(
        f'已发送目标 -> {args.topic}: x={args.x:+.3f} y={args.y:+.3f} '
        f'yaw={args.yaw:+.1f}° frame={args.frame}')
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
