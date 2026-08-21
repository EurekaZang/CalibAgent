#!/usr/bin/env python3

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """
    Launch file to convert Livox MID360 PointCloud2 to LaserScan for DR-SPAAM person detection.

    Input:  /livox/lidar_pc2 (sensor_msgs/PointCloud2 mirrored by livox_ros_driver2)
    Output: /scan (sensor_msgs/LaserScan)
    """

    return LaunchDescription([
        Node(
            package='pointcloud_to_laserscan',
            executable='pointcloud_to_laserscan_node',
            name='pointcloud_to_laserscan',
            remappings=[
                ('cloud_in', '/utlidar/cloud_base'),  # Input: mirrored Livox PointCloud2
                ('scan', '/scan')               # Output: LaserScan for DR-SPAAM
            ],
            parameters=[{
                # Target frame for the scan
                'target_frame': 'base_link',

                # Transform tolerance (seconds)
                'transform_tolerance': 0.05,

                # Height range to extract 2D scan (meters)
                # For person detection: extract points at human body height
                'min_height': 0.0, # -1m
                'max_height': 1.0,   # 2m height (covers most people)

                # Scan angular range (radians)
                # MID360 has 360-degree FOV
                'angle_min': -3.1415926,  # -π (behind)
                'angle_max': 3.1415926,   # +π (behind)

                # Angular resolution (radians)
                # 0.00872 rad ≈ 0.5 degrees (720 points for 360°)
                'angle_increment': 0.00872,

                # Scan rate (seconds)
                # MID360 @ 10Hz = 0.1s per scan
                'scan_time': 0.05,

                # Range limits (meters)
                'range_min': 0.1,   # Minimum reliable range
                'range_max': 10.0,  # Maximum range for person detection

                # How to handle infinite values
                'use_inf': True,
                'inf_epsilon': 1.0,
            }],
            output='screen'
        )
    ])
