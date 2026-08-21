#!/usr/bin/env python3
"""命令行设定导航起点/终点。

用法:
  ros2 run go2_navigation set_route SX SY EX EY [frame]
  例: ros2 run go2_navigation set_route 0.0 0.0 3.5 1.2

原理: 先发 /route_reset 复位, 再依次向 /clicked_point 注入两个点,
复用 nav_goal_manager 的拾取逻辑(第1点=起点, 第2点=终点), 由其发布
/start_point /end_point 与 RViz 标记。需 nav_goal_manager 处于 click_mode=startend。
"""
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped
from std_msgs.msg import Empty


def main():
    args = sys.argv[1:]
    if len(args) < 4:
        print('用法: ros2 run go2_navigation set_route SX SY EX EY [frame]')
        return 1
    sx, sy, ex, ey = (float(args[0]), float(args[1]), float(args[2]), float(args[3]))
    frame = args[4] if len(args) > 4 else 'map'

    rclpy.init()
    node = Node('set_route')
    pub_reset = node.create_publisher(Empty, '/route_reset', 10)
    pub_click = node.create_publisher(PointStamped, '/clicked_point', 10)

    def spin(sec):
        t0 = time.time()
        while time.time() - t0 < sec:
            rclpy.spin_once(node, timeout_sec=0.02)

    # 等待 nav_goal_manager 订阅就绪
    t0 = time.time()
    while pub_click.get_subscription_count() == 0 and time.time() - t0 < 3.0:
        spin(0.1)
    if pub_click.get_subscription_count() == 0:
        node.get_logger().warn('/clicked_point 无订阅者, nav_goal_manager 可能未运行。')

    pub_reset.publish(Empty())
    spin(0.4)

    def click(x, y):
        m = PointStamped()
        m.header.frame_id = frame
        m.header.stamp = node.get_clock().now().to_msg()
        m.point.x, m.point.y, m.point.z = x, y, 0.0
        pub_click.publish(m)

    click(sx, sy)   # 起点
    spin(0.5)
    click(ex, ey)   # 终点
    spin(0.6)

    node.get_logger().info(
        f'已设定: 起点({sx:.2f},{sy:.2f}) 终点({ex:.2f},{ey:.2f}) frame={frame}')
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
