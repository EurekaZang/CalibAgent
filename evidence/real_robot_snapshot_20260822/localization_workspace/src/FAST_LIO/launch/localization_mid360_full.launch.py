import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.conditions import IfCondition
from launch_ros.actions import Node


def generate_launch_description():
    fast_lio_share = get_package_share_directory('fast_lio')
    livox_share = get_package_share_directory('livox_ros_driver2')

    config_path = os.path.join(fast_lio_share, 'config')
    rviz_cfg = os.path.join(fast_lio_share, 'rviz', 'fastlio_localization.rviz')
    livox_config = os.path.join(livox_share, 'config', 'MID360_config.json')
    default_map = '/home/unitree/ws_localization/src/FAST_LIO/PCD/scans.pcd'

    rviz_use = LaunchConfiguration('rviz')
    prior_map = LaunchConfiguration('prior_map')

    declare_rviz_cmd = DeclareLaunchArgument(
        'rviz', default_value='true',
        description='Use RViz to monitor localization results'
    )
    declare_map_cmd = DeclareLaunchArgument(
        'prior_map', default_value=default_map,
        description='Path to prior PCD map for localization'
    )

    livox_driver = Node(
        package='livox_ros_driver2',
        executable='livox_ros_driver2_node',
        name='livox_lidar_publisher',
        output='screen',
        parameters=[
            {'xfer_format': 1},
            {'multi_topic': 0},
            {'data_src': 0},
            {'publish_freq': 10.0},
            {'output_data_type': 0},
            {'frame_id': 'livox_frame'},
            {'user_config_path': livox_config},
            {'cmdline_input_bd_code': 'livox0000000001'},
        ]
    )

    fast_lio_node = Node(
        package='fast_lio',
        executable='fastlio_mapping',
        parameters=[
            PathJoinSubstitution([config_path, 'mid360_localization.yaml']),
            {'prior_map_path': prior_map},
            {'use_sim_time': False},
        ],
        output='screen'
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        arguments=['-d', rviz_cfg],
        condition=IfCondition(rviz_use)
    )

    ld = LaunchDescription()
    ld.add_action(declare_rviz_cmd)
    ld.add_action(declare_map_cmd)
    ld.add_action(livox_driver)
    ld.add_action(fast_lio_node)
    ld.add_action(rviz_node)
    return ld
