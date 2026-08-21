#!/usr/bin/env python3
"""Go2 导航目标管理节点 (nav_goal_manager)。

职责(只做"目标管理 + 地图发布 + 与定位通信", 不含具体路径规划):
  1. 加载 2D 栅格地图(map_server 同款 pgm/yaml), 发布 /map(OccupancyGrid, latched)。
  2. 订阅 /clicked_point(RViz "Publish Point"): 起点/终点拾取——
     第一次点=起点(START), 第二次点=终点(END), 之后循环; 打印坐标并发布:
       /start_point, /end_point (PointStamped, latched) + /route_markers(RViz 可视化)。
  3. 订阅 /goal_pose(RViz "2D Goal Pose") 与 send_goal 脚本: 设定当前导航目标。
  4. 订阅 /Odometry(定位节点输出, map->base_link): 获取机器人当前位姿。
  5. 订阅 /loc_health(定位健康): 仅在定位 READY 时才接受/激活目标。
  6. 发布 /nav_goal(PoseStamped, latched): 当前激活目标, 供上层导航算法订阅。
  7. 发布 /nav_status(String): NO_GOAL / LOC_NOT_READY / ACTIVE|dist=.. / REACHED。
  8. 发布 /nav_goal_marker(Marker): RViz 中可视化目标点。

与定位节点的关系: 两个进程, 仅通过话题(pub/sub)解耦通信。
  定位节点 -> 本节点 :  /Odometry(当前位姿) + /loc_health(就绪)
  本节点   -> 算法层 :  /nav_goal(目标) + /map(地图); 算法另订阅 /Odometry 得当前位姿
"""
import math
import os

import numpy as np
import yaml

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy, QoSHistoryPolicy

from geometry_msgs.msg import Point, PointStamped, PoseStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from std_msgs.msg import Empty, String
from visualization_msgs.msg import Marker, MarkerArray


def yaw_from_quaternion(x, y, z, w):
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def quaternion_from_yaw(yaw):
    return (0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5))


def _read_pgm(path):
    """读 P5 二进制 PGM, 返回 (data[h,w] uint8, w, h)。"""
    with open(path, 'rb') as f:
        magic = f.readline().strip()
        if magic != b'P5':
            raise ValueError(f'仅支持 P5 二进制 PGM: {path}')
        vals = []
        while len(vals) < 3:
            line = f.readline()
            if line.startswith(b'#'):
                continue
            vals += line.split()
        w, h, _maxv = int(vals[0]), int(vals[1]), int(vals[2])
        data = np.frombuffer(f.read(w * h), dtype=np.uint8).reshape(h, w)
    return data, w, h


def load_occupancy_grid(map_yaml, frame_id='map'):
    """按 Nav2 map_server 规则把 pgm/yaml 转成 OccupancyGrid。"""
    with open(map_yaml) as f:
        meta = yaml.safe_load(f)
    res = float(meta['resolution'])
    origin = meta.get('origin', [0.0, 0.0, 0.0])
    negate = int(meta.get('negate', 0))
    occ_th = float(meta.get('occupied_thresh', 0.65))
    free_th = float(meta.get('free_thresh', 0.25))
    pgm_path = os.path.join(os.path.dirname(os.path.abspath(map_yaml)), meta['image'])
    img, w, h = _read_pgm(pgm_path)

    # 像素 -> 占据概率 (map_server 约定)
    p = img.astype(np.float64) / 255.0
    occ = p if negate else (1.0 - p)
    grid = np.full((h, w), -1, dtype=np.int8)        # 未知
    grid[occ >= occ_th] = 100                          # 占据
    grid[occ <= free_th] = 0                           # 空闲

    # OccupancyGrid 数据为行主序, 起点(0,0)在地图左下角; PGM 第 0 行在顶部, 需上下翻转
    grid = np.flipud(grid)

    msg = OccupancyGrid()
    msg.header.frame_id = frame_id
    msg.info.resolution = res
    msg.info.width = w
    msg.info.height = h
    msg.info.origin.position.x = float(origin[0])
    msg.info.origin.position.y = float(origin[1])
    msg.info.origin.position.z = 0.0
    oyaw = float(origin[2]) if len(origin) > 2 else 0.0
    qx, qy, qz, qw = quaternion_from_yaw(oyaw)
    msg.info.origin.orientation.x = qx
    msg.info.origin.orientation.y = qy
    msg.info.origin.orientation.z = qz
    msg.info.origin.orientation.w = qw
    msg.data = grid.reshape(-1).tolist()
    return msg, (w, h, res)


