# import os
# from launch import LaunchDescription
# from launch_ros.actions import Node

# def generate_launch_description():

#     return LaunchDescription([

#         Node(
#             package='rplidar_ros',
#             executable='rplidar_composition',
#             output='screen',
#             parameters=[{
#                 # 'serial_port': '/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.4:1.0-port0',
#                 # 'serial_port': '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0',
#                  'serial_port': '/dev/serial/by-path/pci-0000:05:00.4-usb-0:2:1.0-port0',

#                 'frame_id': 'laser_frame',
#                 'angle_compensate': True,
#                 # 'scan_mode': 'Standard',
#                 'scan_mode': 'Stability',
#                 'serial_baudrate': 115200,
#             }]
#         )

#     ]
#     )

import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():

    scan_mode = LaunchConfiguration('scan_mode', default='Boost')

    return LaunchDescription([

        DeclareLaunchArgument(
            'scan_mode',
            default_value=scan_mode,
            description='Specifying scan mode of lidar'),

        Node(
            package='rplidar_ros',
            executable='rplidar_composition',
            output='screen',
            parameters=[{
                # 'serial_port': '/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.2:1.0-port0',
                # 'serial_port': '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0',
                'serial_port': '/dev/serial/by-path/pci-0000:05:00.4-usb-0:2:1.0-port0',
                'frame_id': 'laser_frame',
                'angle_compensate': True,
                # 'scan_mode': 'Standard',
                # 'scan_mode': 'Express',
                # 'scan_mode': 'Sensitivity',
                'scan_mode': scan_mode,   
                'serial_baudrate': 115200,
            }]
        )

    ]
    )