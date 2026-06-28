import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('ps2_duo_teleop')
    config = os.path.join(pkg, 'config', 'ps2_teleop.yaml')

    return LaunchDescription([  
        Node(
            package='ps2_duo_teleop',
            executable='ps2_teleop_node',
            name='ps2_teleop_node',
            parameters=[config],
            output='screen',
        ),
    ])