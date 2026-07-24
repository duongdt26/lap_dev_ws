"""Launch STM32 conveyor UART bridge."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('amr_stm32_bridge')
    config = os.path.join(pkg, 'config', 'stm32_bridge.yaml')

    return LaunchDescription([
        Node(
            package='amr_stm32_bridge',
            executable='stm32_conveyor_bridge_node',
            name='stm32_conveyor_bridge_node',
            output='screen',
            parameters=[config],
        ),
    ])
