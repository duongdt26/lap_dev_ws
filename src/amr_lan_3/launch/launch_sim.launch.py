import os

from ament_index_python.packages import get_package_share_directory


from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource

from launch_ros.actions import Node

from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.actions import IncludeLaunchDescription


def generate_launch_description():


    # Include the robot_state_publisher launch file, provided by our own package. Force sim time to be enabled
    # !!! MAKE SURE YOU SET THE PACKAGE NAME CORRECTLY !!!

    package_name='amr_lan_3' #<--- CHANGE ME

    # Vid_1 ROS2_control: extra bits
    gazebo_params_file = os.path.join(
                    get_package_share_directory(package_name),'config','gazebo_params.yaml')


    rsp = IncludeLaunchDescription(
                PythonLaunchDescriptionSource([os.path.join(
                    get_package_share_directory(package_name),'launch','rsp.launch.py'
                )]), launch_arguments={'use_sim_time': 'true', 'use_ros2_control': 'true'}.items()
    )

    # Include the Gazebo launch file, provided by the gazebo_ros package
    gazebo = IncludeLaunchDescription(
                PythonLaunchDescriptionSource([os.path.join(
                    get_package_share_directory('gazebo_ros'), 'launch', 'gazebo.launch.py')]),
                    # Vid_1 ROS2_control: extra bits
                    launch_arguments={'extra_gazebo_args': '--ros-args --params-file ' + gazebo_params_file}.items()
             )

    # Run the spawner node from the gazebo_ros package. The entity name doesn't really matter if you only have a single robot.
    # spawn_entity = Node(package='gazebo_ros', executable='spawn_entity.py',
    #                     arguments=['-topic', 'robot_description',
    #                                '-entity', 'my_bot'],
    #                     output='screen')

    # Spawn robot (delay 3s)
    spawn_entity = TimerAction(
        period=3.0,
        actions=[
            Node(
                package='gazebo_ros',
                executable='spawn_entity.py',
                arguments=[
                    '-topic', 'robot_description',
                    '-entity', 'my_bot'
                ],
                output='screen'
            )
        ]
    )



    # Launch them all!
    # return LaunchDescription([
    #     rsp,
    #     gazebo,
    #     spawn_entity,
    # ])



    # Filtered laser scan
    laser_filter_node = Node(
        package='custom_laser_filter',
        executable='laser_filter',
        name='laser_filter',
        output='screen'
    )

    diff_drive_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["diff_cont"],
    )

    joint_broad_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_broad"],
    )

    # Khoi dong Node EKF cho mo phong
    ekf_sim_params_file = os.path.join(get_package_share_directory(package_name), 'config', 'ekf_sim.yaml')
    robot_localization_node = Node(
        package='robot_localization',   
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[ekf_sim_params_file, {'use_sim_time': True}]
    )

    # LƯU Ý: KHÔNG gọi Node imu_uart_node ở đây vì Gazebo plugin đã tự động phát ra topic /imu/data

    web_support = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            os.path.join(
                get_package_share_directory(package_name),
                'launch',
                'web_support.launch.py',
            )
        ]),
    )

    # Launch them all!
    return LaunchDescription([
        rsp,
        gazebo,
        spawn_entity,
        laser_filter_node, # Filtered laser scan
        diff_drive_spawner,
        joint_broad_spawner,
        robot_localization_node,
        web_support, # twist_mux + bridge + rosbridge
    ])