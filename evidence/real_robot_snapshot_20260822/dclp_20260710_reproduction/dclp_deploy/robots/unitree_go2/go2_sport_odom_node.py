#!/usr/bin/env python3
"""Publish /odom and odom->base_link TF from Unitree Go2 SportModeState."""

import math

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import TransformBroadcaster

try:
    from unitree_go.msg import SportModeState
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Cannot import unitree_go.msg.SportModeState. Source /home/unitree/unitree_ros2/setup.sh first."
    ) from exc


def wrap_pi(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def yaw_to_quat(yaw: float):
    half = yaw * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


class Go2SportOdomNode(Node):
    def __init__(self):
        super().__init__("go2_sport_odom_node")

        self.declare_parameter("sport_topic", "/sportmodestate")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("zero_on_start", True)
        self.declare_parameter("rotate_into_initial_frame", True)
        self.declare_parameter("publish_z", False)
        self.declare_parameter("publish_tf", True)
        self.declare_parameter("pose_covariance", 0.05)
        self.declare_parameter("twist_covariance", 0.10)

        self.sport_topic = self.get_parameter("sport_topic").value
        self.odom_topic = self.get_parameter("odom_topic").value
        self.odom_frame = self.get_parameter("odom_frame").value
        self.base_frame = self.get_parameter("base_frame").value
        self.zero_on_start = bool(self.get_parameter("zero_on_start").value)
        self.rotate_into_initial_frame = bool(self.get_parameter("rotate_into_initial_frame").value)
        self.publish_z = bool(self.get_parameter("publish_z").value)
        self.publish_tf = bool(self.get_parameter("publish_tf").value)
        self.pose_covariance = float(self.get_parameter("pose_covariance").value)
        self.twist_covariance = float(self.get_parameter("twist_covariance").value)

        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.create_subscription(SportModeState, self.sport_topic, self._sport_cb, qos)
        self.odom_pub = self.create_publisher(Odometry, self.odom_topic, 10)
        self.tf_broadcaster = TransformBroadcaster(self) if self.publish_tf else None

        self.initial_position = None
        self.initial_yaw = None
        self.get_logger().info(
            f"Go2 odom node: {self.sport_topic} -> {self.odom_topic}, "
            f"TF {self.odom_frame}->{self.base_frame}"
        )

    def _relative_pose(self, msg):
        raw_x = float(msg.position[0])
        raw_y = float(msg.position[1])
        raw_z = float(msg.position[2])
        raw_yaw = float(msg.imu_state.rpy[2])

        if self.initial_position is None:
            self.initial_position = (raw_x, raw_y, raw_z)
            self.initial_yaw = raw_yaw
            self.get_logger().info("Go2 odom origin initialized")

        if self.zero_on_start:
            dx = raw_x - self.initial_position[0]
            dy = raw_y - self.initial_position[1]
            z = raw_z - self.initial_position[2]
            yaw = wrap_pi(raw_yaw - self.initial_yaw)
        else:
            dx = raw_x
            dy = raw_y
            z = raw_z
            yaw = raw_yaw

        if self.rotate_into_initial_frame and self.zero_on_start:
            c = math.cos(-self.initial_yaw)
            s = math.sin(-self.initial_yaw)
            x = c * dx - s * dy
            y = s * dx + c * dy
        else:
            x = dx
            y = dy

        if not self.publish_z:
            z = 0.0

        return x, y, z, yaw

    def _sport_cb(self, msg):
        stamp = self.get_clock().now().to_msg()
        x, y, z, yaw = self._relative_pose(msg)
        qx, qy, qz, qw = yaw_to_quat(yaw)

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.x = x
        odom.pose.pose.position.y = y
        odom.pose.pose.position.z = z
        odom.pose.pose.orientation.x = qx
        odom.pose.pose.orientation.y = qy
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.twist.twist.linear.x = float(msg.velocity[0])
        odom.twist.twist.linear.y = float(msg.velocity[1])
        odom.twist.twist.angular.z = float(msg.yaw_speed)
        odom.pose.covariance[0] = self.pose_covariance
        odom.pose.covariance[7] = self.pose_covariance
        odom.pose.covariance[35] = self.pose_covariance
        odom.twist.covariance[0] = self.twist_covariance
        odom.twist.covariance[7] = self.twist_covariance
        odom.twist.covariance[35] = self.twist_covariance
        self.odom_pub.publish(odom)

        if self.tf_broadcaster is not None:
            tf = TransformStamped()
            tf.header.stamp = stamp
            tf.header.frame_id = self.odom_frame
            tf.child_frame_id = self.base_frame
            tf.transform.translation.x = x
            tf.transform.translation.y = y
            tf.transform.translation.z = z
            tf.transform.rotation.x = qx
            tf.transform.rotation.y = qy
            tf.transform.rotation.z = qz
            tf.transform.rotation.w = qw
            self.tf_broadcaster.sendTransform(tf)


def main():
    rclpy.init()
    node = Go2SportOdomNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