class NavGoalManager(Node):
    def __init__(self):
        super().__init__('nav_goal_manager')

        self.declare_parameter('map_yaml',
                               '/home/unitree/ws_localization/src/go2_loc_bringup/maps/scans.yaml')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('odom_topic', '/Odometry')
        self.declare_parameter('goal_tolerance', 0.30)      # m, 到达判定半径
        self.declare_parameter('require_loc_ready', True)   # 是否要求定位 READY 才接受目标
        self.declare_parameter('status_hz', 5.0)
        # /clicked_point 拾取模式: 'startend'=点两点设起/终点(默认); 'print'=仅打印坐标
        self.declare_parameter('click_mode', 'startend')

        self.map_yaml = self.get_parameter('map_yaml').value
        self.map_frame = self.get_parameter('map_frame').value
        self.odom_topic = self.get_parameter('odom_topic').value
        self.goal_tol = float(self.get_parameter('goal_tolerance').value)
        self.require_loc_ready = bool(self.get_parameter('require_loc_ready').value)
        status_hz = float(self.get_parameter('status_hz').value)
        self.click_mode = str(self.get_parameter('click_mode').value)

        # latched QoS: 后启动的订阅者(RViz / 上层算法)也能立刻收到地图与当前目标
        latched = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
        )

        # ---- 发布 ----
        self.pub_map = self.create_publisher(OccupancyGrid, '/map', latched)
        self.pub_goal = self.create_publisher(PoseStamped, '/nav_goal', latched)
        self.pub_status = self.create_publisher(String, '/nav_status', 10)
        self.pub_marker = self.create_publisher(Marker, '/nav_goal_marker', latched)
        # 起点/终点(供上层路径规划订阅) + RViz 可视化
        self.pub_start = self.create_publisher(PointStamped, '/start_point', latched)
        self.pub_end = self.create_publisher(PointStamped, '/end_point', latched)
        self.pub_route_markers = self.create_publisher(MarkerArray, '/route_markers', latched)

        # ---- 订阅 ----
        self.create_subscription(PointStamped, '/clicked_point', self._on_clicked, 10)
        self.create_subscription(PoseStamped, '/goal_pose', self._on_goal_pose, 10)
        self.create_subscription(Odometry, self.odom_topic, self._on_odom, 20)
        self.create_subscription(String, '/loc_health', self._on_loc_health, 10)
        # 重置起/终点: ros2 topic pub --once /route_reset std_msgs/msg/Empty {}
        self.create_subscription(Empty, '/route_reset', self._on_route_reset, 10)

        self.cur_pose = None        # (x, y, yaw)
        self.goal = None            # (x, y, yaw)
        self.loc_ready = False
        self.reached = False
        # 起点/终点拾取状态
        self.start_pt = None        # (x, y)
        self.end_pt = None          # (x, y)
        self.next_is_start = True   # 下一次 /clicked_point 设起点还是终点

        # 加载并发布地图
        try:
            self.map_msg, (w, h, res) = load_occupancy_grid(self.map_yaml, self.map_frame)
            self.map_msg.header.stamp = self.get_clock().now().to_msg()
            self.pub_map.publish(self.map_msg)
            self.get_logger().info(
                f'已加载并发布 /map: {w}x{h} @ {res:.3f}m/格, frame={self.map_frame}, '
                f'来源 {self.map_yaml}')
        except Exception as e:  # noqa: BLE001
            self.map_msg = None
            self.get_logger().error(f'加载地图失败: {e}')

        self.create_timer(1.0 / max(status_hz, 0.5), self._tick)
        # 地图低频重发, 保证 latched 之外的可靠送达
        self.create_timer(2.0, self._republish_map)

        if self.click_mode == 'startend':
            click_help = (
                '  - RViz "Publish Point" 点地图: 第1次=起点 START(绿), 第2次=终点 END(红), 循环\n'
                '    -> 发布 /start_point /end_point(latched) + /route_markers(RViz 显示)\n'
                '  - 命令行设两点: ros2 run go2_navigation set_route SX SY EX EY\n'
                '  - 重置: ros2 topic pub --once /route_reset std_msgs/msg/Empty {}\n')
        else:
            click_help = '  - RViz "Publish Point" 点地图 -> 终端打印坐标\n'
        self.get_logger().info(
            '导航目标管理已就绪。\n'
            + click_help +
            '  - RViz "2D Goal Pose" 或 `ros2 run go2_navigation send_goal X Y [YAW度]` -> 设定目标\n'
            '  - 目标发布到 /nav_goal(latched), 供上层算法订阅\n'
            f'  - 到达判定半径 goal_tolerance={self.goal_tol:.2f}m')

    # ---------- 回调 ----------
    def _on_clicked(self, msg: PointStamped):
        x, y = msg.point.x, msg.point.y
        if self.click_mode != 'startend':
            self.get_logger().info(
                f'[点选坐标] map 系: x={x:+.3f}  y={y:+.3f}  '
                f'(设为目标: ros2 run go2_navigation send_goal {x:.3f} {y:.3f})')
            return
        # startend 模式: 交替设起点/终点
        if self.next_is_start:
            self.set_start(x, y, src='clicked_point')
        else:
            self.set_end(x, y, src='clicked_point')

    def _on_route_reset(self, _msg: Empty):
        self.start_pt = None
        self.end_pt = None
        self.next_is_start = True
        self._publish_route()
        self.get_logger().info('已重置起点/终点。下一次点击设起点 START。')

    # ---------- 起点/终点 ----------
    def set_start(self, x, y, src=''):
        self.start_pt = (float(x), float(y))
        self.next_is_start = False
        self._publish_route()
        self.get_logger().info(
            f'[起点 START] map: x={x:+.3f} y={y:+.3f} [{src}] -> /start_point'
            '  (再点一次设终点 END)')

    def set_end(self, x, y, src=''):
        self.end_pt = (float(x), float(y))
        self.next_is_start = True
        self._publish_route()
        msg = f'[终点 END] map: x={x:+.3f} y={y:+.3f} [{src}] -> /end_point'
        if self.start_pt is not None:
            d = math.hypot(self.end_pt[0] - self.start_pt[0],
                           self.end_pt[1] - self.start_pt[1])
            msg += f'  | 起点->终点直线距离 {d:.2f}m  (再点一次重设起点)'
        self.get_logger().info(msg)

    def _publish_route(self):
        now = self.get_clock().now().to_msg()
        if self.start_pt is not None:
            ps = PointStamped()
            ps.header.frame_id = self.map_frame
            ps.header.stamp = now
            ps.point.x, ps.point.y, ps.point.z = self.start_pt[0], self.start_pt[1], 0.0
            self.pub_start.publish(ps)
        if self.end_pt is not None:
            pe = PointStamped()
            pe.header.frame_id = self.map_frame
            pe.header.stamp = now
            pe.point.x, pe.point.y, pe.point.z = self.end_pt[0], self.end_pt[1], 0.0
            self.pub_end.publish(pe)
        self.pub_route_markers.publish(self._build_route_markers(now))

    def _build_route_markers(self, stamp):
        arr = MarkerArray()

        def sphere(mid, xy, rgb):
            m = Marker()
            m.header.frame_id = self.map_frame
            m.header.stamp = stamp
            m.ns = 'route'
            m.id = mid
            m.type = Marker.SPHERE
            m.action = Marker.ADD if xy is not None else Marker.DELETE
            if xy is not None:
                m.pose.position.x, m.pose.position.y, m.pose.position.z = xy[0], xy[1], 0.1
                m.pose.orientation.w = 1.0
                m.scale.x = m.scale.y = m.scale.z = 0.35
                m.color.r, m.color.g, m.color.b, m.color.a = rgb[0], rgb[1], rgb[2], 1.0
            return m

        def text(mid, xy, label, rgb):
            m = Marker()
            m.header.frame_id = self.map_frame
            m.header.stamp = stamp
            m.ns = 'route'
            m.id = mid
            m.type = Marker.TEXT_VIEW_FACING
            m.action = Marker.ADD if xy is not None else Marker.DELETE
            if xy is not None:
                m.pose.position.x, m.pose.position.y, m.pose.position.z = xy[0], xy[1], 0.5
                m.pose.orientation.w = 1.0
                m.scale.z = 0.4
                m.color.r, m.color.g, m.color.b, m.color.a = rgb[0], rgb[1], rgb[2], 1.0
                m.text = label
            return m

        arr.markers.append(sphere(0, self.start_pt, (0.0, 1.0, 0.0)))
        arr.markers.append(text(1, self.start_pt, 'START', (0.0, 1.0, 0.0)))
        arr.markers.append(sphere(2, self.end_pt, (1.0, 0.0, 0.0)))
        arr.markers.append(text(3, self.end_pt, 'END', (1.0, 0.3, 0.3)))

        line = Marker()
        line.header.frame_id = self.map_frame
        line.header.stamp = stamp
        line.ns = 'route'
        line.id = 4
        line.type = Marker.LINE_STRIP
        if self.start_pt is not None and self.end_pt is not None:
            line.action = Marker.ADD
            line.scale.x = 0.08
            line.color.r, line.color.g, line.color.b, line.color.a = 0.1, 0.8, 1.0, 0.9
            p0 = Point(); p0.x, p0.y, p0.z = self.start_pt[0], self.start_pt[1], 0.1
            p1 = Point(); p1.x, p1.y, p1.z = self.end_pt[0], self.end_pt[1], 0.1
            line.points = [p0, p1]
        else:
            line.action = Marker.DELETE
        arr.markers.append(line)
        return arr

    def _on_goal_pose(self, msg: PoseStamped):
        q = msg.pose.orientation
        yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)
        self._set_goal(msg.pose.position.x, msg.pose.position.y, yaw, src='/goal_pose')

    def _on_odom(self, msg: Odometry):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        self.cur_pose = (p.x, p.y, yaw_from_quaternion(q.x, q.y, q.z, q.w))

    def _on_loc_health(self, msg: String):
        ready = msg.data.startswith('READY')
        if ready != self.loc_ready:
            self.get_logger().info(f'定位状态: {"READY" if ready else "NOT_READY"} ({msg.data})')
        self.loc_ready = ready

    # ---------- 目标管理 ----------
    def _set_goal(self, x, y, yaw, src=''):
        if self.require_loc_ready and not self.loc_ready:
            self.get_logger().warn(
                f'拒绝目标 ({x:.2f},{y:.2f}) [{src}]: 定位未 READY。'
                '请先确保 /loc_health=READY (或设 require_loc_ready:=false)。')
            return
        self.goal = (x, y, yaw)
        self.reached = False
        self._publish_goal()
        self.get_logger().info(
            f'已设定导航目标 [{src}]: x={x:+.3f} y={y:+.3f} yaw={math.degrees(yaw):+.1f}° '
            '-> 已发布到 /nav_goal')

    def _publish_goal(self):
        if self.goal is None:
            return
        x, y, yaw = self.goal
        now = self.get_clock().now().to_msg()

        ps = PoseStamped()
        ps.header.frame_id = self.map_frame
        ps.header.stamp = now
        ps.pose.position.x = x
        ps.pose.position.y = y
        qx, qy, qz, qw = quaternion_from_yaw(yaw)
        ps.pose.orientation.x = qx
        ps.pose.orientation.y = qy
        ps.pose.orientation.z = qz
        ps.pose.orientation.w = qw
        self.pub_goal.publish(ps)

        m = Marker()
        m.header.frame_id = self.map_frame
        m.header.stamp = now
        m.ns = 'nav_goal'
        m.id = 0
        m.type = Marker.ARROW
        m.action = Marker.ADD
        m.pose = ps.pose
        m.scale.x = 0.6
        m.scale.y = 0.12
        m.scale.z = 0.12
        m.color.r = 0.0 if self.reached else 1.0
        m.color.g = 1.0 if self.reached else 0.4
        m.color.b = 0.0
        m.color.a = 1.0
        self.pub_marker.publish(m)

    def _republish_map(self):
        if self.map_msg is not None:
            self.map_msg.header.stamp = self.get_clock().now().to_msg()
            self.pub_map.publish(self.map_msg)
        # 低频重发起/终点, 保证晚启动的 RViz / 规划器稳定收到
        if self.start_pt is not None or self.end_pt is not None:
            self._publish_route()

    def _tick(self):
        status = String()
        if self.goal is None:
            status.data = 'NO_GOAL'
        elif self.require_loc_ready and not self.loc_ready:
            status.data = 'LOC_NOT_READY'
        elif self.cur_pose is None:
            status.data = 'NO_ODOM'
        else:
            dx = self.goal[0] - self.cur_pose[0]
            dy = self.goal[1] - self.cur_pose[1]
            dist = math.hypot(dx, dy)
            if dist <= self.goal_tol:
                if not self.reached:
                    self.reached = True
                    self.get_logger().info(
                        f'已到达目标附近 (dist={dist:.2f}m <= {self.goal_tol:.2f}m)')
                    self._publish_goal()  # 刷新 marker 为绿色
                status.data = f'REACHED|dist={dist:.2f}'
            else:
                status.data = f'ACTIVE|dist={dist:.2f},dx={dx:+.2f},dy={dy:+.2f}'
            # 持续重发目标(latched 已覆盖晚到订阅者, 这里保证算法层稳定收到)
            self._publish_goal()
        self.pub_status.publish(status)


def main():
    rclpy.init()
    node = NavGoalManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
