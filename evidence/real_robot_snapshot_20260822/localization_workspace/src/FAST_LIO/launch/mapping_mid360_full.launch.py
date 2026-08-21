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
    rviz_cfg = os.path.join(fast_lio_share, 'rviz', 'fastlio.rviz')
    livox_config = os.path.join(livox_share, 'config', 'MID360_config.json')

    rviz_use = LaunchConfiguration('rviz')
    declare_rviz_cmd = DeclareLaunchArgument(
        'rviz', default_value='true',
        description='Use RViz to monitor mapping results'
    )

    livox_driver = Node(
        package='livox_ros_driver2',
        executable='livox_ros_driver2_node',
        name='livox_lidar_publisher',
        output='screen',
        parameters=[
            {'xfer_format': 1},          # 1 = Livox CustomMsg (FAST-LIO 输入)
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
        parameters=[PathJoinSubstitution([config_path, 'mid360.yaml']),
                    {'use_sim_time': False}],
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
    ld.add_action(livox_driver)
    ld.add_action(fast_lio_node)
    ld.add_action(rviz_node)
    return ld
