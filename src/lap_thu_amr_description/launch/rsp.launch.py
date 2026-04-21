# import os

# from ament_index_python.packages import get_package_share_directory
# from launch import LaunchDescription
# from launch_ros.actions import Node

# def generate_launch_description():
#     package_name = 'lap_thu_amr_description'
#     urdf_file = os.path.join(get_package_share_directory(package_name), 'urdf', 'lap_thu_AMR_test_2.urdf')

#     with open(urdf_file, 'r') as infp:
#         robot_description = infp.read()

#     return LaunchDescription([
#         Node(
#             package='robot_state_publisher',
#             executable='robot_state_publisher',
#             output='screen',
#             parameters=[{'robot_description': robot_description}]
#         ),
#         Node(
#             package='rviz2',
#             executable='rviz2',
#             name = 'rviz2',
#             output='screen',
#         )
#     ])




# 1111 Run with directory config rviz input from keyboard
# ros2 launch lap_thu_amr_description rsp.launch.py rviz_config:=./src/lap_thu_amr_description/rviz/urdf_1.rviz
# import os

# from ament_index_python.packages import get_package_share_directory
# from launch import LaunchDescription
# from launch_ros.actions import Node

# # Add argument for Rviz config
# from launch.actions import DeclareLaunchArgument
# from launch.substitutions import LaunchConfiguration


# def generate_launch_description():
#     pkg_name = 'lap_thu_amr_description'
#     pkg_path = get_package_share_directory(pkg_name)
#     urdf_file = os.path.join(pkg_path, 'urdf', 'lap_thu_AMR_test_2.urdf')

#     with open(urdf_file, 'r') as infp:
#         robot_description = infp.read()

#     # Add argument for Rviz config
#     rviz_config_arg = DeclareLaunchArgument(
#         name='rviz_config',
#         default_value='',
#         description='Path to Rviz config file'
#     )
#     rviz_config = LaunchConfiguration('rviz_config')


#     node_robot_state_publisher = Node(
#         package='robot_state_publisher',
#         executable='robot_state_publisher',
#         output='screen',
#         parameters=[{'robot_description': robot_description}],
#     )

#     node_rviz = Node(
#         package='rviz2',
#         executable='rviz2',
#         name = 'rviz2',
#         output='screen',
#         # Add argument for Rviz config
#         arguments=['-d', rviz_config]
#     )

#     return LaunchDescription([
#         # Add argument for Rviz config
#         rviz_config_arg,

#         node_robot_state_publisher,
#         node_rviz
#     ])



# 2222 Run without directory config rviz input from keyboard
#      but with hard directory include in code
# launch lap_thu_amr_description rsp.launch.py
# import os

# from ament_index_python.packages import get_package_share_directory
# from launch import LaunchDescription
# from launch_ros.actions import Node

# # Add argument for Rviz config
# # from launch.actions import DeclareLaunchArgument
# # from launch.substitutions import LaunchConfiguration


# def generate_launch_description():
#     pkg_name = 'lap_thu_amr_description'
#     pkg_path = get_package_share_directory(pkg_name)
#     urdf_file = os.path.join(pkg_path, 'urdf', 'lap_thu_AMR_test_2.urdf')

#     with open(urdf_file, 'r') as infp:
#         robot_description = infp.read()

#     # Add argument for Rviz config
#     # rviz_config_arg = DeclareLaunchArgument(
#     #     name='rviz_config',
#     #     default_value='',
#     #     description='Path to Rviz config file'
#     # )
#     # rviz_config = LaunchConfiguration('rviz_config')

#     rviz_config_file = 'src/lap_thu_amr_description/rviz/urdf_1.rviz'


#     node_robot_state_publisher = Node(
#         package='robot_state_publisher',
#         executable='robot_state_publisher',
#         output='screen',
#         parameters=[{'robot_description': robot_description}],
#     )

#     node_rviz = Node(
#         package='rviz2',
#         executable='rviz2',
#         name = 'rviz2',
#         output='screen',
#         # Add argument for Rviz config
#         arguments=['-d', rviz_config_file]
#     )

#     return LaunchDescription([
#         # Add argument for Rviz config
#         # rviz_config_arg,

#         node_robot_state_publisher,
#         node_rviz
#     ])




# # 3333
# # 
# # launch lap_thu_amr_description rsp.launch.py
# import os

# from ament_index_python.packages import get_package_share_directory
# from launch import LaunchDescription
# from launch_ros.actions import Node

# # Add argument for Rviz config
# from launch.actions import DeclareLaunchArgument
# from launch.substitutions import LaunchConfiguration


# def generate_launch_description():
#     pkg_name = 'lap_thu_amr_description'
#     pkg_path = get_package_share_directory(pkg_name)

#     urdf_file = os.path.join(pkg_path, 'urdf', 'lap_thu_AMR_test_2.urdf')

#     with open(urdf_file, 'r') as infp:
#         robot_description = infp.read()

#     # Default Rviz config 
#     default_rviz_config = 'src/lap_thu_amr_description/rviz/urdf_1.rviz'

#     # Launch argument (enable for override)
#     rviz_config_arg = DeclareLaunchArgument(
#         'rviz_config',
#         default_value=default_rviz_config,
#         description='Path to RViz config file'
#     )

#     # Add argument for Rviz config
#     # rviz_config_arg = DeclareLaunchArgument(
#     #     name='rviz_config',
#     #     default_value='',
#     #     description='Path to Rviz config file'
#     # )
#     rviz_config = LaunchConfiguration('rviz_config')


#     use_sim_time = LaunchConfiguration('use_sim_time', default='true')

    
#     node_robot_state_publisher = Node(
#         package='robot_state_publisher',
#         executable='robot_state_publisher',
#         output='screen',
#         parameters=[{'robot_description': robot_description,
#                      'use_sim_time': True}],
#     )

#     node_rviz = Node(
#         package='rviz2',
#         executable='rviz2',
#         name = 'rviz2',
#         output='screen',
#         # Add argument for Rviz config
#         arguments=['-d', rviz_config,],
#         parameters=[{'use_sim_time': True}]
#     )

#     return LaunchDescription([
#         # Add argument for Rviz config
#         # rviz_config_arg,

#         rviz_config_arg,
#         node_robot_state_publisher,
#         node_rviz
#     ])


import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node

import xacro


def generate_launch_description():

    # Check if we're told to use sim time
    use_sim_time = LaunchConfiguration('use_sim_time')

    # Process the URDF file
    pkg_path = os.path.join(get_package_share_directory('lap_thu_amr_description'))
    xacro_file = os.path.join(pkg_path,'description','lap_thu_AMR_test_2.urdf')
    robot_description_config = xacro.process_file(xacro_file)
    
    # Create a robot_state_publisher node
    params = {'robot_description': robot_description_config.toxml(), 'use_sim_time': use_sim_time}
    node_robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[params]
    )


    # Launch!
    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use sim time if true'),

        node_robot_state_publisher
    ])