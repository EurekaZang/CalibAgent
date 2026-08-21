#!/usr/bin/env python3
"""Project rolling MID360 PointCloud2 frames into a safe base_link LaserScan.

MID360 publishes non-repetitive 20 ms scan fragments. Projecting each fragment
independently through a horizontal height band can produce a fresh but entirely
empty LaserScan. This node keeps a short rolling window, motion-compensates old
points with foot odometry, and refuses to publish low-quality scans.
"""

import math
import time
from collections import deque

import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan, PointCloud2


def quat_to_rot(qx, qy, qz, qw):
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm <= 0.0:
        return np.eye(3, dtype=np.float32)
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    return np.array(
        [
            [1.0 - 2.0 * (qy * qy + qz * qz), 2.0 * (qx * qy - qz * qw), 2.0 * (qx * qz + qy * qw)],
            [2.0 * (qx * qy + qz * qw), 1.0 - 2.0 * (qx * qx + qz * qz), 2.0 * (qy * qz - qx * qw)],
            [2.0 * (qx * qz - qy * qw), 2.0 * (qy * qz + qx * qw), 1.0 - 2.0 * (qx * qx + qy * qy)],
        ],
        dtype=np.float32,
    )


def stamp_to_sec(stamp):
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def yaw_from_quaternion(q):
    siny_cosp = 2.0 * (float(q.w) * float(q.z) + float(q.x) * float(q.y))
    cosy_cosp = 1.0 - 2.0 * (float(q.y) * float(q.y) + float(q.z) * float(q.z))
    return math.atan2(siny_cosp, cosy_cosp)


def wrap_angle(value):
    return (float(value) + math.pi) % (2.0 * math.pi) - math.pi


