#!/usr/bin/env python3
"""Standalone logger: Nav2 cmd_vel vs hall (joint_states) per-wheel velocities -> CSV.

Does not modify any ROS package. Run while the robot stack is up:

  source /opt/ros/<distro>/setup.bash
  source /home/admin-pc/dev_ws/install/setup.bash
  python3 /home/admin-pc/dev_ws/scripts/log_wheel_velocity_response.py

  # optional:
  python3 .../log_wheel_velocity_response.py --duration 60 --output /tmp/vel_response.csv
  python3 .../log_wheel_velocity_response.py --cmd-topic /diff_cont/cmd_vel_unstamped

CSV columns (SI units):
  time_sec, stamp_wall_sec,
  cmd_linear_x_mps, cmd_angular_z_rps,
  nav2_left_rad_s, nav2_right_rad_s,
  nav2_left_mps, nav2_right_mps,
  hall_left_rad_s, hall_right_rad_s,
  hall_left_mps, hall_right_mps
"""

from __future__ import annotations

import argparse
import csv
import math
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import JointState


# Defaults from amr_lan_3/config/my_controllers.yaml
DEFAULT_WHEEL_SEPARATION = 0.5703  # m
DEFAULT_WHEEL_RADIUS = 0.09  # m
LEFT_JOINT = "left_wheel_joint"
RIGHT_JOINT = "right_wheel_joint"


def twist_to_wheel_omega(
    linear_x: float,
    angular_z: float,
    wheel_separation: float,
    wheel_radius: float,
) -> tuple[float, float]:
    """Diff-drive: Twist (v, w) -> left/right wheel angular velocity [rad/s]."""
    v_left = linear_x - (angular_z * wheel_separation / 2.0)
    v_right = linear_x + (angular_z * wheel_separation / 2.0)
    return v_left / wheel_radius, v_right / wheel_radius


class WheelVelocityLogger(Node):
    def __init__(
        self,
        cmd_topic: str,
        joint_states_topic: str,
        wheel_separation: float,
        wheel_radius: float,
        sample_hz: float,
        csv_path: Path,
    ) -> None:
        super().__init__("wheel_velocity_response_logger")
        self._wheel_separation = wheel_separation
        self._wheel_radius = wheel_radius
        self._lock = threading.Lock()

        self._cmd_linear_x = 0.0
        self._cmd_angular_z = 0.0
        self._cmd_rx = False

        self._hall_left = float("nan")
        self._hall_right = float("nan")
        self._hall_rx = False

        self._t0 = time.monotonic()
        self._rows = 0
        self._stop = False

        self._csv_path = csv_path
        self._csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._csv_file = self._csv_path.open("w", newline="")
        self._writer = csv.writer(self._csv_file)
        self._writer.writerow(
            [
                "time_sec",
                "stamp_wall_sec",
                "cmd_linear_x_mps",
                "cmd_angular_z_rps",
                "nav2_left_rad_s",
                "nav2_right_rad_s",
                "nav2_left_mps",
                "nav2_right_mps",
                "hall_left_rad_s",
                "hall_right_rad_s",
                "hall_left_mps",
                "hall_right_mps",
            ]
        )
        self._csv_file.flush()

        self.create_subscription(Twist, cmd_topic, self._on_cmd, 50)
        self.create_subscription(JointState, joint_states_topic, self._on_joint_states, 50)
        period = 1.0 / sample_hz if sample_hz > 0.0 else 0.05
        self.create_timer(period, self._on_sample)

        self.get_logger().info(
            f"Logging cmd={cmd_topic} + hall={joint_states_topic} -> {csv_path} "
            f"(L={wheel_separation} m, r={wheel_radius} m, {sample_hz} Hz)"
        )

    def _on_cmd(self, msg: Twist) -> None:
        with self._lock:
            self._cmd_linear_x = float(msg.linear.x)
            self._cmd_angular_z = float(msg.angular.z)
            self._cmd_rx = True

    def _on_joint_states(self, msg: JointState) -> None:
        if not msg.name or not msg.velocity:
            return
        name_to_idx = {n: i for i, n in enumerate(msg.name)}
        if LEFT_JOINT not in name_to_idx or RIGHT_JOINT not in name_to_idx:
            return
        li = name_to_idx[LEFT_JOINT]
        ri = name_to_idx[RIGHT_JOINT]
        if li >= len(msg.velocity) or ri >= len(msg.velocity):
            return
        with self._lock:
            self._hall_left = float(msg.velocity[li])
            self._hall_right = float(msg.velocity[ri])
            self._hall_rx = True

    def _on_sample(self) -> None:
        if self._stop:
            return
        with self._lock:
            vx = self._cmd_linear_x
            wz = self._cmd_angular_z
            hall_l = self._hall_left
            hall_r = self._hall_right
            have_cmd = self._cmd_rx
            have_hall = self._hall_rx

        if not (have_cmd or have_hall):
            return

        nav_l, nav_r = twist_to_wheel_omega(
            vx, wz, self._wheel_separation, self._wheel_radius
        )
        r = self._wheel_radius
        t_rel = time.monotonic() - self._t0
        t_wall = time.time()

        self._writer.writerow(
            [
                f"{t_rel:.6f}",
                f"{t_wall:.6f}",
                f"{vx:.6f}",
                f"{wz:.6f}",
                f"{nav_l:.6f}",
                f"{nav_r:.6f}",
                f"{nav_l * r:.6f}",
                f"{nav_r * r:.6f}",
                f"{hall_l:.6f}" if have_hall else "",
                f"{hall_r:.6f}" if have_hall else "",
                f"{hall_l * r:.6f}" if have_hall else "",
                f"{hall_r * r:.6f}" if have_hall else "",
            ]
        )
        self._rows += 1
        if self._rows % 50 == 0:
            self._csv_file.flush()

    def request_stop(self) -> None:
        self._stop = True

    def close(self) -> None:
        try:
            self._csv_file.flush()
            self._csv_file.close()
        except Exception:
            pass
        self.get_logger().info(f"Wrote {self._rows} samples to {self._csv_path}")


