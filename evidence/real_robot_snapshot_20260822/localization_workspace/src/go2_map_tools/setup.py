from setuptools import setup
import os
from glob import glob

package_name = 'go2_map_tools'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='unitree',
    maintainer_email='unitree@example.com',
    description='PCD to 2D occupancy grid for Go2 navigation',
    license='BSD',
    entry_points={
        'console_scripts': [
            'pcd_to_occupancy_grid = go2_map_tools.pcd_to_occupancy_grid:main',
            'paint_virtual_obstacles = go2_map_tools.paint_virtual_obstacles:main',
            'pick_map_line = go2_map_tools.pick_map_line:main',
            'manage_obstacles = go2_map_tools.manage_obstacles:main',
        ],
    },
)