class Go2LivoxPc2Scan(Node):
    def __init__(self):
        super().__init__("go2_livox_pc2scan")

        self.declare_parameter("cloud_topic", "/livox/lidar")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("target_frame", "base_link")
        self.declare_parameter("min_height", -0.8)
        self.declare_parameter("max_height", 1.2)
        self.declare_parameter("angle_min", -math.pi)
        self.declare_parameter("angle_max", math.pi)
        self.declare_parameter("angle_increment", 0.005817764)
        self.declare_parameter("scan_time", 0.02)
        self.declare_parameter("range_min", 0.20)
        self.declare_parameter("range_max", 20.0)
        self.declare_parameter("use_inf", True)
        self.declare_parameter("queue_size", 1)
        self.declare_parameter("accumulation_frames", 5)
        self.declare_parameter("accumulation_max_age", 0.12)
        self.declare_parameter("motion_compensation", True)
        self.declare_parameter("odom_max_stamp_delta", 0.08)
        self.declare_parameter("odom_history_sec", 2.0)
        self.declare_parameter("min_raw_finite_points", 1000)
        self.declare_parameter("min_valid_beams", 64)
        self.declare_parameter("drop_low_quality_scan", True)
        self.declare_parameter("tf_x", 0.1870)
        self.declare_parameter("tf_y", 0.0)
        self.declare_parameter("tf_z", 0.3603)
        self.declare_parameter("tf_qx", 0.0)
        self.declare_parameter("tf_qy", 0.113203)
        self.declare_parameter("tf_qz", 0.0)
        self.declare_parameter("tf_qw", 0.993572)

        self.cloud_topic = self.get_parameter("cloud_topic").value
        self.scan_topic = self.get_parameter("scan_topic").value
        self.odom_topic = self.get_parameter("odom_topic").value
        self.target_frame = self.get_parameter("target_frame").value
        self.min_height = float(self.get_parameter("min_height").value)
        self.max_height = float(self.get_parameter("max_height").value)
        self.angle_min = float(self.get_parameter("angle_min").value)
        self.angle_max = float(self.get_parameter("angle_max").value)
        self.angle_increment = float(self.get_parameter("angle_increment").value)
        self.scan_time = float(self.get_parameter("scan_time").value)
        self.range_min = float(self.get_parameter("range_min").value)
        self.range_max = float(self.get_parameter("range_max").value)
        self.use_inf = bool(self.get_parameter("use_inf").value)
        self.accumulation_frames = max(1, int(self.get_parameter("accumulation_frames").value))
        self.accumulation_max_age = max(0.0, float(self.get_parameter("accumulation_max_age").value))
        self.motion_compensation = bool(self.get_parameter("motion_compensation").value)
        self.odom_max_stamp_delta = max(0.0, float(self.get_parameter("odom_max_stamp_delta").value))
        self.odom_history_sec = max(0.2, float(self.get_parameter("odom_history_sec").value))
        self.min_raw_finite_points = max(1, int(self.get_parameter("min_raw_finite_points").value))
        self.min_valid_beams = max(1, int(self.get_parameter("min_valid_beams").value))
        self.drop_low_quality_scan = bool(self.get_parameter("drop_low_quality_scan").value)
        queue_size = max(1, int(self.get_parameter("queue_size").value))

        tx = float(self.get_parameter("tf_x").value)
        ty = float(self.get_parameter("tf_y").value)
        tz = float(self.get_parameter("tf_z").value)
        qx = float(self.get_parameter("tf_qx").value)
        qy = float(self.get_parameter("tf_qy").value)
        qz = float(self.get_parameter("tf_qz").value)
        qw = float(self.get_parameter("tf_qw").value)
        self.translation = np.array([tx, ty, tz], dtype=np.float32)
        self.rotation = quat_to_rot(qx, qy, qz, qw)
        self.ranges_size = int(math.ceil((self.angle_max - self.angle_min) / self.angle_increment))

        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=queue_size,
        )
        odom_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=50,
        )
        self.pub = self.create_publisher(LaserScan, self.scan_topic, sensor_qos)
        self.create_subscription(PointCloud2, self.cloud_topic, self._cloud_cb, sensor_qos)
        self.create_subscription(Odometry, self.odom_topic, self._odom_cb, odom_qos)

        self.frames = deque()
        self.odom_history = deque()
        self.cloud_count = 0
        self.publish_count = 0
        self.raw_quality_drops = 0
        self.scan_quality_drops = 0
        self.get_logger().info(
            "Go2 MID360 rolling pc2scan: %s -> %s frame=%s z=[%.2f, %.2f] "
            "beams=%d accumulate=%d/%.0fms motion_comp=%s raw_min=%d beam_min=%d"
            % (
                self.cloud_topic,
                self.scan_topic,
                self.target_frame,
                self.min_height,
                self.max_height,
                self.ranges_size,
                self.accumulation_frames,
                self.accumulation_max_age * 1000.0,
                "on" if self.motion_compensation else "off",
                self.min_raw_finite_points,
                self.min_valid_beams,
            )
        )

    def _odom_cb(self, msg):
        stamp = stamp_to_sec(msg.header.stamp)
        if stamp <= 0.0:
            return
        pose = msg.pose.pose
        sample = (
            stamp,
            float(pose.position.x),
            float(pose.position.y),
            yaw_from_quaternion(pose.orientation),
        )
        if self.odom_history and stamp < self.odom_history[-1][0] - 0.01:
            return
        self.odom_history.append(sample)
        cutoff = stamp - self.odom_history_sec
        while self.odom_history and self.odom_history[0][0] < cutoff:
            self.odom_history.popleft()

    def _pose_at(self, stamp):
        if not self.odom_history or stamp <= 0.0:
            return None
        before = None
        after = None
        for sample in reversed(self.odom_history):
            if sample[0] <= stamp:
                before = sample
                break
            after = sample
        if before is not None and after is not None:
            gap = after[0] - before[0]
            if 0.0 < gap <= 2.0 * self.odom_max_stamp_delta:
                ratio = max(0.0, min(1.0, (stamp - before[0]) / gap))
                yaw = before[3] + ratio * wrap_angle(after[3] - before[3])
                return (
                    before[1] + ratio * (after[1] - before[1]),
                    before[2] + ratio * (after[2] - before[2]),
                    wrap_angle(yaw),
                )
        candidates = [sample for sample in (before, after) if sample is not None]
        if not candidates:
            return None
        nearest = min(candidates, key=lambda item: abs(item[0] - stamp))
        if abs(nearest[0] - stamp) > self.odom_max_stamp_delta:
            return None
        return nearest[1], nearest[2], nearest[3]

    @staticmethod
    def _extract_xyz(msg):
        count = int(msg.width * msg.height)
        if count <= 0 or msg.point_step < 12:
            return None
        dtype = np.dtype(
            {
                "names": ["x", "y", "z"],
                "formats": ["<f4", "<f4", "<f4"],
                "offsets": [0, 4, 8],
                "itemsize": int(msg.point_step),
            }
        )
        try:
            points = np.frombuffer(msg.data, dtype=dtype, count=count)
        except ValueError:
            return None
        return points["x"], points["y"], points["z"]

    def _warn_quality(self, kind, text, count):
        if count == 1 or count % 50 == 0:
            self.get_logger().warn("%s quality drop #%d: %s" % (kind, count, text))

    def _prune_frames(self, current_stamp):
        while len(self.frames) > self.accumulation_frames:
            self.frames.popleft()
        if self.accumulation_max_age > 0.0:
            cutoff = current_stamp - self.accumulation_max_age
            while len(self.frames) > 1 and self.frames[0]["stamp"] < cutoff:
                self.frames.popleft()

    def _project_history(self, current_pose):
        ranges = np.full(
            self.ranges_size,
            np.inf if self.use_inf else self.range_max + 1.0,
            dtype=np.float32,
        )
        compensated_frames = 0
        used_points = 0
        for frame in self.frames:
            bx = frame["x"]
            by = frame["y"]
            if bx.size == 0:
                continue
            pose = frame["pose"]
            if self.motion_compensation and current_pose is not None and pose is not None:
                old_x, old_y, old_yaw = pose
                cur_x, cur_y, cur_yaw = current_pose
                cos_old = math.cos(old_yaw)
                sin_old = math.sin(old_yaw)
                world_x = old_x + cos_old * bx - sin_old * by
                world_y = old_y + sin_old * bx + cos_old * by
                dx = world_x - cur_x
                dy = world_y - cur_y
                cos_cur = math.cos(cur_yaw)
                sin_cur = math.sin(cur_yaw)
                px = cos_cur * dx + sin_cur * dy
                py = -sin_cur * dx + cos_cur * dy
                compensated_frames += 1
            else:
                px = bx
                py = by
            rr = np.hypot(px, py)
            angles = np.arctan2(py, px)
            valid = (
                np.isfinite(rr)
                & np.isfinite(angles)
                & (rr >= self.range_min)
                & (rr <= self.range_max)
                & (angles >= self.angle_min)
                & (angles <= self.angle_max)
            )
            if not np.any(valid):
                continue
            idx = ((angles[valid] - self.angle_min) / self.angle_increment).astype(np.int32)
            idx = np.clip(idx, 0, self.ranges_size - 1)
            np.minimum.at(ranges, idx, rr[valid].astype(np.float32))
            used_points += int(np.count_nonzero(valid))
        return ranges, used_points, compensated_frames

    def _cloud_cb(self, msg):
        t0 = time.perf_counter()
        self.cloud_count += 1
        xyz = self._extract_xyz(msg)
        if xyz is None:
            self.raw_quality_drops += 1
            self._warn_quality("raw", "empty or unparsable PointCloud2", self.raw_quality_drops)
            return
        xs, ys, zs = xyz
        finite = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(zs)
        finite_count = int(np.count_nonzero(finite))
        if finite_count < self.min_raw_finite_points:
            self.raw_quality_drops += 1
            self._warn_quality(
                "raw",
                "finite points %d < %d" % (finite_count, self.min_raw_finite_points),
                self.raw_quality_drops,
            )
            return

        t1 = time.perf_counter()
        bx = self.rotation[0, 0] * xs + self.rotation[0, 1] * ys + self.rotation[0, 2] * zs + self.translation[0]
        by = self.rotation[1, 0] * xs + self.rotation[1, 1] * ys + self.rotation[1, 2] * zs + self.translation[1]
        bz = self.rotation[2, 0] * xs + self.rotation[2, 1] * ys + self.rotation[2, 2] * zs + self.translation[2]
        rr = np.hypot(bx, by)
        angles = np.arctan2(by, bx)
        mask = (
            np.isfinite(bx)
            & np.isfinite(by)
            & np.isfinite(bz)
            & (bz >= self.min_height)
            & (bz <= self.max_height)
            & (rr >= self.range_min)
            & (rr <= self.range_max)
            & (angles >= self.angle_min)
            & (angles <= self.angle_max)
        )
        stamp = stamp_to_sec(msg.header.stamp)
        pose = self._pose_at(stamp) if self.motion_compensation else None
        self.frames.append(
            {
                "stamp": stamp,
                "x": np.asarray(bx[mask], dtype=np.float32).copy(),
                "y": np.asarray(by[mask], dtype=np.float32).copy(),
                "pose": pose,
            }
        )
        self._prune_frames(stamp)
        ranges, accumulated_points, compensated_frames = self._project_history(pose)
        valid_beams = int(np.count_nonzero(np.isfinite(ranges) & (ranges >= self.range_min) & (ranges <= self.range_max)))
        window_ms = max(0.0, (stamp - self.frames[0]["stamp"]) * 1000.0) if self.frames else 0.0

        if valid_beams < self.min_valid_beams and self.drop_low_quality_scan:
            self.scan_quality_drops += 1
            self._warn_quality(
                "scan",
                "valid beams %d < %d current_points=%d accumulated_points=%d frames=%d window=%.1fms"
                % (
                    valid_beams,
                    self.min_valid_beams,
                    int(np.count_nonzero(mask)),
                    accumulated_points,
                    len(self.frames),
                    window_ms,
                ),
                self.scan_quality_drops,
            )
            return

        t2 = time.perf_counter()
        scan = LaserScan()
        scan.header.stamp = msg.header.stamp
        scan.header.frame_id = self.target_frame
        scan.angle_min = self.angle_min
        scan.angle_max = self.angle_max
        scan.angle_increment = self.angle_increment
        scan.time_increment = 0.0
        scan.scan_time = self.scan_time
        scan.range_min = self.range_min
        scan.range_max = self.range_max
        scan.ranges = ranges.tolist()
        self.pub.publish(scan)
        self.publish_count += 1

        t3 = time.perf_counter()
        if self.cloud_count == 1 or self.cloud_count % 50 == 0:
            now_sec = self.get_clock().now().nanoseconds * 1e-9
            age_ms = (now_sec - stamp) * 1000.0 if stamp > 0.0 else 0.0
            self.get_logger().info(
                "scan #%d cloud#%d: frame=%s raw=%d finite=%d current=%d accumulated=%d "
                "valid_beams=%d frames=%d window=%.1fms odom_comp=%d/%d drops(raw=%d scan=%d) | "
                "extract=%.1fms project=%.1fms build_pub=%.1fms total=%.1fms cloud_stamp→scan_pub=%.1fms"
                % (
                    self.publish_count,
                    self.cloud_count,
                    msg.header.frame_id,
                    int(msg.width * msg.height),
                    finite_count,
                    int(np.count_nonzero(mask)),
                    accumulated_points,
                    valid_beams,
                    len(self.frames),
                    window_ms,
                    compensated_frames,
                    len(self.frames),
                    self.raw_quality_drops,
                    self.scan_quality_drops,
                    (t1 - t0) * 1000.0,
                    (t2 - t1) * 1000.0,
                    (t3 - t2) * 1000.0,
                    (t3 - t0) * 1000.0,
                    age_ms,
                )
            )


def main():
    rclpy.init()
    node = Go2LivoxPc2Scan()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
