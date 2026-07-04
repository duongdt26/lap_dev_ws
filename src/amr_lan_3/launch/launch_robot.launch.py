# import os
# from ament_index_python.packages import get_package_share_directory
# from launch import LaunchDescription
# from launch.actions import IncludeLaunchDescription, TimerAction
# from launch.launch_description_sources import PythonLaunchDescriptionSource
# from launch_ros.actions import Node
# import xacro

# def generate_launch_description():
#     package_name = 'amr_lan_3'

#     # 1. Gọi file rsp.launch.py (Lưu ý: use_sim_time = false)
#     rsp = IncludeLaunchDescription(
#         PythonLaunchDescriptionSource([os.path.join(
#             get_package_share_directory(package_name), 'launch', 'rsp.launch.py'
#         )]), launch_arguments={'use_sim_time': 'false'}.items()
#     )

#     # 2. Xử lý file xacro để nạp vào controller_manager
#     robot_description_path = os.path.join(get_package_share_directory(package_name), 'description', 'robot.urdf.xacro')
#     robot_description_config = xacro.process_file(robot_description_path)
#     robot_description = {'robot_description': robot_description_config.toxml()}

#     # Đường dẫn tới file cấu hình yaml
#     controller_params_file = os.path.join(get_package_share_directory(package_name), 'config', 'my_controllers.yaml')

#     # 3. Chạy Node Controller Manager (Trái tim của hệ thống thực)
#     controller_manager = Node(
#         package='controller_manager',
#         executable='ros2_control_node',
#         parameters=[robot_description, controller_params_file],
#         output='screen'
#     )

#     # 4. Spawner cho diff_cont (Khởi động bộ tính toán động học)
#     diff_drive_spawner = Node(
#         package="controller_manager",
#         executable="spawner",
#         arguments=["diff_cont"],
#     )

#     # 5. Spawner cho joint_broad (Để publish tf cho bánh xe lên Rviz)
#     joint_broad_spawner = Node(
#         package="controller_manager",
#         executable="spawner",
#         arguments=["joint_broad"],
#     )

#     return LaunchDescription([
#         rsp,
#         controller_manager,
#         # Dùng TimerAction để delay spawner 3 giây, đợi Hardware Interface connect Modbus xong
#         TimerAction(period=3.0, actions=[diff_drive_spawner]),
#         TimerAction(period=3.0, actions=[joint_broad_spawner])
#     ])

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
import xacro

from launch.substitutions import Command
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnProcessStart

def generate_launch_description():
    package_name = 'amr_lan_3'

    # 1. Gọi file rsp.launch.py (Lưu ý: use_sim_time = false)
    rsp = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([os.path.join(
            get_package_share_directory(package_name), 'launch', 'rsp.launch.py'
        )]), launch_arguments={'use_sim_time': 'false', 'use_ros2_control': 'true'}.items()
    )

    # 2. Xử lý file xacro để nạp vào controller_manager
    # robot_description_path = os.path.join(get_package_share_directory(package_name), 'description', 'robot.urdf.xacro')
    # robot_description_config = xacro.process_file(robot_description_path)
    # robot_description = {'robot_description': robot_description_config.toxml()}
    robot_description = Command(['ros2 param get --hide-type /robot_state_publisher robot_description'])

    # Đường dẫn tới file cấu hình yaml
    controller_params_file = os.path.join(get_package_share_directory(package_name), 'config', 'my_controllers.yaml')

    # 3. Chạy Node Controller Manager (Trái tim của hệ thống thực)
    controller_manager = Node(
        package='controller_manager',
        executable='ros2_control_node',
        # parameters=[robot_description, controller_params_file],
        parameters=[{'robot_description': robot_description}, 
                    controller_params_file],
        output='screen'
    )   

    delayed_controller_manager = TimerAction(period=3.0, actions=[controller_manager])

    # 4. Spawner cho diff_cont (Khởi động bộ tính toán động học)
    diff_drive_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["diff_cont"],
    )

    delayed_diff_drive_spawner = RegisterEventHandler(
        event_handler=OnProcessStart(
            target_action=controller_manager,
            on_start=[diff_drive_spawner],
        )
    )

    # 5. Spawner cho joint_broad (Để publish tf cho bánh xe lên Rviz)
    joint_broad_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_broad"],
    )

    delayed_joint_broad_spawner = RegisterEventHandler(
        event_handler=OnProcessStart(
            target_action=controller_manager,
            on_start=[joint_broad_spawner],
        )
    )

    ekf_params_file = os.path.join(get_package_share_directory(package_name), 'config', 'ekf.yaml')
    # Node chạy bộ lọc EKF
    robot_localization_node = Node(
       package='robot_localization',
       executable='ekf_node',
       name='ekf_filter_node',
       output='screen',
       parameters=[ekf_params_file]
    )

    delayed_ekf = RegisterEventHandler(
    event_handler=OnProcessStart(
        target_action=diff_drive_spawner,
        on_start=[
            TimerAction(
                period=2.0,   # đợi diff_cont publish vài chu kỳ odom
                actions=[robot_localization_node],
            )
        ],
    )
)
    hardware_ports = os.path.join(get_package_share_directory(package_name), 'config', 'hardware_ports.yaml')
    # Node đọc IMU UART 
    imu_node = Node(
        package='amr_imu_driver', # Tên package chứa file imu_uart_node.py
        executable='imu_uart_node', # Tên executable cậu khai báo trong setup.py
        parameters=[hardware_ports], # Load config from config/hardware_ports.yaml
        output='screen'
    )

    # Filtered laser scan
    laser_filter_node = Node(
        package='custom_laser_filter',
        executable='laser_filter',
        name='laser_filter',
        output='screen'
    )

    web_support = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            os.path.join(
                get_package_share_directory(package_name),
                'launch',
                'web_support.launch.py',
            )
        ]),
        launch_arguments={'use_sim_time': 'false'}.items(),
    )

    ps2_teleop = IncludeLaunchDescription(
    PythonLaunchDescriptionSource([
        os.path.join(
            get_package_share_directory('ps2_duo_teleop'),
            'launch',
            'ps2_teleop.launch.py',
        )
    ]),
    )

    return LaunchDescription([
        rsp,
        delayed_controller_manager,
        # Dùng TimerAction để delay spawner 3 giây, đợi Hardware Interface connect Modbus xong
        delayed_diff_drive_spawner,
        delayed_joint_broad_spawner,
        # robot_localization_node, # Chạy EKF kèm theo hệ thống
        delayed_ekf,
        imu_node,                 # Chạy IMU node
        laser_filter_node,
        web_support, # twist_mux + bridge + rosbridge
        # ps2_teleop,
    ])