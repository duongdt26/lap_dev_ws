import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import FrontendLaunchDescriptionSource
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('amr_lan_3')

    use_sim_time = LaunchConfiguration('use_sim_time')
    use_rosbridge = LaunchConfiguration('use_rosbridge')
    twist_mux_yaml = os.path.join(pkg, 'config', 'twist_mux.yaml')

    sim_time_param = {'use_sim_time': use_sim_time}

    twist_mux_node = Node(
        package='twist_mux',
        executable='twist_mux',
        name='twist_mux',
        parameters=[twist_mux_yaml, sim_time_param],
        remappings=[('cmd_vel_out', 'diff_cont/cmd_vel_unstamped')],
        output='screen',
    )

    map_bridge_node = Node(
        package='amr_web_bridge',
        executable='map_bridge_node',
        name='map_bridge_node',
        output='screen',
        parameters=[sim_time_param],
    )

    nav_pose_bridge_node = Node(
        package='amr_web_bridge',
        executable='nav_pose_bridge_node',
        name='nav_pose_bridge_node',
        output='screen',
        parameters=[
            sim_time_param,
            {
                # Nếu gần home thì tiến thẳng ra trước rồi mới NavigateToPose
                'home_x': 0.0,
                'home_y': 0.0,
                'near_home_threshold_m': 0.30,
                'undock_distance_m': 0.50,
                'undock_speed_mps': 0.08,
                'undock_time_allowance_sec': 20.0,
            },
        ],
    )

    mission_client_node = Node(
        package='amr_web_bridge',
        executable='mission_client_node',
        name='mission_client_node',
        output='screen',
        parameters=[sim_time_param],
    )

    stm32_pkg = get_package_share_directory('amr_stm32_bridge')
    stm32_config = os.path.join(stm32_pkg, 'config', 'stm32_bridge.yaml')
    hardware_ports = os.path.join(get_package_share_directory('amr_lan_3'), 'config', 'hardware_ports.yaml')
    stm32_bridge_node = Node(
        package='amr_stm32_bridge',
        executable='stm32_conveyor_bridge_node',
        name='stm32_conveyor_bridge_node',
        output='screen',
        parameters=[hardware_ports, stm32_config], # Load config from config/hardware_ports.yaml and config/stm32_bridge.yaml
    )

    line_pkg = get_package_share_directory('amr_magnetic_line_follower')
    line_config = os.path.join(line_pkg, 'config', 'magnetic_line_follower.yaml')
    magnetic_line_node = Node(
        package='amr_magnetic_line_follower',
        executable='magnetic_line_follower_node',
        name='magnetic_line_follower_node',
        output='screen',
        parameters=[hardware_ports, line_config, sim_time_param],
    )

    # PZEM-017: đọc pin 24V mỗi 1 s → /battery_state (sim + real đều cần)
    pzem_battery_node = Node(
        package='amr_imu_driver',
        executable='pzem_battery_node',
        name='pzem_battery_node',
        output='screen',
        parameters=[hardware_ports, {'poll_period': 1.0}],
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
            'port': '9091',
            'address': '0.0.0.0',
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation (/clock) clock — set true when running Gazebo sim',
        ),
        DeclareLaunchArgument(
            'use_rosbridge',
            default_value='true',
            description='Bật rosbridge cho web dashboard',
        ),
        twist_mux_node,
        map_bridge_node,
        nav_pose_bridge_node,
        mission_client_node,
        stm32_bridge_node,
        magnetic_line_node,
        pzem_battery_node,
        rosbridge,
    ])
