import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    dock_pkg = get_package_share_directory('amr_docking_server')
    supervisor_pkg = get_package_share_directory('amr_mission_supervisor')
    station_db = LaunchConfiguration('station_database')
    use_sim_time = LaunchConfiguration('use_sim_time')

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'station_database',
            default_value=os.path.join(dock_pkg, 'config', 'station_database.yaml'),
        ),
        Node(
            package='amr_mission_supervisor',
            executable='mission_supervisor',
            name='mission_supervisor',
            output='screen',
            parameters=[
                os.path.join(supervisor_pkg, 'config', 'mission_supervisor.yaml'),
                {'use_sim_time': use_sim_time, 'station_database': station_db},
            ],
        ),
    ])
