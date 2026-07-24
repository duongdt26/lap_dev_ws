#!/usr/bin/env python3
import os
import struct
import select
import fcntl

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

JS_EVENT_FORMAT = 'IhBB'
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FORMAT)
JS_EVENT_AXIS = 0x02


class Ps2TeleopNode(Node):
    def __init__(self):
        super().__init__('ps2_teleop_node')

        self.declare_parameter('device', '/dev/input/js0')
        self.declare_parameter('cmd_vel_topic', 'cmd_vel_key')
        self.declare_parameter('max_linear', 0.8)
        self.declare_parameter('max_angular', 0.5)
        self.declare_parameter('deadzone', 0.15)
        self.declare_parameter('publish_rate_hz', 20.0)
        self.declare_parameter('require_enable_button', False)

        # Stick trái
        self.declare_parameter('axis_linear', 1)
        self.declare_parameter('axis_angular', 0)
        self.declare_parameter('invert_linear', False)
        self.declare_parameter('invert_angular', True)

        # Stick phải
        self.declare_parameter('use_right_stick', True)
        self.declare_parameter('axis_linear_right', 4)
        self.declare_parameter('axis_angular_right', 3)
        self.declare_parameter('invert_linear_right', False)
        self.declare_parameter('invert_angular_right', True)

        # D-pad
        self.declare_parameter('use_dpad', True)
        self.declare_parameter('dpad_hat_x', 6)
        self.declare_parameter('dpad_hat_y', 7)
        self.declare_parameter('invert_dpad_linear', True)
        self.declare_parameter('invert_dpad_angular', False)
        self.declare_parameter('dpad_linear_speed', 0.4)
        self.declare_parameter('dpad_angular_speed', 0.4)

        topic = self.get_parameter('cmd_vel_topic').value
        self._pub = self.create_publisher(Twist, topic, 10)

        self._max_lin = float(self.get_parameter('max_linear').value)
        self._max_ang = float(self.get_parameter('max_angular').value)
        self._deadzone = float(self.get_parameter('deadzone').value)

        self._left_cfg = (
            int(self.get_parameter('axis_linear').value),
            int(self.get_parameter('axis_angular').value),
            bool(self.get_parameter('invert_linear').value),
            bool(self.get_parameter('invert_angular').value),
        )
        self._right_cfg = (
            int(self.get_parameter('axis_linear_right').value),
            int(self.get_parameter('axis_angular_right').value),
            bool(self.get_parameter('invert_linear_right').value),
            bool(self.get_parameter('invert_angular_right').value),
        )
        self._use_right = bool(self.get_parameter('use_right_stick').value)
        self._use_dpad = bool(self.get_parameter('use_dpad').value)
        self._dpad_hat_x = int(self.get_parameter('dpad_hat_x').value)
        self._dpad_hat_y = int(self.get_parameter('dpad_hat_y').value)
        self._inv_dpad_lin = bool(self.get_parameter('invert_dpad_linear').value)
        self._inv_dpad_ang = bool(self.get_parameter('invert_dpad_angular').value)
        self._dpad_lin = float(self.get_parameter('dpad_linear_speed').value)
        self._dpad_ang = float(self.get_parameter('dpad_angular_speed').value)

        device = self.get_parameter('device').value
        self._fd = self._open_joystick(device)
        self._axes = {}

        rate = float(self.get_parameter('publish_rate_hz').value)
        self._timer = self.create_timer(1.0 / rate, self._publish_cmd_vel)
        self.get_logger().info(f'PS2 teleop ready: {device} -> /{topic}')

    def _open_joystick(self, path: str):
        if not os.path.exists(path):
            raise RuntimeError(f'Joystick not found: {path}')
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        return fd

    def _poll_events(self):
        while True:
            ready, _, _ = select.select([self._fd], [], [], 0.0)
            if not ready:
                break
            try:
                data = os.read(self._fd, JS_EVENT_SIZE)
            except BlockingIOError:
                break
            if len(data) < JS_EVENT_SIZE:
                break

            _time, value, evt_type, number = struct.unpack(JS_EVENT_FORMAT, data)
            if evt_type & JS_EVENT_AXIS:
                self._axes[number] = value / 32767.0

    def _apply_deadzone(self, v: float) -> float:
        if abs(v) < self._deadzone:
            return 0.0
        sign = 1.0 if v > 0 else -1.0
        scaled = (abs(v) - self._deadzone) / (1.0 - self._deadzone)
        return sign * max(0.0, min(1.0, scaled))

    def _stick_velocity(self, axis_lin, axis_ang, inv_lin, inv_ang):
        raw_lin = self._axes.get(axis_lin, 0.0)
        raw_ang = self._axes.get(axis_ang, 0.0)
        if inv_lin:
            raw_lin = -raw_lin
        if inv_ang:
            raw_ang = -raw_ang
        return (
            self._apply_deadzone(raw_lin) * self._max_lin,
            self._apply_deadzone(raw_ang) * self._max_ang,
        )

    def _pick_stronger(self, a: float, b: float) -> float:
        return a if abs(a) >= abs(b) else b

    def _dpad_velocity(self):
        lin = 0.0
        ang = 0.0
        hat_x = self._axes.get(self._dpad_hat_x, 0.0)
        hat_y = self._axes.get(self._dpad_hat_y, 0.0)

        if hat_y > 0.5:
            lin = self._dpad_lin
        elif hat_y < -0.5:
            lin = -self._dpad_lin
        if hat_x > 0.5:
            ang = -self._dpad_ang
        elif hat_x < -0.5:
            ang = self._dpad_ang

        if self._inv_dpad_lin:
            lin = -lin
        if self._inv_dpad_ang:
            ang = -ang
        return lin, ang

    def _publish_cmd_vel(self):
        self._poll_events()

        lin_l, ang_l = self._stick_velocity(*self._left_cfg)
        lin, ang = lin_l, ang_l

        if self._use_right:
            lin_r, ang_r = self._stick_velocity(*self._right_cfg)
            lin = self._pick_stronger(lin_l, lin_r)
            ang = self._pick_stronger(ang_l, ang_r)

        if self._use_dpad:
            dpad_lin, dpad_ang = self._dpad_velocity()
            if abs(dpad_lin) > abs(lin):
                lin = dpad_lin
            if abs(dpad_ang) > abs(ang):
                ang = dpad_ang

        msg = Twist()
        msg.linear.x = lin
        msg.angular.z = ang
        self._pub.publish(msg)

    def destroy_node(self):
        if hasattr(self, '_fd'):
            os.close(self._fd)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = Ps2TeleopNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        stop = Twist()
        node._pub.publish(stop)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()