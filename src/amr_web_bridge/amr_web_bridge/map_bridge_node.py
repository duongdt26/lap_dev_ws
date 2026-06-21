#!/usr/bin/env python3
"""Node cầu nối: web set parameter map_name → gọi /save_map (Trigger)."""

import os
import subprocess

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger


class MapBridgeNode(Node):
    def __init__(self):
        super().__init__('map_bridge_node')

        self.maps_dir = os.path.expanduser('~/maps')
        os.makedirs(self.maps_dir, exist_ok=True)

        # Web gửi tên map qua parameter trước khi gọi service
        self.declare_parameter('map_name', '')

        self.srv = self.create_service(
            Trigger, '/save_map', self.save_map_callback)
        self.get_logger().info(f'Service /save_map (Trigger) → {self.maps_dir}')

        # Web goi / list map danh sach map trong ~/maps
        self.list_srv = self.create_service(
            Trigger, '/list_maps', self.list_maps_callback)
        self.get_logger().info(f'Service /list_maps → {self.maps_dir}')

    def save_map_callback(self, request, response):
        name = self.get_parameter('map_name').get_parameter_value().string_value.strip()
        if not name:
            response.success = False
            response.message = 'Parameter map_name trống — web phải set tên trước'
            return response

        out_path = os.path.join(self.maps_dir, name)
        cmd = [
            'ros2', 'run', 'nav2_map_server', 'map_saver_cli',
            '-f', out_path,
        ]
        self.get_logger().info(f'Lưu map: {" ".join(cmd)}')

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                response.success = True
                response.message = f'Đã lưu: {out_path}.yaml + .pgm'
            else:
                response.success = False
                response.message = result.stderr or result.stdout
        except subprocess.TimeoutExpired:
            response.success = False
            response.message = 'Timeout — /map có đang publish không?'
        except Exception as e:
            response.success = False
            response.message = str(e)

        return response

    def list_maps_callback(self, request, response):
        import glob
        files = sorted(glob.glob(os.path.join(self.maps_dir, '*.yaml')))
        # message: tên1,tên2,... (không có .yaml)
        names = [os.path.splitext(os.path.basename(f))[0] for f in files]
        response.success = True
        response.message = ','.join(names) if names else ''
        if not names:
            response.message = '(chưa có map trong ~/maps)'
        return response

def main():
    rclpy.init()
    node = MapBridgeNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()