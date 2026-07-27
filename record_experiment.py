#!/usr/bin/env python3
"""Record AMR experiment data from ROS 2 topics to CSV without controlling it.

Typical rates:
  * 50 Hz: wheel setpoint/actual response and PID experiments.
  * 20 Hz: robot velocity, pose and heading experiments (recommended default).
  * 10-20 Hz: Nav2 trajectory experiments.

Run after sourcing ROS 2 and this workspace. Stop safely with Ctrl+C.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import signal
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, TextIO, Tuple

import rclpy
from action_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import PoseStamped, Quaternion, Twist
from nav_msgs.msg import Odometry, Path as PathMessage
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import Imu, JointState
from tf2_ros import Buffer, TransformException, TransformListener


# CONFIG: verified from this workspace's launch/config/source files.
TOPICS: Dict[str, Optional[str]] = {
    "wheel_actual": "/joint_states",
    "cmd_vel": "/diff_cont/cmd_vel_unstamped",  # output of twist_mux
    "raw_odometry": "/diff_cont/odom",          # before EKF
    "filtered_odometry": "/odometry/filtered",  # after EKF
    "imu": "/imu/data",
    "global_path": "/plan",
    "local_path": None,  # no project-defined local-path topic was found
    "goal": "/goal_pose",
    "nav_status": "/navigate_to_pose/_action/status",
    "manual_cmd_vel": "/cmd_vel_key",  # highest-priority normal twist_mux input
}

LEFT_JOINT = "left_wheel_joint"
RIGHT_JOINT = "right_wheel_joint"
WHEEL_SEPARATION_M = 0.5703
WHEEL_RADIUS_M = 0.09
BASE_FRAME = "base_footprint"
MAP_FRAME = "map"
ODOM_FRAME = "odom"
MAX_LINEAR_MPS = 0.8
MAX_ANGULAR_RAD_S = 3.0
MANUAL_PUBLISH_HZ = 20.0
NAN = float("nan")

CSV_COLUMNS = [
    "timestamp_ros",
    "time_sec",
    "left_wheel_setpoint",
    "left_wheel_actual",
    "right_wheel_setpoint",
    "right_wheel_actual",
    "cmd_linear_x",
    "actual_linear_x",
    "cmd_angular_z",
    "actual_angular_z",
    "odom_x",
    "odom_y",
    "odom_yaw",
    "odom_source",
    "odom_capture_mode",
    "raw_actual_linear_x",
    "raw_actual_angular_z",
    "raw_odom_x",
    "raw_odom_y",
    "raw_odom_yaw",
    "filtered_actual_linear_x",
    "filtered_actual_angular_z",
    "filtered_odom_x",
    "filtered_odom_y",
    "filtered_odom_yaw",
    "map_x",
    "map_y",
    "map_yaw",
    "imu_yaw",
    "imu_angular_z",
    "goal_x",
    "goal_y",
    "goal_yaw",
    "nav_status",
    "wheel_data_age_sec",
    "cmd_vel_age_sec",
    "odom_age_sec",
    "raw_odom_age_sec",
    "filtered_odom_age_sec",
    "imu_age_sec",
    "map_pose_age_sec",
    "manual_mode",
    "manual_repeat_index",
    "manual_repeat_total",
    "manual_step_index",
    "manual_step_total",
    "manual_step_elapsed_sec",
    "manual_step_remaining_sec",
    "manual_left_target_mps",
    "manual_right_target_mps",
    "note",
]

PATH_COLUMNS = [
    "path_id", "point_index", "x", "y", "yaw", "frame_id", "received_time_sec"
]

STATUS_NAMES = {
    GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
    GoalStatus.STATUS_ACCEPTED: "ACCEPTED",
    GoalStatus.STATUS_EXECUTING: "EXECUTING",
    GoalStatus.STATUS_CANCELING: "CANCELING",
    GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
    GoalStatus.STATUS_CANCELED: "CANCELED",
    GoalStatus.STATUS_ABORTED: "ABORTED",
}

SOURCE_TOPICS = {
    "wheel": TOPICS["wheel_actual"],
    "cmd_vel": TOPICS["cmd_vel"],
    "raw_odom": TOPICS["raw_odometry"],
    "filtered_odom": TOPICS["filtered_odometry"],
    "imu": TOPICS["imu"],
    "goal": TOPICS["goal"],
    "nav_status": TOPICS["nav_status"],
    "global_path": TOPICS["global_path"],
    "map_pose": f"TF {MAP_FRAME} -> {BASE_FRAME}",
    "odom_tf": f"TF {ODOM_FRAME} -> {BASE_FRAME}",
}


def normalize_angle(angle: float) -> float:
    """Normalize an angle to [-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def quaternion_to_yaw(q: Quaternion) -> float:
    """Convert a ROS quaternion to normalized yaw in radians."""
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return normalize_angle(math.atan2(siny_cosp, cosy_cosp))


def twist_to_wheel_setpoints(linear_x: float, angular_z: float) -> Tuple[float, float]:
    """Convert differential-drive Twist to nominal left/right wheel rad/s."""
    half_track = WHEEL_SEPARATION_M / 2.0
    left = (linear_x - angular_z * half_track) / WHEEL_RADIUS_M
    right = (linear_x + angular_z * half_track) / WHEEL_RADIUS_M
    return left, right


def wheel_mps_to_twist(left_mps: float, right_mps: float) -> Tuple[float, float]:
    """Convert physical left/right wheel linear speeds to robot Twist."""
    linear_x = (left_mps + right_mps) / 2.0
    angular_z = (right_mps - left_mps) / WHEEL_SEPARATION_M
    return linear_x, angular_z


def age_or_nan(now_monotonic: float, received_at: Optional[float]) -> float:
    return NAN if received_at is None else max(0.0, now_monotonic - received_at)


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return cleaned or "danhgia"


def unique_output_paths(output_dir: Path, requested_name: Optional[str]) -> Tuple[Path, Path]:
    """Return prefixN.csv and its paired path file, with monotonically increasing N."""
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = safe_name(requested_name) if requested_name else "danhgia"
    pattern = re.compile(rf"^{re.escape(prefix)}([0-9]+)\.csv$")
    highest = 0
    for existing in output_dir.glob(f"{prefix}*.csv"):
        match = pattern.fullmatch(existing.name)
        if match:
            highest = max(highest, int(match.group(1)))
    sequence = highest + 1
    while True:
        candidate = f"{prefix}{sequence}"
        main_path = output_dir / f"{candidate}.csv"
        path_path = output_dir / f"{candidate}_global_path.csv"
        if not main_path.exists() and not path_path.exists():
            return main_path.resolve(), path_path.resolve()
        sequence += 1


class ExperimentRecorder(Node):
    """Lightweight latest-value snapshot recorder."""

    def __init__(
        self,
        rate_hz: float,
        main_path: Path,
        global_path: Path,
        note: str,
        use_sim_time: bool,
        manual_control: bool,
    ) -> None:
        super().__init__(
            "record_experiment",
            parameter_overrides=[
                Parameter("use_sim_time", Parameter.Type.BOOL, use_sim_time)
            ],
        )
        self._lock = threading.Lock()
        self._start_monotonic = time.monotonic()
        self._recording_active = not manual_control
        self._recording_start_monotonic: Optional[float] = (
            self._start_monotonic if not manual_control else None
        )
        self._recording_duration_sec = 0.0
        self._last_flush = self._start_monotonic
        self._note = note
        self._rows = 0
        self._path_id = 0
        self._tf_errors = 0
        self._closed = False
        self._manual_control = manual_control
        self._manual_left_rad_s = 0.0
        self._manual_right_rad_s = 0.0
        self._manual_running = False
        self._manual_mode = "stopped"
        self._use_filtered_odom = False
        self._record_both_odom = False
        self._profile_steps: List[Tuple[float, float, float]] = []
        self._profile_repeats = 0
        self._profile_repeat_index = -1
        self._profile_step_index = -1
        self._profile_step_start_sec = NAN
        self._profile_step_deadline_sec = NAN
        self._stale_warned: Dict[str, bool] = {}
        self._last_path_signature: Optional[Tuple[Any, ...]] = None

        self.main_path = main_path
        self.global_path = global_path
        self._main_file: TextIO = main_path.open("x", newline="", encoding="utf-8")
        self._path_file: TextIO = global_path.open("x", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._main_file, fieldnames=CSV_COLUMNS)
        self._path_writer = csv.writer(self._path_file)
        self._writer.writeheader()
        self._path_writer.writerow(PATH_COLUMNS)

        self._values: Dict[str, Any] = {
            "left_wheel_actual": NAN,
            "right_wheel_actual": NAN,
            "cmd_linear_x": NAN,
            "cmd_angular_z": NAN,
            "left_wheel_setpoint": NAN,
            "right_wheel_setpoint": NAN,
            "actual_linear_x": NAN,
            "actual_angular_z": NAN,
            "odom_x": NAN,
            "odom_y": NAN,
            "odom_yaw": NAN,
            "raw_actual_linear_x": NAN,
            "raw_actual_angular_z": NAN,
            "raw_odom_x": NAN,
            "raw_odom_y": NAN,
            "raw_odom_yaw": NAN,
            "filtered_actual_linear_x": NAN,
            "filtered_actual_angular_z": NAN,
            "filtered_odom_x": NAN,
            "filtered_odom_y": NAN,
            "filtered_odom_yaw": NAN,
            "imu_yaw": NAN,
            "imu_angular_z": NAN,
            "goal_x": NAN,
            "goal_y": NAN,
            "goal_yaw": NAN,
            "nav_status": "",
        }
        self._received_at: Dict[str, Optional[float]] = {
            "wheel": None,
            "cmd_vel": None,
            "raw_odom": None,
            "filtered_odom": None,
            "imu": None,
            "goal": None,
            "nav_status": None,
            "global_path": None,
            "map_pose": None,
            "odom_tf": None,
        }
        self._pending_paths: Deque[Tuple[int, float, str, List[Tuple[float, float, float]]]] = deque()

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self.create_subscription(JointState, TOPICS["wheel_actual"], self._on_wheels, 50)
        self.create_subscription(Twist, TOPICS["cmd_vel"], self._on_cmd_vel, 50)
        self.create_subscription(
            Odometry, TOPICS["raw_odometry"], self._on_raw_odom, 50
        )
        self.create_subscription(
            Odometry, TOPICS["filtered_odometry"], self._on_filtered_odom, 50
        )
        self.create_subscription(Imu, TOPICS["imu"], self._on_imu, 50)
        self.create_subscription(PathMessage, TOPICS["global_path"], self._on_global_path, 10)
        self.create_subscription(PoseStamped, TOPICS["goal"], self._on_goal, 10)
        self.create_subscription(
            GoalStatusArray, TOPICS["nav_status"], self._on_nav_status, 10
        )
        self._timer = self.create_timer(1.0 / rate_hz, self._snapshot)
        self._manual_publisher = None
        self._manual_timer = None
        if manual_control:
            self._manual_publisher = self.create_publisher(
                Twist, TOPICS["manual_cmd_vel"], 10
            )
            self._manual_timer = self.create_timer(
                1.0 / MANUAL_PUBLISH_HZ, self._publish_manual_command
            )
        self.get_logger().info(
            f"Recording at {rate_hz:g} Hz -> {self.main_path} "
            f"(manual_control={manual_control}, use_sim_time={use_sim_time})"
        )
        if manual_control:
            self.get_logger().warning(
                "MANUAL CONTROL ENABLED on /cmd_vel_key. Stop/cancel Nav2 before "
                "manual testing. Zero velocity is published until RUN is confirmed."
            )

    def set_manual_wheel_speeds(self, left_rad_s: float, right_rad_s: float) -> None:
        """Apply validated wheel setpoints; publishing continues until STOP."""
        linear_x = (left_rad_s + right_rad_s) * WHEEL_RADIUS_M / 2.0
        angular_z = (right_rad_s - left_rad_s) * WHEEL_RADIUS_M / WHEEL_SEPARATION_M
        if abs(linear_x) > MAX_LINEAR_MPS + 1e-9:
            raise ValueError(
                f"linear velocity {linear_x:.3f} m/s exceeds {MAX_LINEAR_MPS:.3f} m/s"
            )
        if abs(angular_z) > MAX_ANGULAR_RAD_S + 1e-9:
            raise ValueError(
                f"angular velocity {angular_z:.3f} rad/s exceeds "
                f"{MAX_ANGULAR_RAD_S:.3f} rad/s"
            )
        self._begin_recording()
        with self._lock:
            self._manual_left_rad_s = left_rad_s
            self._manual_right_rad_s = right_rad_s
            self._manual_running = True
            self._manual_mode = "direct"
            self._profile_steps = []
            self._profile_repeat_index = -1
            self._profile_step_index = -1
        self.get_logger().info(
            f"Manual RUN: left={left_rad_s:.3f}, right={right_rad_s:.3f} rad/s "
            f"-> linear.x={linear_x:.3f} m/s, angular.z={angular_z:.3f} rad/s"
        )

    def start_manual_profile(
        self,
        steps: Sequence[Tuple[float, float, float]],
        repeats: int,
    ) -> None:
        """Run timed (duration, left m/s, right m/s) steps using the ROS clock."""
        if repeats < 1:
            raise ValueError("Số lần lặp profile phải từ 1 trở lên")
        if not steps:
            raise ValueError("Profile phải có ít nhất một bước")

        validated: List[Tuple[float, float, float]] = []
        for index, (duration, left_mps, right_mps) in enumerate(steps, start=1):
            if not all(math.isfinite(value) for value in (duration, left_mps, right_mps)):
                raise ValueError(f"Bước {index}: dữ liệu phải là số hữu hạn")
            if duration <= 0.0:
                raise ValueError(f"Bước {index}: thời gian phải lớn hơn 0 giây")
            linear_x, angular_z = wheel_mps_to_twist(left_mps, right_mps)
            if abs(linear_x) > MAX_LINEAR_MPS + 1e-9:
                raise ValueError(
                    f"Bước {index}: linear.x={linear_x:.3f} m/s vượt "
                    f"{MAX_LINEAR_MPS:.3f} m/s"
                )
            if abs(angular_z) > MAX_ANGULAR_RAD_S + 1e-9:
                raise ValueError(
                    f"Bước {index}: angular.z={angular_z:.3f} rad/s vượt "
                    f"{MAX_ANGULAR_RAD_S:.3f} rad/s"
                )
            validated.append((duration, left_mps, right_mps))

        now_sec = self.get_clock().now().nanoseconds / 1e9
        duration, left_mps, right_mps = validated[0]
        self._begin_recording()
        with self._lock:
            self._profile_steps = validated
            self._profile_repeats = repeats
            self._profile_repeat_index = 0
            self._profile_step_index = 0
            self._profile_step_start_sec = now_sec
            self._profile_step_deadline_sec = now_sec + duration
            self._manual_left_rad_s = left_mps / WHEEL_RADIUS_M
            self._manual_right_rad_s = right_mps / WHEEL_RADIUS_M
            self._manual_running = True
            self._manual_mode = "profile"
        total_duration = repeats * sum(item[0] for item in validated)
        self.get_logger().info(
            f"Manual PROFILE start: {len(validated)} steps x {repeats} repeat(s), "
            f"total={total_duration:.3f} s"
        )

    def stop_manual_control(self) -> None:
        """Latch manual command at zero and publish an immediate stop."""
        if not self._manual_control:
            return
        with self._lock:
            self._manual_left_rad_s = 0.0
            self._manual_right_rad_s = 0.0
            self._manual_running = False
            self._manual_mode = "stopped"
            self._profile_steps = []
            self._profile_repeat_index = -1
            self._profile_step_index = -1
            self._pause_recording_locked()
        self._publish_manual_command()
        self.get_logger().info("Manual STOP: publishing zero velocity continuously")

    def _publish_manual_command(self) -> None:
        if self._manual_publisher is None:
            return
        self._advance_manual_profile()
        with self._lock:
            left = self._manual_left_rad_s if self._manual_running else 0.0
            right = self._manual_right_rad_s if self._manual_running else 0.0
        command = Twist()
        command.linear.x = (left + right) * WHEEL_RADIUS_M / 2.0
        command.angular.z = (right - left) * WHEEL_RADIUS_M / WHEEL_SEPARATION_M
        self._manual_publisher.publish(command)

    def _advance_manual_profile(self) -> None:
        """Advance all elapsed profile boundaries without accumulating timer drift."""
        now_sec = self.get_clock().now().nanoseconds / 1e9
        completed = False
        with self._lock:
            while (
                self._manual_mode == "profile"
                and now_sec >= self._profile_step_deadline_sec
            ):
                next_step = self._profile_step_index + 1
                next_repeat = self._profile_repeat_index
                if next_step >= len(self._profile_steps):
                    next_step = 0
                    next_repeat += 1
                if next_repeat >= self._profile_repeats:
                    self._manual_running = False
                    self._manual_mode = "stopped"
                    self._manual_left_rad_s = 0.0
                    self._manual_right_rad_s = 0.0
                    self._profile_repeat_index = -1
                    self._profile_step_index = -1
                    self._pause_recording_locked()
                    completed = True
                    break

                start_sec = self._profile_step_deadline_sec
                duration, left_mps, right_mps = self._profile_steps[next_step]
                self._profile_repeat_index = next_repeat
                self._profile_step_index = next_step
                self._profile_step_start_sec = start_sec
                self._profile_step_deadline_sec = start_sec + duration
                self._manual_left_rad_s = left_mps / WHEEL_RADIUS_M
                self._manual_right_rad_s = right_mps / WHEEL_RADIUS_M
        if completed:
            self.get_logger().info("Manual PROFILE completed; publishing zero velocity")

    def manual_state(self) -> Dict[str, Any]:
        """Return a GUI/CSV-safe snapshot of manual control state."""
        now_sec = self.get_clock().now().nanoseconds / 1e9
        with self._lock:
            profile_active = self._manual_mode == "profile"
            return {
                "running": self._manual_running,
                "recording_active": self._recording_active,
                "recording_started": self._recording_start_monotonic is not None,
                "mode": self._manual_mode,
                "left_rad_s": self._manual_left_rad_s,
                "right_rad_s": self._manual_right_rad_s,
                "left_target_mps": self._manual_left_rad_s * WHEEL_RADIUS_M,
                "right_target_mps": self._manual_right_rad_s * WHEEL_RADIUS_M,
                "actual_left_rad_s": float(self._values["left_wheel_actual"]),
                "actual_right_rad_s": float(self._values["right_wheel_actual"]),
                "repeat_index": self._profile_repeat_index + 1 if profile_active else NAN,
                "repeat_total": self._profile_repeats if profile_active else NAN,
                "step_index": self._profile_step_index + 1 if profile_active else NAN,
                "step_total": len(self._profile_steps) if profile_active else NAN,
                "step_elapsed_sec": (
                    max(0.0, now_sec - self._profile_step_start_sec)
                    if profile_active else NAN
                ),
                "step_remaining_sec": (
                    max(0.0, self._profile_step_deadline_sec - now_sec)
                    if profile_active else NAN
                ),
            }

    def _begin_recording(self) -> None:
        """Start CSV time on the first GUI RUN/PROFILE action."""
        now_monotonic = time.monotonic()
        with self._lock:
            if self._recording_start_monotonic is None:
                self._recording_start_monotonic = now_monotonic
                self._recording_duration_sec = 0.0
            self._recording_active = True

    def _pause_recording_locked(self) -> None:
        """Pause row creation; caller must hold self._lock."""
        if self._recording_active and self._recording_start_monotonic is not None:
            self._recording_duration_sec = max(
                self._recording_duration_sec,
                time.monotonic() - self._recording_start_monotonic,
            )
        self._recording_active = False

    def _on_wheels(self, msg: JointState) -> None:
        indices = {name: index for index, name in enumerate(msg.name)}
        left_index = indices.get(LEFT_JOINT)
        right_index = indices.get(RIGHT_JOINT)
        if left_index is None or right_index is None:
            return
        if left_index >= len(msg.velocity) or right_index >= len(msg.velocity):
            return
        with self._lock:
            self._values["left_wheel_actual"] = float(msg.velocity[left_index])
            self._values["right_wheel_actual"] = float(msg.velocity[right_index])
            self._received_at["wheel"] = time.monotonic()

    def _on_cmd_vel(self, msg: Twist) -> None:
        linear_x = float(msg.linear.x)
        angular_z = float(msg.angular.z)
        left, right = twist_to_wheel_setpoints(linear_x, angular_z)
        with self._lock:
            self._values["cmd_linear_x"] = linear_x
            self._values["cmd_angular_z"] = angular_z
            self._values["left_wheel_setpoint"] = left
            self._values["right_wheel_setpoint"] = right
            self._received_at["cmd_vel"] = time.monotonic()

    def set_use_filtered_odom(self, enabled: bool) -> None:
        """Select which odometry source feeds the legacy/main odom columns."""
        prefix = "filtered" if enabled else "raw"
        with self._lock:
            self._use_filtered_odom = enabled
            self._values["actual_linear_x"] = self._values[f"{prefix}_actual_linear_x"]
            self._values["actual_angular_z"] = self._values[f"{prefix}_actual_angular_z"]
            self._values["odom_x"] = self._values[f"{prefix}_odom_x"]
            self._values["odom_y"] = self._values[f"{prefix}_odom_y"]
            self._values["odom_yaw"] = self._values[f"{prefix}_odom_yaw"]
        self.get_logger().info(
            "Primary odometry columns now use "
            + ("AFTER EKF (/odometry/filtered)" if enabled else "BEFORE EKF (/diff_cont/odom)")
        )

    def set_record_both_odom(self, enabled: bool) -> None:
        """Control whether each CSV snapshot exposes both raw and filtered odometry."""
        with self._lock:
            self._record_both_odom = enabled
        self.get_logger().info(
            "Odometry CSV capture: "
            + ("BOTH before+after EKF" if enabled else "selected source only")
        )

    def _update_odom(self, msg: Odometry, prefix: str, received_key: str) -> None:
        pose = msg.pose.pose
        twist = msg.twist.twist
        linear_x = float(twist.linear.x)
        angular_z = float(twist.angular.z)
        x = float(pose.position.x)
        y = float(pose.position.y)
        yaw = quaternion_to_yaw(pose.orientation)
        with self._lock:
            self._values[f"{prefix}_actual_linear_x"] = linear_x
            self._values[f"{prefix}_actual_angular_z"] = angular_z
            self._values[f"{prefix}_odom_x"] = x
            self._values[f"{prefix}_odom_y"] = y
            self._values[f"{prefix}_odom_yaw"] = yaw
            selected = self._use_filtered_odom == (prefix == "filtered")
            if selected:
                self._values["actual_linear_x"] = linear_x
                self._values["actual_angular_z"] = angular_z
                self._values["odom_x"] = x
                self._values["odom_y"] = y
                self._values["odom_yaw"] = yaw
            self._received_at[received_key] = time.monotonic()

    def _on_raw_odom(self, msg: Odometry) -> None:
        self._update_odom(msg, "raw", "raw_odom")

    def _on_filtered_odom(self, msg: Odometry) -> None:
        self._update_odom(msg, "filtered", "filtered_odom")

    def _on_imu(self, msg: Imu) -> None:
        # The production driver sets orientation_covariance[0] = -1 (no orientation).
        imu_yaw = NAN
        # Gazebo/rosidl may expose fixed-size arrays as numpy.ndarray. Never use
        # their truth value (``if not array``), which is ambiguous for >1 item.
        if len(msg.orientation_covariance) == 0 or msg.orientation_covariance[0] >= 0.0:
            imu_yaw = quaternion_to_yaw(msg.orientation)
        with self._lock:
            self._values["imu_yaw"] = imu_yaw
            self._values["imu_angular_z"] = float(msg.angular_velocity.z)
            self._received_at["imu"] = time.monotonic()

    def _on_goal(self, msg: PoseStamped) -> None:
        with self._lock:
            self._values["goal_x"] = float(msg.pose.position.x)
            self._values["goal_y"] = float(msg.pose.position.y)
            self._values["goal_yaw"] = quaternion_to_yaw(msg.pose.orientation)
            self._received_at["goal"] = time.monotonic()

    def _on_nav_status(self, msg: GoalStatusArray) -> None:
        if not msg.status_list:
            return
        latest = max(
            msg.status_list,
            key=lambda item: (
                item.goal_info.stamp.sec,
                item.goal_info.stamp.nanosec,
            ),
        )
        with self._lock:
            self._values["nav_status"] = STATUS_NAMES.get(
                int(latest.status), f"STATUS_{int(latest.status)}"
            )
            self._received_at["nav_status"] = time.monotonic()

    def _on_global_path(self, msg: PathMessage) -> None:
        points = [
            (
                float(item.pose.position.x),
                float(item.pose.position.y),
                quaternion_to_yaw(item.pose.orientation),
            )
            for item in msg.poses
        ]
        signature: Tuple[Any, ...] = (
            msg.header.frame_id,
            tuple((round(x, 9), round(y, 9), round(yaw, 9)) for x, y, yaw in points),
        )
        received = time.monotonic()
        with self._lock:
            self._received_at["global_path"] = received
            if not self._recording_active:
                return
            if signature == self._last_path_signature:
                return
            self._last_path_signature = signature
            self._path_id += 1
            self._pending_paths.append(
                (
                    self._path_id,
                    received - (self._recording_start_monotonic or received),
                    msg.header.frame_id,
                    points,
                )
            )

    def _lookup_pose(self, target_frame: str) -> Optional[Tuple[float, float, float]]:
        try:
            transform = self._tf_buffer.lookup_transform(
                target_frame,
                BASE_FRAME,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.0),
            )
            translation = transform.transform.translation
            return (
                float(translation.x),
                float(translation.y),
                quaternion_to_yaw(transform.transform.rotation),
            )
        except TransformException:
            self._tf_errors += 1
            if self._tf_errors == 1 or self._tf_errors % 200 == 0:
                self.get_logger().warning(
                    f"TF {target_frame} -> {BASE_FRAME} unavailable "
                    f"(error count: {self._tf_errors})"
                )
            return None

    def _warn_if_stale(self, group: str, age: float) -> None:
        if math.isnan(age):
            return
        if age > 0.5 and not self._stale_warned.get(group, False):
            self.get_logger().warning(f"{group} data is stale ({age:.3f} s old); continuing")
            self._stale_warned[group] = True
        elif age <= 0.5:
            self._stale_warned[group] = False

    def _write_pending_paths(self) -> None:
        with self._lock:
            pending = list(self._pending_paths)
            self._pending_paths.clear()
        for path_id, received_time, frame_id, points in pending:
            for index, (x, y, yaw) in enumerate(points):
                self._path_writer.writerow(
                    [path_id, index, x, y, yaw, frame_id, received_time]
                )

    def _snapshot(self) -> None:
        if self._manual_control:
            # End a timed profile before deciding whether another row is allowed.
            self._advance_manual_profile()
        now_monotonic = time.monotonic()
        with self._lock:
            if not self._recording_active or self._recording_start_monotonic is None:
                return
            recording_start = self._recording_start_monotonic
        ros_now = self.get_clock().now().nanoseconds / 1e9
        map_pose = self._lookup_pose(MAP_FRAME)
        odom_tf = self._lookup_pose(ODOM_FRAME)

        with self._lock:
            if map_pose is not None:
                self._received_at["map_pose"] = now_monotonic
            if odom_tf is not None:
                self._received_at["odom_tf"] = now_monotonic
            values = dict(self._values)
            received = dict(self._received_at)
            use_filtered_odom = self._use_filtered_odom
            record_both_odom = self._record_both_odom

        selected_odom_key = "filtered_odom" if use_filtered_odom else "raw_odom"
        ages = {
            "wheel_data_age_sec": age_or_nan(now_monotonic, received["wheel"]),
            "cmd_vel_age_sec": age_or_nan(now_monotonic, received["cmd_vel"]),
            "odom_age_sec": age_or_nan(now_monotonic, received[selected_odom_key]),
            "raw_odom_age_sec": age_or_nan(now_monotonic, received["raw_odom"]),
            "filtered_odom_age_sec": age_or_nan(
                now_monotonic, received["filtered_odom"]
            ),
            "imu_age_sec": age_or_nan(now_monotonic, received["imu"]),
            "map_pose_age_sec": age_or_nan(now_monotonic, received["map_pose"]),
        }
        for column, age in ages.items():
            self._warn_if_stale(column.removesuffix("_age_sec"), age)

        row: Dict[str, Any] = {column: NAN for column in CSV_COLUMNS}
        row.update(values)
        row.update(ages)
        row["timestamp_ros"] = ros_now
        row["time_sec"] = now_monotonic - recording_start
        row["odom_source"] = "after_ekf" if use_filtered_odom else "before_ekf"
        row["odom_capture_mode"] = "both" if record_both_odom else "selected_only"
        if not record_both_odom:
            hidden_prefix = "raw" if use_filtered_odom else "filtered"
            for suffix in (
                "actual_linear_x",
                "actual_angular_z",
                "odom_x",
                "odom_y",
                "odom_yaw",
            ):
                row[f"{hidden_prefix}_{suffix}"] = NAN
            row[f"{hidden_prefix}_odom_age_sec"] = NAN
        row["note"] = self._note
        manual = self.manual_state()
        row["manual_mode"] = manual["mode"]
        row["manual_repeat_index"] = manual["repeat_index"]
        row["manual_repeat_total"] = manual["repeat_total"]
        row["manual_step_index"] = manual["step_index"]
        row["manual_step_total"] = manual["step_total"]
        row["manual_step_elapsed_sec"] = manual["step_elapsed_sec"]
        row["manual_step_remaining_sec"] = manual["step_remaining_sec"]
        row["manual_left_target_mps"] = manual["left_target_mps"]
        row["manual_right_target_mps"] = manual["right_target_mps"]
        if map_pose is not None:
            row["map_x"], row["map_y"], row["map_yaw"] = map_pose

        self._writer.writerow(row)
        self._rows += 1
        self._write_pending_paths()

        if now_monotonic - self._last_flush >= 1.0:
            self._main_file.flush()
            self._path_file.flush()
            self._last_flush = now_monotonic

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_manual_control()
        if self._manual_timer is not None:
            self._manual_timer.cancel()
        self._timer.cancel()
        try:
            self._write_pending_paths()
            self._main_file.flush()
            self._path_file.flush()
        finally:
            self._main_file.close()
            self._path_file.close()

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def duration(self) -> float:
        with self._lock:
            if self._recording_start_monotonic is None:
                return 0.0
            if self._recording_active:
                return max(0.0, time.monotonic() - self._recording_start_monotonic)
            return self._recording_duration_sec

    @property
    def tf_errors(self) -> int:
        return self._tf_errors

    def missing_sources(self) -> List[str]:
        with self._lock:
            missing = [
                f"{name} ({SOURCE_TOPICS[name]})"
                for name, seen in self._received_at.items()
                if seen is None
            ]
            imu_seen = self._received_at["imu"] is not None
            imu_yaw_missing = math.isnan(float(self._values["imu_yaw"]))
        if imu_seen and imu_yaw_missing:
            missing.append("imu_yaw (/imu/data does not provide orientation)")
        if TOPICS["local_path"] is None:
            missing.append("local_path (not defined by project)")
        return missing


