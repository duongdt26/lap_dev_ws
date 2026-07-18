"""ROS 2 magnetic-line station approach state machine.

Command topic (JSON, std_msgs/String):
  /magnetic_line/command
  {"command":"start", "request_id":"...", "workflow":"approach",
   "belt1_command":"load",
   "belt2_command":"unload", "target_x":1.0, "target_y":2.0,
   "target_yaw":0.0}

Status topic (JSON, std_msgs/String):
  /magnetic_line/status

The node publishes only ``/cmd_vel_line``.  It never opens the motor-driver or
STM32 ports; those remain owned by ros2_control and amr_stm32_bridge.
"""

from __future__ import annotations

import json
import math
import threading
import time
from enum import Enum, auto
from typing import Optional

import rclpy
from amr_stm32_interfaces.srv import RunBeltCommand
from geometry_msgs.msg import Twist
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from .control import (
    HorizontalMarkerDetector,
    MARKER_CLEAR_RPM,
    MagneticSensorBus,
    PDController,
    SEARCH_SPIN_RPM,
    TrackingMode,
    choose_sweep_direction,
    compute_home_reverse_recovery_command,
    compute_home_reverse_wheel_command,
    compute_home_tracking_measurement,
    compute_no_sensor_recovery_command,
    compute_pd_wheel_command,
    compute_pose_errors,
    compute_tracking_measurement,
    belt_command_at_marker,
    motor_rpms_to_twist,
    normalize_angle_rad,
    reached_sweep_limit,
)


class State(Enum):
    IDLE = auto()
    SETTLING = auto()
    SEARCH_LINE = auto()
    CAPTURE_LINE = auto()
    TRACKING = auto()
    RECOVER_LINE = auto()
    WAIT_BELT = auto()
    CLEAR_MARKER = auto()


