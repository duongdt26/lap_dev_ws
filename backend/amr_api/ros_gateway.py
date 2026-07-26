"""Small rclpy gateway used while replacing browser-side ROSLIB calls."""

from __future__ import annotations

import math
import threading
from copy import deepcopy
from typing import Any

from .config import Settings


class TelemetryState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._version = 0
        self._value: dict[str, Any] = {
            "ros": {"connected": False, "error": "Chưa khởi động"}
        }

    def update(self, key: str, value: Any) -> None:
        with self._lock:
            self._value[key] = value
            self._version += 1

    def snapshot(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            return self._version, deepcopy(self._value)


class RosGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.telemetry = TelemetryState()
        self.node = None
        self.executor = None
        self.thread: threading.Thread | None = None
        self._rclpy = None
        self._cmd_vel_pub = None
        self._cmd_vel_pause_pub = None
        self._nav_pause_timer = None
        self._nav_paused = False
        self._send_nav_client = None
        self._cancel_nav_client = None

    @property
    def available(self) -> bool:
        return self.node is not None

    def start(self) -> None:
        if not self.settings.enable_ros_gateway:
            self.telemetry.update(
                "ros", {"connected": False, "error": "ROS gateway bị tắt trong cấu hình"}
            )
            return
        try:
            import rclpy
            from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
            from nav_msgs.msg import Odometry
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.parameter import Parameter
            from sensor_msgs.msg import BatteryState
            from std_msgs.msg import String
            from std_srvs.srv import Trigger
            from amr_web_interfaces.srv import SendNavGoal
        except ImportError as exc:
            self.telemetry.update(
                "ros",
                {
                    "connected": False,
                    "error": f"Chưa source ROS workspace: {exc}",
                },
            )
            return

        try:
            if not rclpy.ok():
                rclpy.init(args=None)
            self._rclpy = rclpy
            self.node = rclpy.create_node(
                "amr_api_gateway",
                parameter_overrides=[
                    Parameter(
                        "use_sim_time",
                        Parameter.Type.BOOL,
                        self.settings.use_sim_time,
                    )
                ],
            )
            self.executor = MultiThreadedExecutor(num_threads=2)
            self.executor.add_node(self.node)
            self._cmd_vel_pub = self.node.create_publisher(Twist, "/cmd_vel_web", 10)
            self._cmd_vel_pause_pub = self.node.create_publisher(Twist, "/cmd_vel_pause", 10)
            self._send_nav_client = self.node.create_client(SendNavGoal, "/send_nav_goal")
            self._cancel_nav_client = self.node.create_client(Trigger, "/cancel_nav")

            def odom_callback(message) -> None:
                self.telemetry.update(
                    "odometry",
                    {
                        "linearX": message.twist.twist.linear.x,
                        "angularZ": message.twist.twist.angular.z,
                    },
                )

            def pose_callback(message) -> None:
                pose = message.pose.pose
                quaternion = pose.orientation
                yaw = math.atan2(
                    2.0 * (quaternion.w * quaternion.z + quaternion.x * quaternion.y),
                    1.0 - 2.0 * (quaternion.y**2 + quaternion.z**2),
                )
                self.telemetry.update(
                    "pose",
                    {
                        "x": pose.position.x,
                        "y": pose.position.y,
                        "yaw": yaw,
                        "yawDeg": math.degrees(yaw),
                    },
                )

            def battery_callback(message) -> None:
                def _finite_or_none(value: float):
                    return float(value) if math.isfinite(value) else None

                self.telemetry.update(
                    "battery",
                    {
                        "percentage": _finite_or_none(message.percentage),
                        "voltage": _finite_or_none(message.voltage),
                        "current": _finite_or_none(message.current),
                    },
                )

            def string_callback(key: str):
                return lambda message: self.telemetry.update(key, message.data)

            self.node.create_subscription(Odometry, "/odometry/filtered", odom_callback, 10)
            self.node.create_subscription(
                PoseWithCovarianceStamped, "/robot_pose_map", pose_callback, 10
            )
            self.node.create_subscription(BatteryState, "/battery_state", battery_callback, 10)
            self.node.create_subscription(
                String, "/web_nav_status", string_callback("navigation"), 10
            )
            self.node.create_subscription(
                String, "/mission/status", string_callback("mission"), 10
            )

            self.thread = threading.Thread(
                target=self.executor.spin,
                name="amr-api-ros-executor",
                daemon=True,
            )
            self.thread.start()
            self.telemetry.update(
                "ros",
                {
                    "connected": True,
                    "useSimTime": self.settings.use_sim_time,
                },
            )
        except Exception as exc:
            self.telemetry.update("ros", {"connected": False, "error": str(exc)})
            self.stop()

    def publish_teleop(self, linear_x: float, angular_z: float) -> None:
        if self.node is None or self._cmd_vel_pub is None:
            raise RuntimeError("ROS gateway chưa sẵn sàng")
        from geometry_msgs.msg import Twist

        message = Twist()
        message.linear.x = float(linear_x)
        message.angular.z = float(angular_z)
        self._cmd_vel_pub.publish(message)

    def _publish_pause_zero(self) -> None:
        if self._cmd_vel_pause_pub is None:
            return
        from geometry_msgs.msg import Twist

        self._cmd_vel_pause_pub.publish(Twist())

    def set_nav_paused(self, paused: bool) -> bool:
        """Đè Twist(0) lên /cmd_vel_pause để đứng yên, không hủy Nav2."""
        if self.node is None or self._cmd_vel_pause_pub is None:
            raise RuntimeError("ROS gateway chưa sẵn sàng")

        if paused:
            if self._nav_pause_timer is None:
                self._publish_pause_zero()
                self._nav_pause_timer = self.node.create_timer(0.1, self._publish_pause_zero)
            self._nav_paused = True
        else:
            if self._nav_pause_timer is not None:
                self._nav_pause_timer.cancel()
                self.node.destroy_timer(self._nav_pause_timer)
                self._nav_pause_timer = None
            self._nav_paused = False
        self.telemetry.update("navPause", {"paused": self._nav_paused})
        return self._nav_paused

    @property
    def nav_paused(self) -> bool:
        return self._nav_paused

    def _call_service(self, client, request, timeout_sec: float = 5.0):
        if client is None or not client.wait_for_service(timeout_sec=timeout_sec):
            raise RuntimeError("ROS service chưa sẵn sàng")
        future = client.call_async(request)
        done = threading.Event()
        future.add_done_callback(lambda _future: done.set())
        if not done.wait(timeout_sec):
            raise RuntimeError("ROS service timeout")
        return future.result()

    def send_nav_goal(self, x: float, y: float, yaw: float, controller_id: str = ""):
        from amr_web_interfaces.srv import SendNavGoal

        request = SendNavGoal.Request()
        request.x = float(x)
        request.y = float(y)
        request.yaw = float(yaw)
        request.controller_id = controller_id or ""
        return self._call_service(self._send_nav_client, request, 5.0)

    def cancel_nav(self):
        from std_srvs.srv import Trigger

        return self._call_service(self._cancel_nav_client, Trigger.Request(), 5.0)

    def stop(self) -> None:
        try:
            if self._nav_paused:
                self.set_nav_paused(False)
        except Exception:
            pass
        if self.executor is not None:
            self.executor.shutdown(timeout_sec=2.0)
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.node is not None:
            self.node.destroy_node()
        self.executor = None
        self.node = None
        self._cmd_vel_pub = None
        self._cmd_vel_pause_pub = None
        self._nav_pause_timer = None
        self._nav_paused = False
        self._send_nav_client = None
        self._cancel_nav_client = None
        self.thread = None
        if self._rclpy is not None and self._rclpy.ok():
            self._rclpy.shutdown()


_gateway: RosGateway | None = None


def get_ros_gateway(settings: Settings | None = None) -> RosGateway:
    global _gateway
    if _gateway is None:
        from .config import get_settings

        _gateway = RosGateway(settings or get_settings())
    return _gateway
