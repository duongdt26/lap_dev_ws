"""Process-level ROS mode transitions (NORMAL <-> SLAM mapping)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from .config import Settings


class RosModeManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._mode = "normal"
        self._slam: subprocess.Popen | None = None
        self._localization: subprocess.Popen | None = None
        self._navigation: subprocess.Popen | None = None

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def status(self) -> dict:
        with self._lock:
            return {
                "mode": self._mode,
                "slamRunning": self._alive(self._slam),
                "localizationRunning": self._alive(self._localization),
                "navigationRunning": self._alive(self._navigation),
                "busy": False,
            }

    @staticmethod
    def _alive(process: subprocess.Popen | None) -> bool:
        return process is not None and process.poll() is None

    def _command(self, command: str) -> subprocess.Popen:
        workspace = Path(__file__).resolve().parents[2]
        setup = workspace / "install" / "setup.bash"
        shell_command = f"source '{setup}' && {command}"
        return subprocess.Popen(
            ["bash", "-lc", shell_command],
            cwd=str(workspace),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )

    def _stop_process(self, process: subprocess.Popen | None) -> None:
        if not self._alive(process):
            return
        assert process is not None
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=8)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _shutdown_existing_lifecycle(self, manager: str) -> None:
        # Best effort: this also handles launches started manually in a terminal.
        subprocess.run(
            ["ros2", "lifecycle", "set", manager, "shutdown"],
            check=False,
            timeout=8,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _stop_normal(self) -> None:
        self._shutdown_existing_lifecycle("/lifecycle_manager_navigation")
        self._shutdown_existing_lifecycle("/lifecycle_manager_localization")
        self._stop_process(self._navigation)
        self._stop_process(self._localization)
        # Also clean launches started manually from Terminator/another shell.
        # Lifecycle shutdown alone leaves the ros2 launch process alive.
        for pattern in (
            "localization_launch.py",
            "navigation_launch.py",
            "/nav2_amcl/amcl",
            "/nav2_bt_navigator/bt_navigator",
            "/nav2_lifecycle_manager/lifecycle_manager",
            "bt_navigator_navigate_through_poses_rclcpp_node",
            "bt_navigator_navigate_to_pose_rclcpp_node",
        ):
            subprocess.run(
                ["pkill", "-TERM", "-f", pattern],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(1.0)
        for pattern in (
            "/nav2_amcl/amcl",
            "/nav2_bt_navigator/bt_navigator",
            "/nav2_lifecycle_manager/lifecycle_manager",
            "bt_navigator_navigate_through_poses_rclcpp_node",
            "bt_navigator_navigate_to_pose_rclcpp_node",
        ):
            subprocess.run(
                ["pkill", "-KILL", "-f", pattern],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self._wait_nodes_gone({"/amcl", "/bt_navigator", "/lifecycle_manager_localization", "/lifecycle_manager_navigation"}, timeout=30.0)
        self._navigation = None
        self._localization = None

    @staticmethod
    def _wait_nodes_gone(names: set[str], timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["ros2", "node", "list"], capture_output=True, text=True,
                    check=False, timeout=2,
                )
                active = set(result.stdout.splitlines())
                if not active.intersection(names):
                    return
            except (OSError, subprocess.TimeoutExpired):
                pass
            time.sleep(0.5)
        remaining = ", ".join(sorted(names))
        raise RuntimeError(f"Chưa dừng hoàn toàn Nav2/localization: {remaining}")

    @staticmethod
    def _wait_nodes_present(names: set[str], timeout: float = 45.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["ros2", "node", "list"], capture_output=True, text=True,
                    check=False, timeout=2,
                )
                if names.issubset(set(result.stdout.splitlines())):
                    return
            except (OSError, subprocess.TimeoutExpired):
                pass
            time.sleep(0.5)
        raise RuntimeError(f"Node chưa sẵn sàng: {', '.join(sorted(names))}")

    def _stop_slam(self) -> None:
        self._stop_process(self._slam)
        self._slam = None

    def _start_slam(self) -> None:
        workspace = Path(__file__).resolve().parents[2]
        params = workspace / "src/amr_lan_3/config/mapper_params_online_async.yaml"
        sim = "true" if self.settings.use_sim_time else "false"
        self._slam = self._command(
            "ros2 launch slam_toolbox online_async_launch.py "
            f"slam_params_file:='{params}' use_sim_time:={sim}"
        )
        self._wait_nodes_present({"/slam_toolbox"})

    def _start_normal(self) -> None:
        sim = "true" if self.settings.use_sim_time else "false"
        self._localization = self._command(
            "ros2 launch amr_lan_3 localization_launch.py "
            f"map:=./obs_3_map_save.yaml use_sim_time:={sim}"
        )
        self._navigation = self._command(
            "ros2 launch amr_lan_3 navigation_launch.py "
            f"use_sim_time:={sim} map_subscribe_transient_local:=true"
        )
        self._wait_nodes_present({"/amcl", "/bt_navigator", "/lifecycle_manager_localization", "/lifecycle_manager_navigation"})
        self._activate_localization()

    @staticmethod
    def _activate_localization() -> None:
        # Some launch/lifecycle-manager combinations leave these nodes
        # unconfigured after a mode switch. Make readiness explicit.
        for node in ("/map_server", "/amcl"):
            state = subprocess.run(
                ["ros2", "lifecycle", "get", node],
                capture_output=True, text=True, check=False, timeout=5,
            ).stdout
            if "unconfigured" in state:
                subprocess.run(["ros2", "lifecycle", "set", node, "configure"],
                               check=True, timeout=10)
                state = "inactive"
            if "inactive" in state:
                subprocess.run(["ros2", "lifecycle", "set", node, "activate"],
                               check=True, timeout=10)

    def enable_slam(self) -> dict:
        with self._lock:
            if self._mode == "slam":
                return self.status()
            self._stop_normal()
            self._start_slam()
            self._mode = "slam"
            return self.status()

    def disable_slam(self, map_name: str | None = None) -> dict:
        with self._lock:
            if self._mode != "slam":
                return self.status()
            if map_name:
                safe = map_name.strip()
                if not safe.replace("_", "").replace("-", "").isalnum():
                    raise ValueError("Tên map chỉ được dùng chữ, số, _ và -")
                subprocess.run(
                    ["ros2", "service", "call", "/save_map_named",
                     "amr_web_interfaces/srv/SaveMap", f"{{map_name: '{safe}'}}"],
                    check=True, timeout=30,
                )
            self._stop_slam()
            self._start_normal()
            self._mode = "normal"
            return self.status()

    def close(self) -> None:
        with self._lock:
            self._stop_slam()
            self._stop_normal()


_manager: RosModeManager | None = None


def get_mode_manager(settings: Settings | None = None) -> RosModeManager:
    global _manager
    if _manager is None:
        from .config import get_settings
        _manager = RosModeManager(settings or get_settings())
    return _manager
