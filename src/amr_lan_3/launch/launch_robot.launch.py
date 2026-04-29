import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
import xacro

def generate_launch_description():
    package_name = 'amr_lan_3'

    # 1. Gọi file rsp.launch.py (Lưu ý: use_sim_time = false)
    rsp = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([os.path.join(
            get_package_share_directory(package_name), 'launch', 'rsp.launch.py'
        )]), launch_arguments={'use_sim_time': 'false'}.items()
    )

    # 2. Xử lý file xacro để nạp vào controller_manager
    robot_description_path = os.path.join(get_package_share_directory(package_name), 'description', 'robot.urdf.xacro')
    robot_description_config = xacro.process_file(robot_description_path)
    robot_description = {'robot_description': robot_description_config.toxml()}

    # Đường dẫn tới file cấu hình yaml
    controller_params_file = os.path.join(get_package_share_directory(package_name), 'config', 'my_controllers.yaml')

    # 3. Chạy Node Controller Manager (Trái tim của hệ thống thực)
    controller_manager = Node(
        package='controller_manager',
        executable='ros2_control_node',
        parameters=[robot_description, controller_params_file],
        output='screen'
    )

    # 4. Spawner cho diff_cont (Khởi động bộ tính toán động học)
    diff_drive_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["diff_cont"],
    )

    # 5. Spawner cho joint_broad (Để publish tf cho bánh xe lên Rviz)
    joint_broad_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_broad"],
    )

    return LaunchDescription([
        rsp,
        controller_manager,
        # Dùng TimerAction để delay spawner 3 giây, đợi Hardware Interface connect Modbus xong
        TimerAction(period=3.0, actions=[diff_drive_spawner]),
        TimerAction(period=3.0, actions=[joint_broad_spawner])
    ])