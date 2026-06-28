#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
import serial
# import math

#adding service
# from std_srvs.srv import Trigger
# import tf_transformations # sudo apt install ros-humble-tf-transformations
#adding service


class ImuUartNode(Node):
    def __init__(self):
        super().__init__('imu_uart_node')
        self.publisher_ = self.create_publisher(Imu, '/imu/data', 10)

        # #adding service
        # # Khoi tao bien luu tru Offset va tao Service
        # self.yaw_offset = 0.0
        # self.request_reset = False
        # self.srv = self.create_service(Trigger, 'reset_imu_yaw', self.reset_callback)
        # #adding service
        
        # Cấu hình cổng Serial (Khớp với cấu hình 256000 trên STM32)
        # self.declare_parameter('port', '/dev/ttyUSB0')
        # self.declare_parameter('port', '/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0-port0')
        self.declare_parameter('port', '/dev/serial/by-path/pci-0000:05:00.3-usb-0:3:1.0-port0')
        self.declare_parameter('baudrate', 256000)
        
        port = self.get_parameter('port').get_parameter_value().string_value
        baud = self.get_parameter('baudrate').get_parameter_value().integer_value
        
        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
            self.get_logger().info(f"Đã kết nối thành công với STM32 IMU qua cổng {port} (Baudrate: {baud})")
        except Exception as e:
            self.get_logger().error(f"Không thể mở cổng Serial: {e}")
            self.ser = None
            return

        # Đọc dữ liệu liên tục với tần số cao (khoảng 200Hz để không miss bản tin 100Hz của STM32)
        self.timer = self.create_timer(0.005, self.read_serial_callback)

    # #adding service
    # def reset_callback(self, request, response):
    #     self.request_reset = True
    #     response.success = True
    #     response.message = "IMU Yaw has been reset to 0."
    #     self.get_logger().info("Resetting Yaw...")
    #     return response
    # #adding service

    def read_serial_callback(self):
        if self.ser is None:
            return
            
        if self.ser.in_waiting > 0:
            try:
                # Đọc 1 dòng dữ liệu từ UART
                line = self.ser.readline().decode('utf-8').strip()
                
                # Kiểm tra header bản tin
                if line.startswith('$IMU'):
                    parts = line.split(',')
                    if len(parts) == 11:
                        msg = Imu()
                        msg.header.stamp = self.get_clock().now().to_msg()
                        msg.header.frame_id = 'imu_link' # Cần khớp với URDF sau này

                        # #adding service
                        # qw_raw = float(parts[1])
                        # qx_raw = float(parts[2])
                        # qy_raw = float(parts[3])
                        # qz_raw = float(parts[4])

                        # # Chuyen Quaternion goc sang Euler (Roll, Pitch, Yaw)
                        # euler = tf_transformations.euler_from_quaternion([qx_raw, qy_raw, qz_raw, qw_raw])
                        # roll, pitch, yaw = euler[0], euler[1], euler[2]

                        # if getattr(self, 'request_reset', False):
                        #     self.yaw_offset = yaw # Luu lai goc Yaw hien tai lam moc 0 moi
                        #     self.request_reset = False
                        #     self.get_logger().info(f"New Yaw Offset has been updated succesfully: {self.yaw_offset:.4f} rad") 

                        # # Tru di offset de ra goc Yaw da hieu chinh
                        # yaw_corrected = yaw - self.yaw_offset

                        # # Dong goi lai thanh Quaternion moi de Publish
                        # q_new = tf_transformations.quaternion_from_euler(roll, pitch, yaw_corrected)                      

                        # # Dong goi lai quaternion moi de publish

                        # msg.orientation.x = q_new[0]
                        # msg.orientation.y = q_new[1]
                        # msg.orientation.z = q_new[2]
                        # msg.orientation.w = q_new[3]
                        # #adding service   

                        # EKF chỉ dùng gyro Z — không publish orientation
                        msg.orientation_covariance[0] = -1.0

                        # Hướng (Quaternion)
                        # msg.orientation.w = float(parts[1])
                        # msg.orientation.x = float(parts[2])
                        # msg.orientation.y = float(parts[3])
                        # msg.orientation.z = float(parts[4])


                        # Vận tốc góc (Radian/s)
                        msg.angular_velocity.x = float(parts[5])
                        msg.angular_velocity.y = float(parts[6])
                        msg.angular_velocity.z = float(parts[7])
                        # self.get_logger().info(f"Angular Velocity: {msg.angular_velocity.z:.4f} rad/s")
                        if abs(msg.angular_velocity.z) < 0.004:
                            msg.angular_velocity.z = 0.0

                        # Gia tốc (m/s^2)
                        msg.linear_acceleration.x = float(parts[8])
                        msg.linear_acceleration.y = float(parts[9])
                        msg.linear_acceleration.z = float(parts[10])

                        # Ma trận hiệp phương sai (Covariance)
                        # Orientation không dùng trong EKF nên cứ để mặc định hoặc -1 để báo EKF bỏ qua
                        # msg.orientation_covariance = [0.01, 0.0, 0.0,
                        #                                 0.0, 0.01, 0.0,
                        #                                 0.0, 0.0, 0.01]
                        # Vận tốc góc: Z rất ít nhiễu (khoảng 0.000005), X và Y có thể để lớn hơn chút
                        # msg.angular_velocity_covariance = [0.00001, 0.0, 0.0, 
                        #                                     0.0, 0.00001, 0.0,
                        #                                     0.0, 0.0, 0.000005]
                        # msg.angular_velocity_covariance = [0.01, 0.0, 0.0, 
                        #                                     0.0, 0.01, 0.0,
                        #                                     0.0, 0.0, 0.00005]
                        # Chỉ hỗ trợ lọc nhiễu khi quay nhanh
                        msg.angular_velocity_covariance = [0.1, 0.0, 0.0,
                                                            0.0, 0.1, 0.0,
                                                            0.0, 0.0, 0.02]
                        msg.linear_acceleration_covariance = [0.002, 0.0, 0.0, 
                                                            0.0, 0.002, 0.0, 
                                                            0.0, 0.0, 0.002]

                        self.publisher_.publish(msg)
            except Exception as e:
                pass # Bỏ qua các dòng rác hoặc lỗi decode khi mới cắm cáp

def main(args=None):
    rclpy.init(args=args)
    node = ImuUartNode()
    if node.ser is not None:
        rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()