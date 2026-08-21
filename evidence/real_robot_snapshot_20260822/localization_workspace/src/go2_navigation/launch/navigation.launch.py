"""导航线程: 加载 2D 地图 + nav_goal_manager(+可选 RViz)。

与定位栈(run_localization.sh)分离运行, 仅通过话题通信:
  订阅 /Odometry /loc_health (来自定位节点)
  发布 /map /nav_goal /nav_status /nav_goal_marker
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    nav_share = get_package_share_directory('go2_navigation')
    rviz_cfg = os.path.join(nav_share, 'rviz', 'navigation.rviz')

    map_yaml = LaunchConfiguration('map_yaml')
    rviz_use = LaunchConfiguration('rviz')
    goal_tol = LaunchConfiguration('goal_tolerance')
    require_ready = LaunchConfiguration('require_loc_ready')

    return LaunchDescription([
        DeclareLaunchArgument(
            'map_yaml',
            default_value='/home/unitree/ws_localization/src/go2_loc_bringup/maps/scans.yaml',
            description='2D 栅格地图 yaml 路径'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('goal_tolerance', default_value='0.30'),
        DeclareLaunchArgument('require_loc_ready', default_value='true'),
        Node(
            package='go2_navigation',
            executable='nav_goal_manager',
            name='nav_goal_manager',
            output='screen',
            parameters=[{
                'map_yaml': map_yaml,
                'map_frame': 'map',
                'odom_topic': '/Odometry',
                'goal_tolerance': goal_tol,
                'require_loc_ready': require_ready,
            }],
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2_navigation',
            arguments=['-d', rviz_cfg, '--ros-args', '-r', '__node:=rviz2_navigation'],
            condition=IfCondition(rviz_use),
        ),
    ])