class ManualControlWindow:
    """Small Tk GUI for latched manual wheel-speed commands."""

    def __init__(self, recorder: ExperimentRecorder, request_close: Any) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        self._tk = tk
        self._messagebox = messagebox
        self._recorder = recorder
        self._request_close = request_close
        self._closing = False

        self.root = tk.Tk()
        self.root.title("AMR Manual Wheel Control + CSV Recorder")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            frame,
            text="Điều khiển vận tốc bánh liên tục",
            font=("TkDefaultFont", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, pady=(0, 12))

        ttk.Label(frame, text="Bánh trái (rad/s):").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=4
        )
        self.left_var = tk.StringVar(value="0.0")
        ttk.Entry(frame, textvariable=self.left_var, width=16).grid(row=1, column=1, pady=4)

        ttk.Label(frame, text="Bánh phải (rad/s):").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=4
        )
        self.right_var = tk.StringVar(value="0.0")
        ttk.Entry(frame, textvariable=self.right_var, width=16).grid(row=2, column=1, pady=4)

        limits = (
            f"Giới hạn sau quy đổi: |linear.x| ≤ {MAX_LINEAR_MPS:g} m/s, "
            f"|angular.z| ≤ {MAX_ANGULAR_RAD_S:g} rad/s"
        )
        ttk.Label(frame, text=limits, foreground="#555555").grid(
            row=3, column=0, columnspan=2, pady=(4, 10)
        )

        ttk.Button(frame, text="XÁC NHẬN / CHẠY LIÊN TỤC", command=self.run).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=4
        )

        ttk.Separator(frame, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=12
        )
        ttk.Label(
            frame,
            text="Profile tự động theo bước (đơn vị vận tốc: m/s)",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=6, column=0, columnspan=2, pady=(0, 6))

        ttk.Label(frame, text="Thời gian từng bước (s):").grid(
            row=7, column=0, sticky="w", padx=(0, 10), pady=3
        )
        self.duration_list_var = tk.StringVar(value="10, 10, 10")
        ttk.Entry(frame, textvariable=self.duration_list_var, width=28).grid(
            row=7, column=1, pady=3
        )

        ttk.Label(frame, text="Bánh trái từng bước (m/s):").grid(
            row=8, column=0, sticky="w", padx=(0, 10), pady=3
        )
        self.left_profile_var = tk.StringVar(value="0.2, 0.3, 0.4")
        ttk.Entry(frame, textvariable=self.left_profile_var, width=28).grid(
            row=8, column=1, pady=3
        )

        ttk.Label(frame, text="Bánh phải từng bước (m/s):").grid(
            row=9, column=0, sticky="w", padx=(0, 10), pady=3
        )
        self.right_profile_var = tk.StringVar(value="0.2, 0.3, 0.4")
        ttk.Entry(frame, textvariable=self.right_profile_var, width=28).grid(
            row=9, column=1, pady=3
        )

        ttk.Label(frame, text="Lặp toàn bộ profile (lần):").grid(
            row=10, column=0, sticky="w", padx=(0, 10), pady=3
        )
        self.repeat_var = tk.StringVar(value="1")
        ttk.Entry(frame, textvariable=self.repeat_var, width=28).grid(
            row=10, column=1, pady=3
        )
        ttk.Label(
            frame,
            text="Ví dụ mặc định: 3 bước × 10 s = 30 s; hai bánh đổi cùng lúc.",
            foreground="#555555",
        ).grid(row=11, column=0, columnspan=2, pady=(3, 7))
        ttk.Button(frame, text="BẮT ĐẦU PROFILE TỰ ĐỘNG", command=self.start_profile).grid(
            row=12, column=0, columnspan=2, sticky="ew", pady=4
        )

        stop_button = tk.Button(
            frame,
            text="DỪNG",
            command=self.stop,
            bg="#c62828",
            fg="white",
            activebackground="#8e0000",
            activeforeground="white",
            font=("TkDefaultFont", 13, "bold"),
            height=2,
        )
        stop_button.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(10, 4))

        self.status_var = tk.StringVar(
            value="CHỜ BẮT ĐẦU — chưa ghi dữ liệu CSV, lệnh vận tốc = 0"
        )
        ttk.Label(frame, textvariable=self.status_var, justify="left").grid(
            row=14, column=0, columnspan=2, sticky="w", pady=(10, 4)
        )
        self.actual_var = tk.StringVar(value="Hall thực tế: trái=NaN, phải=NaN rad/s")
        ttk.Label(frame, textvariable=self.actual_var).grid(
            row=15, column=0, columnspan=2, sticky="w", pady=4
        )
        self.use_filtered_odom_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text=(
                "Dùng dữ liệu SAU EKF (/odometry/filtered)\n"
                "Bỏ chọn = TRƯỚC EKF (/diff_cont/odom)"
            ),
            variable=self.use_filtered_odom_var,
            command=self._select_odom_source,
        ).grid(row=16, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.odom_source_var = tk.StringVar(value="Nguồn cột odom chính: TRƯỚC EKF")
        ttk.Label(frame, textvariable=self.odom_source_var, foreground="#1b5e20").grid(
            row=17, column=0, columnspan=2, sticky="w", pady=2
        )
        self.record_both_odom_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text=(
                "Ghi đồng thời TRƯỚC + SAU EKF trong cùng một dòng CSV\n"
                "(raw_* và filtered_* dùng chung timestamp)"
            ),
            variable=self.record_both_odom_var,
            command=self._select_both_odom,
        ).grid(row=18, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.odom_capture_var = tk.StringVar(value="Chế độ CSV: chỉ nguồn đang chọn")
        ttk.Label(frame, textvariable=self.odom_capture_var, foreground="#0d47a1").grid(
            row=19, column=0, columnspan=2, sticky="w", pady=2
        )
        ttk.Button(frame, text="Đóng cửa sổ (dừng xe)", command=self.close).grid(
            row=20, column=0, columnspan=2, sticky="ew", pady=(10, 0)
        )
        self.root.after(200, self._refresh)

    def run(self) -> None:
        try:
            left = float(self.left_var.get().strip())
            right = float(self.right_var.get().strip())
            if not math.isfinite(left) or not math.isfinite(right):
                raise ValueError("wheel speeds must be finite numbers")
            self._recorder.set_manual_wheel_speeds(left, right)
        except ValueError as exc:
            self._messagebox.showerror("Vận tốc không hợp lệ", str(exc))

    def stop(self) -> None:
        self._recorder.stop_manual_control()

    def _select_odom_source(self) -> None:
        enabled = bool(self.use_filtered_odom_var.get())
        self._recorder.set_use_filtered_odom(enabled)
        self.odom_source_var.set(
            "Nguồn cột odom chính: SAU EKF" if enabled
            else "Nguồn cột odom chính: TRƯỚC EKF"
        )

    def _select_both_odom(self) -> None:
        enabled = bool(self.record_both_odom_var.get())
        self._recorder.set_record_both_odom(enabled)
        self.odom_capture_var.set(
            "Chế độ CSV: đồng thời TRƯỚC + SAU EKF"
            if enabled else "Chế độ CSV: chỉ nguồn đang chọn"
        )

    @staticmethod
    def _number_list(raw: str, label: str) -> List[float]:
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if not parts:
            raise ValueError(f"{label}: danh sách đang trống")
        try:
            return [float(part) for part in parts]
        except ValueError as exc:
            raise ValueError(f"{label}: chỉ nhập các số cách nhau bằng dấu phẩy") from exc

    def start_profile(self) -> None:
        try:
            durations = self._number_list(self.duration_list_var.get(), "Thời gian")
            left_speeds = self._number_list(self.left_profile_var.get(), "Bánh trái")
            right_speeds = self._number_list(self.right_profile_var.get(), "Bánh phải")
            if not (len(durations) == len(left_speeds) == len(right_speeds)):
                raise ValueError(
                    "Ba danh sách phải có cùng số phần tử: mỗi vị trí là một bước"
                )
            repeats = int(self.repeat_var.get().strip())
            steps = list(zip(durations, left_speeds, right_speeds))
            self._recorder.start_manual_profile(steps, repeats)
        except ValueError as exc:
            self._messagebox.showerror("Profile không hợp lệ", str(exc))

    def _refresh(self) -> None:
        if self._closing:
            return
        state = self._recorder.manual_state()
        if state["mode"] == "profile":
            self.status_var.set(
                f"PROFILE: lần {state['repeat_index']:.0f}/{state['repeat_total']:.0f}, "
                f"bước {state['step_index']:.0f}/{state['step_total']:.0f}, "
                f"còn {state['step_remaining_sec']:.1f} s\n"
                f"Mục tiêu: trái={state['left_target_mps']:.3f}, "
                f"phải={state['right_target_mps']:.3f} m/s"
            )
        elif state["running"]:
            self.status_var.set(
                f"ĐANG CHẠY LIÊN TỤC: trái={state['left_rad_s']:.3f}, "
                f"phải={state['right_rad_s']:.3f} rad/s"
            )
        else:
            if state["recording_started"]:
                self.status_var.set(
                    "ĐÃ DỪNG — không ghi thêm CSV, lệnh 0 được phát liên tục"
                )
            else:
                self.status_var.set(
                    "CHỜ BẮT ĐẦU — chưa ghi dữ liệu CSV, lệnh vận tốc = 0"
                )
        self.actual_var.set(
            f"Hall thực tế: trái={state['actual_left_rad_s']:.3f}, "
            f"phải={state['actual_right_rad_s']:.3f} rad/s"
        )
        self.root.after(200, self._refresh)

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._recorder.stop_manual_control()
        self._request_close()
        self.root.destroy()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record AMR ROS 2 experiment data to CSV; manual publishing is disabled "
            "unless --manual-control is supplied."
        )
    )
    parser.add_argument(
        "--name",
        help="File prefix; auto-numbered (default: danhgia -> danhgia1.csv, danhgia2.csv)",
    )
    parser.add_argument(
        "--rate", type=float, default=20.0, help="Snapshot rate, 1-100 Hz (default: 20)"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("experiment_data"), help="Output directory"
    )
    parser.add_argument("--note", default="", help="Optional note stored in every CSV row")
    parser.add_argument(
        "--use-sim-time",
        action="store_true",
        help="Use Gazebo /clock for timestamp_ros",
    )
    parser.add_argument(
        "--manual-control",
        action="store_true",
        help="Enable GUI that continuously publishes confirmed wheel speeds",
    )
    args = parser.parse_args(argv)
    if not 1.0 <= args.rate <= 100.0:
        parser.error("--rate must be between 1 and 100 Hz")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    main_path, path_path = unique_output_paths(args.output.expanduser(), args.name)
    recorder: Optional[ExperimentRecorder] = None
    stop_requested = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    def request_gui_close() -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_sigint: Any = None
    previous_sigterm: Any = None

    try:
        rclpy.init()
        # Install after rclpy.init(), whose default handlers would otherwise replace ours.
        previous_sigint = signal.signal(signal.SIGINT, request_stop)
        previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
        recorder = ExperimentRecorder(
            args.rate,
            main_path,
            path_path,
            args.note,
            args.use_sim_time,
            args.manual_control,
        )
        if args.manual_control:
            window = ManualControlWindow(recorder, request_gui_close)

            def pump_ros() -> None:
                if stop_requested or not rclpy.ok():
                    window.close()
                    return
                try:
                    rclpy.spin_once(recorder, timeout_sec=0.0)
                except (KeyboardInterrupt, ExternalShutdownException):
                    window.close()
                    return
                except Exception as exc:
                    # A failed ROS callback must not leave a misleading live GUI.
                    # Latch zero immediately, report the cause, then close safely.
                    recorder.stop_manual_control()
                    print(f"ROS callback error; manual control stopped: {exc}")
                    window.close()
                    return
                window.root.after(10, pump_ros)

            window.root.after(10, pump_ros)
            window.root.mainloop()
        else:
            while rclpy.ok() and not stop_requested:
                rclpy.spin_once(recorder, timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        stop_requested = True
    except Exception as exc:
        print(f"Recording error: {exc}")
        return_code = 1
    else:
        return_code = 0
    finally:
        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        if recorder is not None:
            recorder.close()
            duration = recorder.duration
            rows = recorder.rows
            average_rate = rows / duration if duration > 0.0 else 0.0
            missing = recorder.missing_sources()
            recorder.destroy_node()
            print("\nRecording stopped")
            print(f"CSV file: {recorder.main_path}")
            print(f"Global path file: {recorder.global_path}")
            print(f"Duration: {duration:.3f} seconds")
            print(f"Rows written: {rows}")
            print(f"Average write rate: {average_rate:.3f} Hz")
            print(f"Missing topics/data: {', '.join(missing) if missing else 'None'}")
            print(f"TF errors: {recorder.tf_errors}")
        if rclpy.ok():
            rclpy.shutdown()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
