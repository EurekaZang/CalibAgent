"""栈 A: Livox + global_reloc + FAST-LIO + nav_tf_manager (4 节点, 无 loc_health_monitor)."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    fast_lio_share = get_package_share_directory('fast_lio')
    livox_share = get_package_share_directory('livox_ros_driver2')
    global_reloc_share = get_package_share_directory('global_reloc')

    config_path = os.path.join(fast_lio_share, 'config')
    default_livox_config = os.path.join(livox_share, 'config', 'MID360_config.json')
    reloc_cfg = os.path.join(global_reloc_share, 'config', 'global_reloc.yaml')

    prior_map = LaunchConfiguration('prior_map')
    db_dir = LaunchConfiguration('db_dir')
    livox_config = LaunchConfiguration('livox_config')

    return LaunchDescription([
        DeclareLaunchArgument(
            'prior_map',
            default_value='/home/unitree/ws_localization/src/FAST_LIO/PCD/scans.pcd'),
        DeclareLaunchArgument(
            'db_dir',
            default_value='/home/unitree/ws_localization/src/FAST_LIO/PCD/reloc_db'),
        DeclareLaunchArgument(
            'livox_config',
            default_value=default_livox_config,
            description='MID360 JSON config with the current host IP'),
        Node(
            package='livox_ros_driver2',
            executable='livox_ros_driver2_node',
            name='livox_lidar_publisher',
            output='screen',
            parameters=[
                {'xfer_format': 1}, {'multi_topic': 0}, {'data_src': 0},
                {'publish_freq': 20.0}, {'output_data_type': 0},
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
            parameters=[reloc_cfg, {'db_dir': db_dir, 'map_pcd': prior_map}],
        ),
        Node(
            package='fast_lio',
            executable='fastlio_mapping',
            parameters=[
                os.path.join(config_path, 'mid360_localization.yaml'),
                {'prior_map_path': prior_map, 'use_sim_time': False,
                 'localization.publish_tf': False},
            ],
            output='screen',
        ),
        Node(
            package='go2_nav_frames',
            executable='nav_tf_manager',
            name='nav_tf_manager',
            output='screen',
            # Keep TF and FAST-LIO synchronized on every accepted initialpose.
            # Branch continuity is enforced by global_reloc against the last
            # trustworthy map pose, not independently in this TF consumer.
            parameters=[{'max_initialpose_jump': 0.0}],
        ),
    ])
