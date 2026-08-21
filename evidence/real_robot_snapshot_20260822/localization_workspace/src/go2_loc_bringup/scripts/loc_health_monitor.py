#!/usr/bin/env python3
"""监视栈 A 定位健康, 发布 /loc_health (std_msgs/String).

格式:
  READY|<pos_x>,<pos_y>
  NOT_READY|<reason>
"""
import math
import time
from collections import deque

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import String


class LocHealthMonitor(Node):
    def __init__(self):
        super().__init__('loc_health_monitor')
        self.declare_parameter('stable_window_sec', 10.0)
        self.declare_parameter('max_position_std_xy', 0.15)
        self.declare_parameter('max_dist_from_init', 0.55)
        self.declare_parameter('max_single_jump', 0.45)
        self.declare_parameter('publish_hz', 2.0)

        self.stable_window = self.get_parameter('stable_window_sec').value
        self.max_std = self.get_parameter('max_position_std_xy').value
        self.max_dist_init = self.get_parameter('max_dist_from_init').value
        self.max_jump = self.get_parameter('max_single_jump').value

        self.init_xy = None
        self.samples = deque()  # (t, x, y)
        self.last_xy = None
        self.last_reason = 'waiting for /initialpose'

        self.pub = self.create_publisher(String, '/loc_health', 10)
        self.create_subscription(
            PoseWithCovarianceStamped, '/initialpose', self._on_init, 10)
        self.create_subscription(Odometry, '/Odometry', self._on_odom, 20)
        hz = self.get_parameter('publish_hz').value
        self.create_timer(1.0 / hz, self._publish)

        self.get_logger().info(
            'loc_health_monitor: 监视 /Odometry + /initialpose, '
            f'连续 {self.stable_window:.0f}s 稳定后发布 READY')

    def _on_init(self, msg: PoseWithCovarianceStamped):
        self.init_xy = (
            msg.pose.pose.position.x,
            msg.pose.pose.position.y,
        )
        self.samples.clear()
        self.last_xy = None
        self.last_reason = 'waiting for stable odometry'
        self.get_logger().info(
            f'收到 initialpose [{self.init_xy[0]:.2f}, {self.init_xy[1]:.2f}], '
            '等待 FAST-LIO 稳定...')

    def _on_odom(self, msg: Odometry):
        if self.init_xy is None:
            return
        t = time.monotonic()
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        if self.last_xy is not None:
            jump = math.hypot(x - self.last_xy[0], y - self.last_xy[1])
            if jump > self.max_jump:
                self.samples.clear()
                self.last_reason = f'position jump {jump:.2f}m > {self.max_jump:.2f}m'
                self.get_logger().warn(self.last_reason)
        self.last_xy = (x, y)
        self.samples.append((t, x, y))
        cutoff = t - self.stable_window
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def _evaluate(self):
        if self.init_xy is None:
            return False, self.last_reason
        if len(self.samples) < 5:
            return False, 'collecting odometry samples'
        t0 = self.samples[0][0]
        t1 = self.samples[-1][0]
        if t1 - t0 < self.stable_window * 0.9:
            return False, (
                f'need {self.stable_window:.0f}s stable window '
                f'(have {t1 - t0:.1f}s)')

        xs = [s[1] for s in self.samples]
        ys = [s[2] for s in self.samples]
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        std_x = math.sqrt(sum((x - mx) ** 2 for x in xs) / len(xs))
        std_y = math.sqrt(sum((y - my) ** 2 for y in ys) / len(ys))
        std_xy = math.hypot(std_x, std_y)
        if std_xy > self.max_std:
            return False, (
                f'displacement std {std_xy:.2f}m > {self.max_std:.2f}m')

        dist_init = math.hypot(mx - self.init_xy[0], my - self.init_xy[1])
        if dist_init > self.max_dist_init:
            return False, (
                f'dist from initialpose {dist_init:.2f}m > '
                f'{self.max_dist_init:.2f}m')

        return True, f'pos[{mx:.2f},{my:.2f}] std={std_xy:.2f}m'

    def _publish(self):
        ready, detail = self._evaluate()
        msg = String()
        if ready:
            msg.data = f'READY|{detail}'
        else:
            msg.data = f'NOT_READY|{detail}'
        self.pub.publish(msg)


def main():
    rclpy.init()
    node = LocHealthMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
