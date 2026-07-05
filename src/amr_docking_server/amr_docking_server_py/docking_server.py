import math
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import rclpy
import yaml
from amr_docking_server.action import Dock
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool
from tf2_ros import Buffer, TransformException, TransformListener


def normalize_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def yaw_from_quat(q) -> float:
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


@dataclass
class Pose2D:
    frame_id: str
    x: float
    y: float
    yaw: float


class VelocityRamp:
    def __init__(self, max_accel: float, max_jerk: float, dt: float):
        self.max_accel = max_accel
        self.max_jerk = max_jerk
        self.dt = dt
        self.v = 0.0
        self.w = 0.0
        self.a_v = 0.0
        self.a_w = 0.0

    def reset(self):
        self.v = 0.0
        self.w = 0.0
        self.a_v = 0.0
        self.a_w = 0.0

    def step_axis(self, current: float, target: float, accel: float) -> float:
        delta = target - current
        limit = accel * self.dt
        if delta > limit:
            return current + limit
        if delta < -limit:
            return current - limit
        return target

    def step(self, target_v: float, target_w: float):
        self.v = self.step_axis(self.v, target_v, self.max_accel)
        self.w = self.step_axis(self.w, target_w, self.max_jerk)
        return self.v, self.w


class DockingServer(Node):
    def __init__(self):
        super().__init__('docking_server')
        self.cb_group = ReentrantCallbackGroup()

        self.declare_parameter('station_database', '')
        self.declare_parameter('cmd_vel_topic', '/cmd_vel_dock')
        self.declare_parameter('odom_topic', '/odometry/filtered')
        self.declare_parameter('scan_topic', '/scan_filtered')
        self.declare_parameter('emergency_topic', '/emergency/bumper')
        self.declare_parameter('base_frame', 'base_footprint')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('control_rate_hz', 20.0)
        self.declare_parameter('dock_speed', 0.06)
        self.declare_parameter('undock_speed', 0.06)
        self.declare_parameter('max_angular_speed', 0.08)
        self.declare_parameter('max_linear_accel', 0.08)
        self.declare_parameter('max_angular_accel', 0.12)
        self.declare_parameter('near_a_tolerance_m', 0.25)
        self.declare_parameter('goal_tolerance_m', 0.035)
        self.declare_parameter('yaw_align_tolerance_rad', math.radians(3.0))
        self.declare_parameter('yaw_abort_rad', math.radians(5.0))
        self.declare_parameter('lateral_abort_m', 0.08)
        self.declare_parameter('obstacle_stop_distance_m', 0.45)
        self.declare_parameter('front_scan_half_angle_rad', math.radians(18.0))
        self.declare_parameter('dock_timeout_sec', 60.0)
        self.declare_parameter('tf_timeout_sec', 0.15)
        self.declare_parameter('enable_dynamic_costmap_tuning', True)
        self.declare_parameter('dock_costmap_inflation_radius', 0.33)
        self.declare_parameter('restore_costmap_after_dock', True)
        self.declare_parameter('costmap_parameter_timeout_sec', 1.0)
        self.declare_parameter('dock_costmap_nodes', [
            '/local_costmap/local_costmap',
            '/global_costmap/global_costmap',
        ])
        self.declare_parameter('dock_costmap_parameters', [
            'inflation_layer.inflation_radius',
        ])

        self.cmd_pub = self.create_publisher(
            Twist, self.get_parameter('cmd_vel_topic').value, 10)
        self.odom_sub = self.create_subscription(
            Odometry, self.get_parameter('odom_topic').value,
            self._odom_cb, qos_profile_sensor_data)
        self.scan_sub = self.create_subscription(
            LaserScan, self.get_parameter('scan_topic').value,
            self._scan_cb, qos_profile_sensor_data)
        self.emergency_sub = self.create_subscription(
            Bool, self.get_parameter('emergency_topic').value,
            self._emergency_cb, 10)

        self.tf_buffer = Buffer(cache_time=Duration(seconds=20.0))
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.stations = self._load_station_db()
        self.odom: Optional[Odometry] = None
        self.front_obstacle_m = float('inf')
        self.emergency_active = False
        self.lock = threading.Lock()
        self._costmap_param_clients = {}

        self.action_server = ActionServer(
            self, Dock, '/dock', execute_callback=self.execute_callback,
            goal_callback=self.goal_callback, cancel_callback=self.cancel_callback,
            callback_group=self.cb_group)
        self.get_logger().info('Dock action server ready on /dock')

    def _load_station_db(self) -> Dict[str, Dict[str, Pose2D]]:
        path = self.get_parameter('station_database').value
        if not path:
            raise RuntimeError('station_database parameter is empty')
        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}
        stations = {}
        for station_id, poses in raw.get('stations', {}).items():
            stations[station_id] = {}
            for name, data in poses.items():
                stations[station_id][name] = Pose2D(
                    frame_id=str(data.get('frame_id', 'map')),
                    x=float(data['x']),
                    y=float(data['y']),
                    yaw=float(data['yaw']),
                )
        self.get_logger().info(f'Loaded stations: {list(stations.keys())}')
        return stations

    def _odom_cb(self, msg: Odometry):
        with self.lock:
            self.odom = msg

    def _scan_cb(self, msg: LaserScan):
        half = self.get_parameter('front_scan_half_angle_rad').value
        best = float('inf')
        for i, value in enumerate(msg.ranges):
            if not math.isfinite(value) or value < msg.range_min or value > msg.range_max:
                continue
            angle = msg.angle_min + i * msg.angle_increment
            if abs(angle) <= half:
                best = min(best, value)
        self.front_obstacle_m = best

    def _emergency_cb(self, msg: Bool):
        self.emergency_active = bool(msg.data)

    def goal_callback(self, goal_request):
        if goal_request.mode not in ('DOCK_IN', 'UNDOCK_OUT'):
            self.get_logger().error(f'Invalid dock mode: {goal_request.mode}')
            return GoalResponse.REJECT
        if goal_request.station_id not in self.stations and not goal_request.target_pose.header.frame_id:
            self.get_logger().error(f'Unknown station: {goal_request.station_id}')
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        del goal_handle
        self.publish_zero(8)
        return CancelResponse.ACCEPT

    def publish_zero(self, count: int = 1):
        zero = Twist()
        for _ in range(count):
            self.cmd_pub.publish(zero)

    def current_map_pose(self) -> Pose2D:
        base = self.get_parameter('base_frame').value
        frame = self.get_parameter('map_frame').value
        timeout = Duration(seconds=float(self.get_parameter('tf_timeout_sec').value))
        t = self.tf_buffer.lookup_transform(frame, base, rclpy.time.Time(), timeout=timeout)
        return Pose2D(
            frame_id=frame,
            x=t.transform.translation.x,
            y=t.transform.translation.y,
            yaw=yaw_from_quat(t.transform.rotation),
        )

    def pose_stamped_to_pose2d(self, msg) -> Pose2D:
        return Pose2D(
            frame_id=msg.header.frame_id or self.get_parameter('map_frame').value,
            x=float(msg.pose.position.x),
            y=float(msg.pose.position.y),
            yaw=yaw_from_quat(msg.pose.orientation),
        )

    def current_odom_pose(self) -> Pose2D:
        with self.lock:
            odom = self.odom
        if odom is None:
            raise RuntimeError('No odometry received yet')
        p = odom.pose.pose.position
        return Pose2D(
            frame_id=odom.header.frame_id,
            x=p.x,
            y=p.y,
            yaw=yaw_from_quat(odom.pose.pose.orientation),
        )

    def _feedback(self, goal_handle, state, distance, yaw_error, lateral):
        fb = Dock.Feedback()
        fb.state = state
        fb.distance_remaining = float(max(distance, 0.0))
        fb.yaw_error = float(yaw_error)
        fb.lateral_error = float(lateral)
        goal_handle.publish_feedback(fb)
        self.get_logger().info(
            f'{state}: dist={distance:.3f} yaw={math.degrees(yaw_error):.2f}deg '
            f'lat={lateral:.3f} obstacle={self.front_obstacle_m:.2f}m')

    def _check_safety(self, allow_obstacle: bool = False):
        if self.emergency_active:
            raise RuntimeError('emergency active')
        if not allow_obstacle:
            stop = self.get_parameter('obstacle_stop_distance_m').value
            if self.front_obstacle_m < stop:
                raise RuntimeError(f'obstacle too close: {self.front_obstacle_m:.2f}m')

    def _wait_future(self, future, timeout_sec: float) -> bool:
        deadline = time.monotonic() + float(timeout_sec)
        while rclpy.ok() and not future.done():
            if time.monotonic() > deadline:
                return False
            time.sleep(0.02)
        return future.done()

    def _costmap_clients(self, node_name: str):
        if node_name not in self._costmap_param_clients:
            prefix = node_name.rstrip('/')
            self._costmap_param_clients[node_name] = (
                self.create_client(
                    GetParameters,
                    f'{prefix}/get_parameters',
                    callback_group=self.cb_group,
                ),
                self.create_client(
                    SetParameters,
                    f'{prefix}/set_parameters',
                    callback_group=self.cb_group,
                ),
            )
        return self._costmap_param_clients[node_name]

    def _get_costmap_params(self, node_name: str, names):
        timeout = float(self.get_parameter('costmap_parameter_timeout_sec').value)
        get_cli, _ = self._costmap_clients(node_name)
        if not get_cli.wait_for_service(timeout_sec=timeout):
            self.get_logger().warn(f'Costmap parameter service not ready: {node_name}/get_parameters')
            return {}

        req = GetParameters.Request()
        req.names = list(names)
        future = get_cli.call_async(req)
        if not self._wait_future(future, timeout):
            self.get_logger().warn(f'Costmap get_parameters timeout: {node_name}')
            return {}

        try:
            res = future.result()
        except Exception as exc:
            self.get_logger().warn(f'Costmap get_parameters failed on {node_name}: {exc}')
            return {}

        values = {}
        for name, value in zip(names, res.values):
            if value.type == ParameterType.PARAMETER_DOUBLE:
                values[name] = float(value.double_value)
        return values

    def _set_costmap_params(self, node_name: str, values: Dict[str, float]) -> bool:
        timeout = float(self.get_parameter('costmap_parameter_timeout_sec').value)
        _, set_cli = self._costmap_clients(node_name)
        if not set_cli.wait_for_service(timeout_sec=timeout):
            self.get_logger().warn(f'Costmap parameter service not ready: {node_name}/set_parameters')
            return False

        req = SetParameters.Request()
        for name, value in values.items():
            param = Parameter()
            param.name = name
            param.value = ParameterValue(
                type=ParameterType.PARAMETER_DOUBLE,
                double_value=float(value),
            )
            req.parameters.append(param)

        future = set_cli.call_async(req)
        if not self._wait_future(future, timeout):
            self.get_logger().warn(f'Costmap set_parameters timeout: {node_name}')
            return False

        try:
            res = future.result()
        except Exception as exc:
            self.get_logger().warn(f'Costmap set_parameters failed on {node_name}: {exc}')
            return False

        ok = True
        for result in res.results:
            if not result.successful:
                ok = False
                self.get_logger().warn(
                    f'Costmap rejected parameter on {node_name}: {result.reason}')
        return ok

    def _enter_docking_costmap_mode(self) -> Dict[str, Dict[str, float]]:
        if not bool(self.get_parameter('enable_dynamic_costmap_tuning').value):
            return {}

        nodes = list(self.get_parameter('dock_costmap_nodes').value)
        param_names = list(self.get_parameter('dock_costmap_parameters').value)
        radius = float(self.get_parameter('dock_costmap_inflation_radius').value)
        restore_values = {}

        for node_name in nodes:
            original = self._get_costmap_params(node_name, param_names)
            if original:
                restore_values[node_name] = original

            target = {name: radius for name in param_names}
            if self._set_costmap_params(node_name, target):
                self.get_logger().info(
                    f'Docking costmap mode: {node_name} {target}')

        return restore_values

    def _restore_costmap_mode(self, restore_values: Dict[str, Dict[str, float]]):
        if not restore_values:
            return
        if not bool(self.get_parameter('restore_costmap_after_dock').value):
            return

        for node_name, values in restore_values.items():
            if self._set_costmap_params(node_name, values):
                self.get_logger().info(
                    f'Restored costmap params: {node_name} {values}')

    def execute_callback(self, goal_handle):
        goal = goal_handle.request
        result = Dock.Result()
        restore_costmap = {}
        ramp = VelocityRamp(
            self.get_parameter('max_linear_accel').value,
            self.get_parameter('max_angular_accel').value,
            1.0 / self.get_parameter('control_rate_hz').value,
        )
        try:
            mode = goal.mode
            restore_costmap = self._enter_docking_costmap_mode()
            dynamic_target = bool(goal.target_pose.header.frame_id)
            map_pose = self.current_map_pose()
            if dynamic_target:
                target = self.pose_stamped_to_pose2d(goal.target_pose)
                if mode == 'DOCK_IN':
                    pose_a = map_pose
                    pose_b = target
                else:
                    pose_a = target
                    pose_b = map_pose
            else:
                station = self.stations[goal.station_id]
                pose_a = station['dock_start_A']
                pose_b = station['dock_final_B']
            direction = 1.0 if mode == 'DOCK_IN' else -1.0
            travel = math.hypot(pose_b.x - pose_a.x, pose_b.y - pose_a.y)
            yaw_ref = pose_a.yaw
            speed_param = 'dock_speed' if mode == 'DOCK_IN' else 'undock_speed'
            speed = abs(float(goal.max_speed)) if goal.max_speed > 0.0 else self.get_parameter(speed_param).value
            speed = min(speed, self.get_parameter(speed_param).value)

            dist_to_a = math.hypot(map_pose.x - pose_a.x, map_pose.y - pose_a.y)
            if not dynamic_target and mode == 'DOCK_IN' and dist_to_a > self.get_parameter('near_a_tolerance_m').value:
                raise RuntimeError(f'robot is {dist_to_a:.2f}m from A; ask Nav2 to return to A')

            self._align_yaw(goal_handle, yaw_ref, ramp)
            start = self.current_odom_pose()
            deadline = self.get_clock().now() + Duration(seconds=self.get_parameter('dock_timeout_sec').value)
            rate = self.create_rate(self.get_parameter('control_rate_hz').value)

            while rclpy.ok():
                if goal_handle.is_cancel_requested:
                    result.success = False
                    result.message = 'Dock goal canceled'
                    goal_handle.canceled()
                    return result
                if self.get_clock().now() > deadline:
                    raise RuntimeError('dock timeout')

                self._check_safety(allow_obstacle=(mode == 'UNDOCK_OUT'))
                now = self.current_odom_pose()
                dx = now.x - start.x
                dy = now.y - start.y
                along = direction * (math.cos(yaw_ref) * dx + math.sin(yaw_ref) * dy)
                lateral = -math.sin(yaw_ref) * dx + math.cos(yaw_ref) * dy
                remaining = travel - along
                yaw_error = normalize_angle(yaw_ref - now.yaw)
                if abs(yaw_error) > self.get_parameter('yaw_abort_rad').value:
                    raise RuntimeError(f'yaw error too large in dock corridor: {math.degrees(yaw_error):.1f}deg')
                if abs(lateral) > self.get_parameter('lateral_abort_m').value:
                    raise RuntimeError(f'lateral error too large: {lateral:.3f}m')
                if remaining <= self.get_parameter('goal_tolerance_m').value:
                    break

                w_cmd = max(
                    -self.get_parameter('max_angular_speed').value,
                    min(self.get_parameter('max_angular_speed').value, 0.45 * yaw_error - 0.25 * lateral),
                )
                v_cmd, w_cmd = ramp.step(direction * speed, w_cmd)
                twist = Twist()
                twist.linear.x = v_cmd
                twist.angular.z = w_cmd
                self.cmd_pub.publish(twist)
                self._feedback(goal_handle, 'DOCKING_IN' if mode == 'DOCK_IN' else 'UNDOCKING',
                               remaining, yaw_error, lateral)
                rate.sleep()

            self.publish_zero(12)
            result.success = True
            result.message = 'DOCKED/READY_TO_PICK' if mode == 'DOCK_IN' else 'UNDOCKED'
            goal_handle.succeed()
            return result
        except (RuntimeError, TransformException, KeyError) as exc:
            self.publish_zero(12)
            result.success = False
            result.message = str(exc)
            self.get_logger().error(f'Dock failed: {result.message}')
            goal_handle.abort()
            return result
        finally:
            self.publish_zero(5)
            self._restore_costmap_mode(restore_costmap)

    def _align_yaw(self, goal_handle, yaw_ref: float, ramp: VelocityRamp):
        tolerance = self.get_parameter('yaw_align_tolerance_rad').value
        timeout = self.get_clock().now() + Duration(seconds=12.0)
        rate = self.create_rate(self.get_parameter('control_rate_hz').value)
        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                raise RuntimeError('dock goal canceled during yaw align')
            self._check_safety()
            pose = self.current_odom_pose()
            yaw_error = normalize_angle(yaw_ref - pose.yaw)
            if abs(yaw_error) <= tolerance:
                self.publish_zero(4)
                ramp.reset()
                return
            if self.get_clock().now() > timeout:
                raise RuntimeError(f'align yaw timeout: {math.degrees(yaw_error):.1f}deg')
            w_target = max(-0.12, min(0.12, 0.7 * yaw_error))
            _, w_cmd = ramp.step(0.0, w_target)
            twist = Twist()
            twist.angular.z = w_cmd
            self.cmd_pub.publish(twist)
            self._feedback(goal_handle, 'ALIGN_YAW_AT_A', 0.0, yaw_error, 0.0)
            rate.sleep()


def main():
    rclpy.init()
    node = DockingServer()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.publish_zero(10)
        node.destroy_node()
        rclpy.shutdown()
