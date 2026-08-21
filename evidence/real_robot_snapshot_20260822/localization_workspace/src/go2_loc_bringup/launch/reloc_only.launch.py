"""Livox + global_reloc + FAST-LIO + RViz，与 run_global_localization 视觉一致。"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description():
    fast_lio_share = get_package_share_directory('fast_lio')
    livox_share = get_package_share_directory('livox_ros_driver2')
    global_reloc_share = get_package_share_directory('global_reloc')

    config_path = os.path.join(fast_lio_share, 'config')
    rviz_cfg = os.path.join(fast_lio_share, 'rviz', 'fastlio_localization.rviz')
    livox_config = os.path.join(livox_share, 'config', 'MID360_config.json')
    reloc_cfg = os.path.join(global_reloc_share, 'config', 'global_reloc.yaml')

    rviz_use = LaunchConfiguration('rviz')
    prior_map = LaunchConfiguration('prior_map')
    db_dir = LaunchConfiguration('db_dir')

    return LaunchDescription([
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument(
            'prior_map',
            default_value='/home/unitree/ws_localization/src/FAST_LIO/PCD/scans.pcd'),
        DeclareLaunchArgument(
            'db_dir',
            default_value='/home/unitree/ws_localization/src/FAST_LIO/PCD/reloc_db'),
        Node(
            package='livox_ros_driver2',
            executable='livox_ros_driver2_node',
            name='livox_lidar_publisher',
            output='screen',
            parameters=[
                {'xfer_format': 1}, {'multi_topic': 0}, {'data_src': 0},
                {'publish_freq': 10.0}, {'output_data_type': 0},
                {'frame_id': 'livox_frame'},
                {'user_config_path': livox_config},
                {'cmdline_input_bd_code': 'livox0000000001'},
            ],
        ),
        Node(
            package='global_reloc',
            executable='global_reloc_node',
            name='global_reloc',
            output='screen',
            parameters=[
                reloc_cfg,
                {'db_dir': db_dir, 'map_pcd': prior_map},
            ],
        ),
        Node(
            package='fast_lio',
            executable='fastlio_mapping',
            parameters=[
                PathJoinSubstitution([config_path, 'mid360_localization.yaml']),
                {'prior_map_path': prior_map},
                {'use_sim_time': False},
            ],
            output='screen',
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            arguments=['-d', rviz_cfg],
            condition=IfCondition(rviz_use),
        ),
    ])
