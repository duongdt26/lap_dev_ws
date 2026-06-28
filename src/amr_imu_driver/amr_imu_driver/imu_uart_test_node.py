#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
import serial
import math

from std_srvs.srv import Trigger
import tf_transformations


class ImuUartTestNode(Node):
    def __init__(self):
        super().__init__('imu_uart_test_node')
        self.publisher_ = self.create_publisher(Imu, '/imu/data', 10)

        self.yaw_offset = 0.0
        self.request_reset = False
        self.srv = self.create_service(Trigger, 'reset_imu_yaw', self.reset_callback)

        # Có thể đổi port khi chạy: -p port:=/dev/ttyUSB2
        # self.declare_parameter('port', '/dev/serial/by-path/pci-0000:05:00.3-usb-0:3:1.0-port0')
        self.declare_parameter('port', '/dev/ttyUSB0')
        self.declare_parameter('baudrate', 256000)

        port = self.get_parameter('port').get_parameter_value().string_value
        baud = self.get_parameter('baudrate').get_parameter_value().integer_value

        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
            self.get_logger().info(
                f'Đã kết nối thành công với STM32 IMU qua cổng {port} (Baudrate: {baud})'
            )
        except Exception as e:
            self.get_logger().error(f'Không thể mở cổng Serial: {e}')
            self.ser = None
            return

        self.timer = self.create_timer(0.005, self.read_serial_callback)

    def reset_callback(self, request, response):
        self.request_reset = True
        response.success = True
        response.message = 'IMU Yaw has been reset to 0.'
        self.get_logger().info('Resetting Yaw...')
        return response

    def read_serial_callback(self):
        if self.ser is None:
            return

        if self.ser.in_waiting > 0:
            try:
                line = self.ser.readline().decode('utf-8').strip()

                if line.startswith('$IMU'):
                    parts = line.split(',')
                    if len(parts) == 11:
                        msg = Imu()
                        msg.header.stamp = self.get_clock().now().to_msg()
                        msg.header.frame_id = 'imu_link'

                        qw_raw = float(parts[1])
                        qx_raw = float(parts[2])
                        qy_raw = float(parts[3])
                        qz_raw = float(parts[4])

                        euler = tf_transformations.euler_from_quaternion(
                            [qx_raw, qy_raw, qz_raw, qw_raw]
                        )
                        roll, pitch, yaw = euler[0], euler[1], euler[2]

                        if getattr(self, 'request_reset', False):
                            self.yaw_offset = yaw
                            self.request_reset = False
                            self.get_logger().info(
                                f'New Yaw Offset has been updated succesfully: {self.yaw_offset:.4f} rad'
                            )

                        yaw_corrected = yaw - self.yaw_offset
                        q_new = tf_transformations.quaternion_from_euler(
                            roll, pitch, yaw_corrected
                        )

                        msg.orientation.x = q_new[0]
                        msg.orientation.y = q_new[1]
                        msg.orientation.z = q_new[2]
                        msg.orientation.w = q_new[3]

                        msg.angular_velocity.x = float(parts[5])
                        msg.angular_velocity.y = float(parts[6])
                        msg.angular_velocity.z = float(parts[7])

                        msg.linear_acceleration.x = float(parts[8])
                        msg.linear_acceleration.y = float(parts[9])
                        msg.linear_acceleration.z = float(parts[10])

                        msg.orientation_covariance = [
                            0.01, 0.0, 0.0,
                            0.0, 0.01, 0.0,
                            0.0, 0.0, 0.01,
                        ]
                        msg.angular_velocity_covariance = [
                            0.00001, 0.0, 0.0,
                            0.0, 0.00001, 0.0,
                            0.0, 0.0, 0.000005,
                        ]
                        msg.linear_acceleration_covariance = [
                            0.002, 0.0, 0.0,
                            0.0, 0.002, 0.0,
                            0.0, 0.0, 0.002,
                        ]

                        self.publisher_.publish(msg)
            except Exception:
                pass


def main(args=None):
    rclpy.init(args=args)
    node = ImuUartTestNode()
    if node.ser is not None:
        rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()