class MagneticLineFollowerNode(Node):
    CAPTURE_CONFIRM_SAMPLES = 2
    CAPTURE_TIMEOUT_SEC = 0.70
    DUAL_ENTRY_CONFIRM_SAMPLES = 3
    LEADING_LOST_RECOVERY_SEC = 0.45

    def __init__(self) -> None:
        super().__init__('magnetic_line_follower_node')

        self.declare_parameter('port', '')
        self.declare_parameter('baudrate', 115200)
        self.declare_parameter('serial_timeout_sec', 0.10)
        self.declare_parameter('bus_gap_sec', 0.035)
        self.declare_parameter('front_sensor_id', 83)
        self.declare_parameter('rear_sensor_id', 86)
        self.declare_parameter('gear_ratio', 30.0)
        self.declare_parameter('wheel_radius_m', 0.09)
        self.declare_parameter('wheel_separation_m', 0.5703)
        self.declare_parameter('settle_time_sec', 0.5)
        self.declare_parameter('pose_timeout_sec', 1.0)
        self.declare_parameter('yaw_align_deadband_deg', 5.0)
        self.declare_parameter('lateral_deadband_m', 0.02)
        self.declare_parameter('max_search_yaw_deg', 90.0)
        self.declare_parameter('search_timeout_sec', 60.0)
        self.declare_parameter('marker_clear_timeout_sec', 3.0)
        self.declare_parameter('marker_clear_confirm_samples', 3)
        self.declare_parameter('belt_timeout_sec', 60.0)
        self.declare_parameter('belt1_timeout_sec', 120.0)
        self.declare_parameter('unload_side', 'LEFT')
        self.declare_parameter('sensor_fault_timeout_sec', 1.0)

        self._front_id = int(self.get_parameter('front_sensor_id').value)
        self._rear_id = int(self.get_parameter('rear_sensor_id').value)
        self._gear_ratio = float(self.get_parameter('gear_ratio').value)
        self._wheel_radius = float(self.get_parameter('wheel_radius_m').value)
        self._wheel_separation = float(
            self.get_parameter('wheel_separation_m').value)
        self._settle_time = float(self.get_parameter('settle_time_sec').value)
        self._pose_timeout = float(self.get_parameter('pose_timeout_sec').value)
        self._yaw_deadband = math.radians(float(
            self.get_parameter('yaw_align_deadband_deg').value))
        self._lateral_deadband = float(
            self.get_parameter('lateral_deadband_m').value)
        self._max_search_yaw = math.radians(float(
            self.get_parameter('max_search_yaw_deg').value))
        self._search_timeout = float(self.get_parameter('search_timeout_sec').value)
        self._marker_clear_timeout = float(
            self.get_parameter('marker_clear_timeout_sec').value)
        self._marker_clear_samples = int(
            self.get_parameter('marker_clear_confirm_samples').value)
        self._belt_timeout = float(self.get_parameter('belt_timeout_sec').value)
        self._belt1_timeout = float(
            self.get_parameter('belt1_timeout_sec').value)
        self._unload_side = str(
            self.get_parameter('unload_side').value).strip().upper() or 'LEFT'
        self._sensor_fault_timeout = float(
            self.get_parameter('sensor_fault_timeout_sec').value)

        self._bus = MagneticSensorBus(
            port=str(self.get_parameter('port').value),
            baudrate=int(self.get_parameter('baudrate').value),
            timeout_sec=float(self.get_parameter('serial_timeout_sec').value),
            bus_gap_sec=float(self.get_parameter('bus_gap_sec').value),
        )
        self._marker_detector = HorizontalMarkerDetector(
            (self._front_id, self._rear_id))
        self._controller = PDController()
        self._tf_buffer = Buffer(cache_time=Duration(seconds=10.0))
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self._cmd_pub = self.create_publisher(Twist, '/cmd_vel_line', 10)
        self._status_pub = self.create_publisher(String, '/magnetic_line/status', 10)
        self._io_group = ReentrantCallbackGroup()
        self._timer_group = MutuallyExclusiveCallbackGroup()
        self.create_subscription(
            String, '/magnetic_line/command', self._command_cb, 10,
            callback_group=self._io_group)
        self._belt_client = self.create_client(
            RunBeltCommand, '/run_belt_command', callback_group=self._io_group)
        self.create_timer(0.01, self._tick, callback_group=self._timer_group)

        self._lock = threading.RLock()
        self._state = State.IDLE
        self._active = False
        self._request_id = ''
        self._target_pose = (0.0, 0.0, 0.0)
        self._handoff_pose: Optional[tuple[float, float, float]] = None
        self._belt_commands = {1: 'load', 2: 'load'}
        self._workflow = 'approach'
        self._marker_index = 0
        self._completed_markers: set[int] = set()
        self._belt_future = None
        self._waiting_belt_id: Optional[int] = None
        self._waiting_belt_command: Optional[str] = None
        self._front_first = True
        self._state_started = time.monotonic()
        self._last_status_at = 0.0
        self._last_sensor_ok_at = time.monotonic()
        self._last_pose_ok_at = time.monotonic()
        self._search_started = time.monotonic()
        self._search_phase = 'align'
        self._first_sweep_direction = +1
        self._capture_count = 0
        self._dual_count = 0
        self._dual_enabled = False
        self._leading_lost_at: Optional[float] = None
        self._last_correction = 0.0
        self._last_mode = TrackingMode.NONE
        self._marker_clear_count = 0

        self.get_logger().info(
            'Magnetic line follower ready; motor output via /cmd_vel_line only')
        if not self._bus.port:
            self.get_logger().warn(
                'Chua cau hinh cong cam bien line tu; node se tu choi START')
        self._publish_status('idle', 'Line follower san sang')

    def _command_cb(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except (TypeError, ValueError) as exc:
            self._publish_status('error', f'JSON command khong hop le: {exc}', final=True)
            return

        command = str(data.get('command', '')).lower()
        request_id = str(data.get('request_id', '')).strip()
        if command == 'cancel':
            with self._lock:
                if self._active and (not request_id or request_id == self._request_id):
                    self._finish(False, 'Da huy line follower', 'cancelled')
            return
        if command != 'start':
            self._publish_status(
                'error', f'Command khong ho tro: {command}', final=True,
                request_id=request_id)
            return
        if not request_id:
            self._publish_status(
                'error', 'Thieu request_id', final=True, request_id=request_id)
            return

        try:
            target_pose = (
                float(data['target_x']),
                float(data['target_y']),
                float(data['target_yaw']),
            )
        except (KeyError, TypeError, ValueError):
            self._publish_status(
                'error', 'Approach Pose thieu target_x, target_y hoac target_yaw',
                final=True, request_id=request_id)
            return
        if not all(math.isfinite(value) for value in target_pose):
            self._publish_status(
                'error', 'Approach Pose co x, y hoac yaw khong hop le',
                final=True, request_id=request_id)
            return

        belt1_command = str(data.get('belt1_command', '')).strip().lower()
        belt2_command = str(data.get('belt2_command', '')).strip().lower()
        workflow = str(data.get('workflow', 'approach')).strip().lower()
        if workflow not in ('approach', 'home'):
            self._publish_status(
                'error', f'Workflow line tu khong hop le: {workflow}',
                final=True, request_id=request_id)
            return
        if workflow == 'home':
            belt1_command = 'none'
            belt2_command = 'none'
        valid_belt_commands = ('none', 'load', 'unload')
        if belt1_command not in valid_belt_commands or belt2_command not in (
            valid_belt_commands
        ):
            self._publish_status(
                'error',
                'Lenh bang tai phai la none/load/unload',
                final=True,
                request_id=request_id)
            return
        if (workflow == 'approach'
                and belt1_command == 'none' and belt2_command == 'none'):
            self._publish_status(
                'error', 'Approach Pose phai chon it nhat mot bang tai',
                final=True, request_id=request_id)
            return

        with self._lock:
            if self._active:
                self._publish_status(
                    'error', f'Node dang chay request {self._request_id}', final=True,
                    request_id=request_id)
                return
            if self._belt_future is not None and not self._belt_future.done():
                self._publish_status(
                    'error', 'Lenh STM32 truoc van dang chay; xe tiep tuc dung',
                    final=True, request_id=request_id)
                return

            if workflow == 'approach' and not self._belt_client.service_is_ready():
                self._publish_status(
                    'error', 'STM32 bridge /run_belt_command chua san sang',
                    final=True, request_id=request_id)
                return
            try:
                self._bus.open()
            except Exception as exc:
                self._publish_status(
                    'error', f'Khong mo duoc cam bien line tu: {exc}',
                    final=True, request_id=request_id)
                return

            self._request_id = request_id
            self._target_pose = target_pose
            self._handoff_pose = None
            self._workflow = workflow
            self._belt_commands = {1: belt1_command, 2: belt2_command}
            self._active = True
            self._state = State.SETTLING
            self._state_started = time.monotonic()
            self._marker_index = 0
            self._completed_markers.clear()
            self._waiting_belt_id = None
            self._waiting_belt_command = None
            self._belt_future = None
            self._capture_count = 0
            self._dual_count = 0
            self._dual_enabled = False
            self._leading_lost_at = None
            self._last_correction = 0.0
            self._last_mode = TrackingMode.NONE
            self._marker_clear_count = 0
            self._last_sensor_ok_at = time.monotonic()
            self._last_pose_ok_at = time.monotonic()
            self._marker_detector.reset()
            self._controller.reset()
            self._publish_zero()
            self._publish_status(
                'settling',
                f'Da den Approach Pose; dung {self._settle_time:.1f}s de lay pose that. '
                f'Setpoint x={target_pose[0]:.3f}, y={target_pose[1]:.3f}, '
                f'yaw={math.degrees(target_pose[2]):.1f}°; '
                f'workflow={workflow.upper()}; '
                f'BT1={belt1_command.upper()}, BT2={belt2_command.upper()}',
                extra={
                    'target_pose': self._pose_dict(target_pose),
                    'workflow': workflow,
                    'belt1_command': belt1_command,
                    'belt2_command': belt2_command,
                })

    @staticmethod
    def _pose_dict(pose: tuple[float, float, float]) -> dict:
        return {
            'x': pose[0],
            'y': pose[1],
            'yaw_rad': pose[2],
            'yaw_deg': math.degrees(pose[2]),
        }

    def _lookup_robot_pose(self) -> Optional[tuple[float, float, float]]:
        """Doc pose that map -> base_footprint, khong lay pose tu trinh duyet."""
        try:
            transform = self._tf_buffer.lookup_transform(
                'map',
                'base_footprint',
                Time(),
                timeout=Duration(seconds=0.05),
            )
        except TransformException:
            return None
        q = transform.transform.rotation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        return (
            transform.transform.translation.x,
            transform.transform.translation.y,
            yaw,
        )

    def _settle_tick(self, now: float) -> None:
        """Giu xe dung, sau do chup pose that tai thoi diem handoff Nav2 -> line."""
        self._publish_zero()
        elapsed = now - self._state_started
        if elapsed < self._settle_time:
            return
        actual_pose = self._lookup_robot_pose()
        if actual_pose is None:
            if elapsed >= self._settle_time + self._pose_timeout:
                self._finish(
                    False,
                    'Khong doc duoc TF map -> base_footprint sau khi Nav2 dung',
                    'error')
            return
        self._handoff_pose = actual_pose
        self._begin_yaw_search(actual_pose, now, 'Bat dau tim line')

    def _begin_yaw_search(
        self,
        actual_pose: tuple[float, float, float],
        now: float,
        reason: str,
    ) -> None:
        target_x, target_y, target_yaw = self._target_pose
        actual_x, actual_y, actual_yaw = actual_pose
        errors = compute_pose_errors(
            target_x,
            target_y,
            target_yaw,
            actual_x,
            actual_y,
            actual_yaw,
        )
        relative_yaw = normalize_angle_rad(actual_yaw - target_yaw)
        if abs(relative_yaw) > self._max_search_yaw:
            self._finish(
                False,
                f'Yaw that lech setpoint {math.degrees(relative_yaw):+.1f}°, '
                f'vuot gioi han ±{math.degrees(self._max_search_yaw):.0f}°',
                'error')
            return

        self._first_sweep_direction = choose_sweep_direction(
            errors.yaw_error_rad,
            errors.lateral_error_m,
            self._yaw_deadband,
            self._lateral_deadband,
        )
        self._search_phase = 'align'
        self._search_started = now
        self._last_pose_ok_at = now
        self._state = State.SEARCH_LINE
        self._state_started = now
        direction_text = (
            'trai' if self._first_sweep_direction > 0 else 'phai')
        message = (
            f'{reason}: pose that x={actual_x:.3f}, y={actual_y:.3f}, '
            f'yaw={math.degrees(actual_yaw):.1f}°; '
            f'sai so yaw={math.degrees(errors.yaw_error_rad):+.1f}°, '
            f'lech ngang={errors.lateral_error_m:+.3f}m; '
            f'uu tien quet {direction_text}')
        self._publish_status(
            'aligning',
            message,
            extra={
                'target_pose': self._pose_dict(self._target_pose),
                'actual_pose': self._pose_dict(actual_pose),
                'yaw_error_deg': math.degrees(errors.yaw_error_rad),
                'forward_error_m': errors.forward_error_m,
                'lateral_error_m': errors.lateral_error_m,
                'search_direction': direction_text,
                'max_search_yaw_deg': math.degrees(self._max_search_yaw),
            })

    def _read_both(self):
        order = (
            (self._front_id, self._rear_id)
            if self._front_first else (self._rear_id, self._front_id))
        self._front_first = not self._front_first
        values = {sensor_id: self._bus.read_sensor(sensor_id) for sensor_id in order}
        return values[self._front_id], values[self._rear_id]

    def _tick(self) -> None:
        with self._lock:
            now = time.monotonic()
            if not self._active:
                if self._belt_future is not None and self._belt_future.done():
                    self._belt_future = None
                if now - self._last_status_at >= 2.0:
                    self._publish_status('idle', 'Line follower san sang')
                return
            request_id = self._request_id

            if self._state is State.WAIT_BELT:
                self._poll_belt_future()
                return
            if self._state is State.SETTLING:
                self._settle_tick(now)
                return

        front, rear = self._read_both()

        with self._lock:
            if not self._active or request_id != self._request_id:
                return
            now = time.monotonic()
            required_sensor_ok = rear.ok if self._workflow == 'home' else (front.ok or rear.ok)
            if required_sensor_ok:
                self._last_sensor_ok_at = now
            elif now - self._last_sensor_ok_at >= self._sensor_fault_timeout:
                sensor_error = (
                    f'Mat giao tiep cam bien sau ID{self._rear_id}: {rear.error_text}'
                    if self._workflow == 'home'
                    else f'Mat giao tiep ca hai cam bien: '
                         f'ID{self._front_id}={front.error_text}; '
                         f'ID{self._rear_id}={rear.error_text}')
                self._finish(
                    False, sensor_error, 'error')
                return

            if self._state is State.SEARCH_LINE:
                leading = rear if self._workflow == 'home' else front
                self._search_tick(leading, now)
            elif self._state is State.CAPTURE_LINE:
                self._capture_tick(front, rear, now)
            elif self._state in (State.TRACKING, State.RECOVER_LINE):
                self._tracking_tick(front, rear, now)
            elif self._state is State.CLEAR_MARKER:
                self._clear_marker_tick(front, rear, now)

    def _search_tick(self, front, now: float) -> None:
        """Can yaw ngan nhat, sau do quet hai phia trong yaw_setpoint ±90°."""
        actual_pose = self._lookup_robot_pose()
        if actual_pose is None:
            self._publish_zero()
            if now - self._last_pose_ok_at >= self._pose_timeout:
                self._finish(False, 'Mat TF khi dang xoay tim line', 'error')
            return
        self._last_pose_ok_at = now

        target_yaw = self._target_pose[2]
        actual_yaw = actual_pose[2]
        relative_yaw = normalize_angle_rad(actual_yaw - target_yaw)

        leading = front
        # Home gọi hàm này với cảm biến sau; Approach gọi với cảm biến trước.
        if leading.detected:
            if abs(relative_yaw) > self._max_search_yaw:
                self._finish(
                    False,
                    f'ID{leading.slave_id} thay line tai yaw khong an toan '
                    f'{math.degrees(relative_yaw):+.1f}°',
                    'error')
                return
            self._publish_zero()
            self._state = State.CAPTURE_LINE
            self._state_started = now
            self._capture_count = 1
            self._publish_status(
                'capturing',
                f'ID{leading.slave_id} thay line tai yaw '
                f'{math.degrees(actual_yaw):.1f}°; dung va xac nhan 2 mau',
                extra={'actual_pose': self._pose_dict(actual_pose)})
            return

        if now - self._search_started >= self._search_timeout:
            self._finish(
                False, f'Khong tim thay line sau {self._search_timeout:.1f}s', 'error')
            return

        if self._search_phase == 'align':
            yaw_error = normalize_angle_rad(target_yaw - actual_yaw)
            if abs(yaw_error) <= self._yaw_deadband:
                self._publish_zero()
                self._search_phase = 'sweep_first'
                direction_text = (
                    'trai' if self._first_sweep_direction > 0 else 'phai')
                self._publish_status(
                    'searching',
                    f'Da gan yaw setpoint; quet {direction_text} truoc, '
                    f'toi da {math.degrees(self._max_search_yaw):.0f}°')
                return
            self._publish_spin(+1 if yaw_error > 0.0 else -1)
            return

        if self._search_phase == 'sweep_first':
            direction = self._first_sweep_direction
            reached_limit = reached_sweep_limit(
                relative_yaw, direction, self._max_search_yaw)
            if reached_limit:
                self._publish_zero()
                self._search_phase = 'sweep_second'
                second_text = 'phai' if direction > 0 else 'trai'
                self._publish_status(
                    'searching',
                    f'Khong co line o phia quet dau; doi sang quet {second_text} '
                    f'toi bien {math.degrees(self._max_search_yaw):.0f}° doi dien')
                return
            self._publish_spin(direction)
            return

        direction = -self._first_sweep_direction
        reached_limit = reached_sweep_limit(
            relative_yaw, direction, self._max_search_yaw)
        if reached_limit:
            self._finish(
                False,
                f'Da quet het yaw setpoint ±'
                f'{math.degrees(self._max_search_yaw):.0f}° nhung khong co line',
                'error')
            return
        self._publish_spin(direction)

    def _publish_spin(self, direction: int) -> None:
        """direction +1 = xoay trai; -1 = xoay phai."""
        sign = +1 if direction > 0 else -1
        self._publish_rpms(-sign * SEARCH_SPIN_RPM, sign * SEARCH_SPIN_RPM)

    def _restart_yaw_search(self, now: float, reason: str) -> None:
        actual_pose = self._lookup_robot_pose()
        if actual_pose is None:
            self._finish(False, f'{reason}; khong doc duoc TF de tim lai', 'error')
            return
        self._begin_yaw_search(actual_pose, now, reason)

    def _capture_tick(self, front, rear, now: float) -> None:
        leading = rear if self._workflow == 'home' else front
        if leading.detected:
            self._capture_count += 1
        else:
            self._capture_count = 0
        if self._capture_count >= self.CAPTURE_CONFIRM_SAMPLES:
            if self._workflow == 'home':
                measurement = compute_home_tracking_measurement(rear)
                self._controller.prime(measurement.control_error_mm, now)
            else:
                self._controller.prime(front.offset_mm, now)
            self._state = State.TRACKING
            self._state_started = now
            self._dual_count = 0 if self._workflow == 'home' else (1 if rear.detected else 0)
            direction = 'lui vao vi tri sac' if self._workflow == 'home' else 'tien vao tram'
            self._publish_status('tracking', f'Da khoa line; bat dau bam line {direction}')
            self._tracking_tick(front, rear, now)
            return
        if now - self._state_started >= self.CAPTURE_TIMEOUT_SEC:
            self._controller.reset()
            self._restart_yaw_search(now, 'Xac nhan line that bai; tim lai co gioi han')
            return
        self._publish_zero()

    def _tracking_tick(self, front, rear, now: float) -> None:
        if self._workflow == 'home':
            self._home_tracking_tick(rear, now)
            return

        # Xe đang tiến: chỉ cảm biến trước được đếm marker. Nếu dùng cả hai,
        # cùng một line ngang sẽ bị đếm lần nữa khi cảm biến sau đi qua.
        marker_front = self._marker_detector.observe(front)
        if marker_front[0]:
            self._handle_marker(marker_front[1], now)
            return

        if front.detected and rear.detected:
            self._dual_count += 1
        else:
            self._dual_count = 0
        self._dual_enabled = (
            front.detected and rear.detected
            and self._dual_count >= self.DUAL_ENTRY_CONFIRM_SAMPLES)
        measurement = compute_tracking_measurement(front, rear, self._dual_enabled)

        if measurement.mode in (TrackingMode.LEADING_ONLY, TrackingMode.DUAL):
            self._leading_lost_at = None
            self._state = State.TRACKING
            if measurement.mode is not self._last_mode:
                self._controller.reset_derivative(now)
            left, right, correction = compute_pd_wheel_command(
                self._controller, measurement, now)
            self._publish_rpms(left, right)
            self._last_correction = correction
            self._last_mode = measurement.mode
            return

        if self._leading_lost_at is None:
            self._leading_lost_at = now
            self._controller.reset_derivative(now)
        if now - self._leading_lost_at < self.LEADING_LOST_RECOVERY_SEC:
            self._state = State.RECOVER_LINE
            if measurement.mode is TrackingMode.TRAILING_RECOVERY:
                left, right, correction = compute_pd_wheel_command(
                    self._controller, measurement, now)
            else:
                left, right, correction = compute_no_sensor_recovery_command(
                    self._last_correction)
            self._publish_rpms(left, right)
            self._last_correction = correction
            self._last_mode = measurement.mode
            return

        self._publish_zero()
        self._controller.reset()
        self._dual_count = 0
        self._dual_enabled = False
        self._leading_lost_at = None
        self._last_correction = 0.0
        self._restart_yaw_search(now, 'Mat line; dung va tim lai co gioi han')

    def _home_tracking_tick(self, rear, now: float) -> None:
        marker_rear = self._marker_detector.observe(rear)
        if marker_rear[0]:
            self._publish_zero()
            self._marker_index = 1
            self._publish_status(
                'marker',
                f'Cam bien sau phat hien line ngang sac: {marker_rear[1]}',
                marker=1)
            self._finish(
                True,
                'Da lui toi line ngang Home; dung xe va bat dau sac',
                'success')
            return

        measurement = compute_home_tracking_measurement(rear)
        if measurement.mode is TrackingMode.LEADING_ONLY:
            self._leading_lost_at = None
            self._state = State.TRACKING
            left, right, correction = compute_home_reverse_wheel_command(
                self._controller, measurement, now)
            self._publish_rpms(left, right)
            self._last_correction = correction
            self._last_mode = measurement.mode
            return

        if self._leading_lost_at is None:
            self._leading_lost_at = now
            self._controller.reset_derivative(now)
        if now - self._leading_lost_at < self.LEADING_LOST_RECOVERY_SEC:
            self._state = State.RECOVER_LINE
            left, right, correction = compute_home_reverse_recovery_command(
                self._last_correction)
            self._publish_rpms(left, right)
            self._last_correction = correction
            self._last_mode = TrackingMode.NONE
            return

        self._publish_zero()
        self._controller.reset()
        self._leading_lost_at = None
        self._last_correction = 0.0
        self._restart_yaw_search(
            now, 'Mat line sau khi dang lui Home; dung va tim lai')

    def _handle_marker(self, reason: str, now: float) -> None:
        self._publish_zero()
        self._marker_index += 1
        marker = self._marker_index
        self._publish_status(
            'marker', f'Phat hien line ngang {marker}: {reason}', marker=marker)
        if marker >= 3:
            if marker == 3:
                if self._completed_markers == {1, 2}:
                    self._finish(
                        True,
                        'Da xu ly marker 1, marker 2 va den line ngang cuoi cung',
                        'success')
                else:
                    self._finish(
                        False,
                        f'Den marker 3 khi marker da xu ly={sorted(self._completed_markers)}',
                        'error')
            else:
                self._finish(False, f'Dem du line ngang bat thuong: {marker}', 'error')
            return

        belt_action = belt_command_at_marker(
            marker, self._belt_commands[1], self._belt_commands[2])
        if belt_action is not None:
            belt_id, command = belt_action
            self._start_belt_command(belt_id, command)
            return

        if self._belt_commands[marker] == 'none':
            self.get_logger().info(
                f'Line ngang {marker}: BT{marker}=NONE, bỏ qua không gửi STM32')
            self._completed_markers.add(marker)
            self._begin_marker_clear(
                f'Bo qua line ngang {marker}; BT{marker} khong co lenh')
            return

        self._finish(False, f'Khong co lenh hop le cho marker {marker}', 'error')

    def _start_belt_command(self, belt_id: int, command: str) -> None:
        request = RunBeltCommand.Request()
        request.belt_id = belt_id
        request.command = command
        request.side = self._unload_side if command == 'unload' else ''
        request.timeout_sec = (
            self._belt1_timeout if belt_id == 1 else self._belt_timeout)
        self.get_logger().info(
            f'Line ngang {self._marker_index}: gọi /run_belt_command '
            f'belt={belt_id}, command={command}, side={request.side or "-"}, '
            f'timeout={request.timeout_sec:.1f}s')
        self._belt_future = self._belt_client.call_async(request)
        self._waiting_belt_id = belt_id
        self._waiting_belt_command = command
        self._state = State.WAIT_BELT
        self._publish_status(
            'waiting_belt',
            f'Da dung tai line ngang {belt_id}; cho STM32 hoan thanh '
            f'{command.upper()} BT{belt_id}',
            marker=self._marker_index)

    def _poll_belt_future(self) -> None:
        self._publish_zero()
        if self._belt_future is None or not self._belt_future.done():
            return
        belt_id = self._waiting_belt_id
        command = self._waiting_belt_command or 'unknown'
        try:
            response = self._belt_future.result()
        except Exception as exc:
            self._finish(False, f'Loi service BT{belt_id}: {exc}', 'error')
            return
        if response is None or not response.success:
            message = response.message if response is not None else 'khong co response'
            self._finish(
                False, f'{command.upper()} BT{belt_id} that bai: {message}', 'error')
            return
        self._belt_future = None
        self._waiting_belt_id = None
        self._waiting_belt_command = None
        self._completed_markers.add(self._marker_index)
        self._begin_marker_clear(
            f'{command.upper()} BT{belt_id} xong; '
            f'tiep tuc qua line ngang {self._marker_index}')

    def _begin_marker_clear(self, message: str) -> None:
        self._state = State.CLEAR_MARKER
        self._state_started = time.monotonic()
        self._marker_clear_count = 0
        self._publish_status(
            'clearing_marker',
            message,
            marker=self._marker_index)

    def _clear_marker_tick(self, front, rear, now: float) -> None:
        del rear
        # Approach chỉ re-arm marker bằng cảm biến trước. Cảm biến sau tuyệt đối
        # không được tạo marker mới khi đi qua cùng vạch ngang vừa xử lý.
        marker_front = self._marker_detector.observe(front)[0]
        if not marker_front:
            self._marker_clear_count += 1
        else:
            self._marker_clear_count = 0
        if self._marker_clear_count >= self._marker_clear_samples:
            self._marker_detector.reset()
            self._controller.reset()
            if front.detected:
                self._controller.prime(front.offset_mm, now)
            self._dual_count = 0
            self._dual_enabled = False
            self._leading_lost_at = None
            self._last_correction = 0.0
            self._last_mode = TrackingMode.NONE
            self._state = State.TRACKING
            self._state_started = now
            self._publish_status(
                'tracking',
                f'Da qua line ngang {self._marker_index}; tiep tuc bam line',
                marker=self._marker_index)
            return
        if now - self._state_started >= self._marker_clear_timeout:
            self._finish(
                False,
                f'Khong thoat khoi line ngang {self._marker_index} sau '
                f'{self._marker_clear_timeout:.1f}s',
                'error')
            return
        # Di thang cham de thoat khoi be rong cua marker, khong dung offset marker
        # lam dau vao PD.
        self._publish_rpms(MARKER_CLEAR_RPM, MARKER_CLEAR_RPM)

    def _publish_rpms(self, left_rpm: float, right_rpm: float) -> None:
        linear, angular = motor_rpms_to_twist(
            left_rpm, right_rpm, self._gear_ratio,
            self._wheel_radius, self._wheel_separation)
        msg = Twist()
        msg.linear.x = linear
        msg.angular.z = angular
        self._cmd_pub.publish(msg)

    def _publish_zero(self) -> None:
        self._cmd_pub.publish(Twist())

    def _finish(self, success: bool, message: str, state: str) -> None:
        self._publish_zero()
        request_id = self._request_id
        marker = self._marker_index
        self._active = False
        self._state = State.IDLE
        self._controller.reset()
        self._publish_status(
            state, message, final=True, success=success,
            request_id=request_id, marker=marker)
        self.get_logger().info(f'{state}: {message}')

    def _publish_status(
        self,
        state: str,
        message: str,
        *,
        final: bool = False,
        success: Optional[bool] = None,
        request_id: Optional[str] = None,
        marker: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> None:
        payload = {
            'request_id': self._request_id if request_id is None else request_id,
            'workflow': self._workflow,
            'state': state,
            'message': message,
            'marker': self._marker_index if marker is None else marker,
            'final': final,
        }
        if success is not None:
            payload['success'] = success
        if extra:
            payload.update(extra)
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._status_pub.publish(msg)
        self._last_status_at = time.monotonic()

    def destroy_node(self):
        with self._lock:
            self._publish_zero()
            self._bus.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MagneticLineFollowerNode()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
