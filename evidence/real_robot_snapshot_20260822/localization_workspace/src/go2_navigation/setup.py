from setuptools import setup
import os
from glob import glob

package_name = 'go2_navigation'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'rviz'), glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='unitree',
    maintainer_email='unitree@example.com',
    description='Go2 导航目标管理节点(加载2D地图+目标点管理), 与定位栈话题解耦',
    license='BSD',
    entry_points={
        'console_scripts': [
            'nav_goal_manager = go2_navigation.nav_goal_manager:main',
            'send_goal = go2_navigation.send_goal:main',
            'set_route = go2_navigation.set_route:main',
        ],
    },
)
