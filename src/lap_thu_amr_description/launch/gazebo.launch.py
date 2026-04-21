# import os

# from ament_index_python.packages import get_package_share_directory
# from launch import LaunchDescription
# from launch.actions import IncludeLaunchDescription
# from launch.launch_description_sources import PythonLaunchDescriptionSource
# from launch_ros.actions import Node

# # use sim time
# from launch.substitutions import LaunchConfiguration
# from launch.actions import DeclareLaunchArgument

# #add delay
# from launch.actions import TimerAction

# def generate_launch_description():
#     pkg_name = 'lap_thu_amr_description'


#     # use sim time
#     use_sim_time = LaunchConfiguration('use_sim_time', default='true')


#     rsp = IncludeLaunchDescription(
#         PythonLaunchDescriptionSource(os.path.join(
#             get_package_share_directory(pkg_name),'launch', 'rsp.launch.py'
#             )
#         ), launch_arguments={'use_sim_time': use_sim_time}.items() # use sim time
#     )

#     gazebo = IncludeLaunchDescription(
#         PythonLaunchDescriptionSource([os.path.join(
#             get_package_share_directory('gazebo_ros'), 'launch', 'gazebo.launch.py')]
#         )
#     )

#     # spawn_entity = Node(package='gazebo_ros', executable='spawn_entity.py',
#     #                     arguments=['-topic', 'robot_description',
#     #                                '-entity', 'my_amr'],
#     #                     output='screen')

#     spawn_entity = TimerAction(
#         period=3.0, #delay 3 giay
#         actions=[Node(package='gazebo_ros', executable='spawn_entity.py',
#                         arguments=['-topic', 'robot_description',
#                                     '-entity', 'my_amr',
#                                     '-x', '0',
#                                     '-y', '0',
#                                     '-z', '1.0'],
#                         output='screen')
#         ]
#     )
    
#     return LaunchDescription([
#         DeclareLaunchArgument('use_sim_time', default_value='true'),
#         rsp,
#         gazebo,
#         spawn_entity,
#     ])
    


import os

from ament_index_python.packages import get_package_share_directory


from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource

from launch_ros.actions import Node



def generate_launch_description():


    # Include the robot_state_publisher launch file, provided by our own package. Force sim time to be enabled
    # !!! MAKE SURE YOU SET THE PACKAGE NAME CORRECTLY !!!

    package_name='amr_lan_2_mesh' #<--- CHANGE ME

    rsp = IncludeLaunchDescription(
                PythonLaunchDescriptionSource([os.path.join(
                    get_package_share_directory(package_name),'launch','rsp.launch.py'
                )]), launch_arguments={'use_sim_time': 'true'}.items()
    )

    # Include the Gazebo launch file, provided by the gazebo_ros package
    gazebo = IncludeLaunchDescription(
                PythonLaunchDescriptionSource([os.path.join(
                    get_package_share_directory('gazebo_ros'), 'launch', 'gazebo.launch.py')]),
             )

    # Run the spawner node from the gazebo_ros package. The entity name doesn't really matter if you only have a single robot.
    spawn_entity = Node(package='gazebo_ros', executable='spawn_entity.py',
                        arguments=['-topic', 'robot_description',
                                   '-entity', 'my_bot'],
                        output='screen')



    # Launch them all!
    return LaunchDescription([
        rsp,
        gazebo,
        spawn_entity,
    ])