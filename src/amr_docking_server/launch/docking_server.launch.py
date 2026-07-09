import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('amr_docking_server')
    station_db = LaunchConfiguration('station_database')
    use_sim_time = LaunchConfiguration('use_sim_time')
    dock_costmap_inflation_radius = LaunchConfiguration('dock_costmap_inflation_radius')
    obstacle_stop_distance = LaunchConfiguration('obstacle_stop_distance')
    lateral_abort = LaunchConfiguration('lateral_abort')

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('dock_costmap_inflation_radius', default_value='0.33'),
        DeclareLaunchArgument('obstacle_stop_distance', default_value='0.33'),
        DeclareLaunchArgument('lateral_abort', default_value='0.06'),
        DeclareLaunchArgument(
            'station_database',
            default_value=os.path.join(pkg, 'config', 'station_database.yaml'),
        ),
        Node(
            package='amr_docking_server',
            executable='docking_server',
            name='docking_server',
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'station_database': station_db,
                'cmd_vel_topic': '/cmd_vel_dock',
                'odom_topic': '/odometry/filtered',
                'scan_topic': '/scan_filtered',
                'base_frame': 'base_footprint',
                'map_frame': 'map',
                'dock_costmap_inflation_radius': dock_costmap_inflation_radius,
                'obstacle_stop_distance_m': obstacle_stop_distance,
                'lateral_abort_m': lateral_abort,
                'enable_dynamic_costmap_tuning': True,
                'restore_costmap_after_dock': True,
            }],
        ),
    ])