def parse_args() -> argparse.Namespace:
    default_out = Path.home() / "vel_response_logs" / (
        f"wheel_vel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    p = argparse.ArgumentParser(
        description="Log Nav2 cmd_vel vs hall wheel velocities to CSV (standalone)."
    )
    p.add_argument(
        "--cmd-topic",
        default="/cmd_vel_nav",
        help="Nav2 (smoothed) Twist topic. Use /diff_cont/cmd_vel_unstamped for "
        "command actually sent to diff_drive after twist_mux. (default: %(default)s)",
    )
    p.add_argument(
        "--joint-states-topic",
        default="/joint_states",
        help="JointState topic with left/right wheel velocity from hall (default: %(default)s)",
    )
    p.add_argument(
        "--wheel-separation",
        type=float,
        default=DEFAULT_WHEEL_SEPARATION,
        help=f"Track width L [m] (default: {DEFAULT_WHEEL_SEPARATION})",
    )
    p.add_argument(
        "--wheel-radius",
        type=float,
        default=DEFAULT_WHEEL_RADIUS,
        help=f"Wheel radius r [m] (default: {DEFAULT_WHEEL_RADIUS})",
    )
    p.add_argument(
        "--rate",
        type=float,
        default=20.0,
        help="CSV sample rate [Hz] (default: %(default)s)",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Stop after N seconds (0 = until Ctrl+C). (default: %(default)s)",
    )
    p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=default_out,
        help=f"CSV output path (default: {default_out})",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.wheel_radius <= 0.0 or args.wheel_separation <= 0.0:
        print("wheel-radius and wheel-separation must be > 0", file=sys.stderr)
        return 2
    if args.rate <= 0.0:
        print("--rate must be > 0", file=sys.stderr)
        return 2

    rclpy.init()
    node = WheelVelocityLogger(
        cmd_topic=args.cmd_topic,
        joint_states_topic=args.joint_states_topic,
        wheel_separation=args.wheel_separation,
        wheel_radius=args.wheel_radius,
        sample_hz=args.rate,
        csv_path=args.output.expanduser().resolve(),
    )

    stop = {"flag": False}

    def _handle_sig(_signum, _frame) -> None:
        stop["flag"] = True
        node.request_stop()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    end_t = (
        time.monotonic() + args.duration if args.duration and args.duration > 0 else None
    )

    try:
        while rclpy.ok() and not stop["flag"]:
            rclpy.spin_once(node, timeout_sec=0.1)
            if end_t is not None and time.monotonic() >= end_t:
                break
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    print(f"CSV saved: {args.output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
