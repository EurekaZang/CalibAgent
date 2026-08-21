import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('global_reloc')
    default_cfg = os.path.join(pkg, 'config', 'global_reloc.yaml')

    db_dir = LaunchConfiguration('db_dir')
    map_pcd = LaunchConfiguration('map_pcd')

    return LaunchDescription([
        DeclareLaunchArgument('db_dir', default_value=''),
        DeclareLaunchArgument('map_pcd', default_value=''),
        Node(
            package='global_reloc',
            executable='global_reloc_node',
            name='global_reloc',
            output='screen',
            parameters=[
                default_cfg,
                {
                    'db_dir': db_dir,
                    'map_pcd': map_pcd,
                },
            ],
        ),
    ])
