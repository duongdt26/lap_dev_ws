import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.launch_description_sources import FrontendLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('amr_lan_3')

    use_rosbridge = LaunchConfiguration('use_rosbridge')
    twist_mux_yaml = os.path.join(pkg, 'config', 'twist_mux.yaml')

    twist_mux_node = Node(
        package='twist_mux',
        executable='twist_mux',
        name='twist_mux',
        parameters=[twist_mux_yaml],
        remappings=[('cmd_vel_out', 'diff_cont/cmd_vel_unstamped')],
        output='screen',
    )

    map_bridge_node = Node(
        package='amr_web_bridge',
        executable='map_bridge_node',
        name='map_bridge_node',
        output='screen',
    )

    nav_pose_bridge_node = Node(
        package='amr_web_bridge',
        executable='nav_pose_bridge_node',
        name='nav_pose_bridge_node',
        output='screen',
    )

    rosbridge = IncludeLaunchDescription(
        FrontendLaunchDescriptionSource([
            os.path.join(
                get_package_share_directory('rosbridge_server'),
                'launch',
                'rosbridge_websocket_launch.xml',
            )
        ]),
        launch_arguments={
            'port': '9090',
            'address': '0.0.0.0',
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_rosbridge',
            default_value='true',
            description='Bật rosbridge cho web dashboard',
        ),
        twist_mux_node,
        map_bridge_node,
        nav_pose_bridge_node,
        # rosbridge tùy chọn — tắt nếu chỉ test ROS không cần web
        # Dùng IfCondition nếu muốn bật/tắt sạch hơn
        rosbridge,
    ])