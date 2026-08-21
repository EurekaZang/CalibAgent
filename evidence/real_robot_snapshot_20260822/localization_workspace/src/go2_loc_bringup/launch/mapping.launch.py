"""MID360 + FAST-LIO2 mapping; no robot locomotion process is started."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    fast_lio_share = get_package_share_directory("fast_lio")
    livox_share = get_package_share_directory("livox_ros_driver2")

    config_path = os.path.join(fast_lio_share, "config")
    rviz_cfg = os.path.join(fast_lio_share, "rviz", "fastlio.rviz")
    default_livox_config = os.path.join(livox_share, "config", "MID360_config.json")

    rviz_use = LaunchConfiguration("rviz")
    livox_config = LaunchConfiguration("livox_config")

    return LaunchDescription(
        [
            DeclareLaunchArgument("rviz", default_value="true"),
            DeclareLaunchArgument(
                "livox_config",
                default_value=default_livox_config,
                description="Runtime MID360 SDK configuration",
            ),
            Node(
                package="livox_ros_driver2",
                executable="livox_ros_driver2_node",
                name="livox_lidar_publisher",
                output="screen",
                parameters=[
                    {"xfer_format": 1},
                    {"multi_topic": 0},
                    {"data_src": 0},
                    {"publish_freq": 10.0},
                    {"output_data_type": 0},
                    {"frame_id": "livox_frame"},
                    {"user_config_path": livox_config},
                    {"cmdline_input_bd_code": "livox0000000001"},
                ],
            ),
            Node(
                package="fast_lio",
                executable="fastlio_mapping",
                parameters=[
                    os.path.join(config_path, "mid360.yaml"),
                    {"use_sim_time": False},
                ],
                output="screen",
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                arguments=["-d", rviz_cfg],
                condition=IfCondition(rviz_use),
            ),
        ]
    )
