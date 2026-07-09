import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

import rclpy
import yaml
from action_msgs.msg import GoalStatus
from amr_docking_server.action import Dock
from amr_mission_supervisor.srv import SubmitMission
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger


class MissionState(str, Enum):
    IDLE = 'IDLE'
    NAV_TO_PRE_DOCK_A = 'NAV_TO_PRE_DOCK_A'
    ARRIVED_A = 'ARRIVED_A'
    DOCKING_IN = 'DOCKING_IN'
    DOCKED = 'DOCKED'
    WAITING_CARGO = 'WAITING_CARGO'
    UNDOCKING = 'UNDOCKING'
    UNDOCKED = 'UNDOCKED'
    NAV_TO_NEXT = 'NAV_TO_NEXT'
    MISSION_DONE = 'MISSION_DONE'
    FAILED = 'FAILED'


@dataclass
class Pose2D:
    frame_id: str
    x: float
    y: float
    yaw: float


@dataclass
class Mission:
    task_id: str
    station_id: str
    cargo_mode: str
    next_goal: PoseStamped
    has_next_goal: bool
    use_dynamic_poses: bool
    pre_dock_pose: PoseStamped
    dock_final_pose: PoseStamped


def yaw_to_quat(yaw: float):
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


class MissionSupervisor(Node):
    def __init__(self):
        super().__init__('mission_supervisor')
        self.declare_parameter('station_database', '')
        self.declare_parameter('nav_action_name', 'navigate_to_pose')
        self.declare_parameter('dock_action_name', '/dock')
        self.declare_parameter('cmd_vel_nav_topic', '/cmd_vel_nav')
        self.declare_parameter('cmd_vel_dock_topic', '/cmd_vel_dock')
        self.declare_parameter('nav_to_a_timeout_sec', 180.0)
        self.declare_parameter('nav_to_next_timeout_sec', 180.0)
        self.declare_parameter('docking_timeout_sec', 90.0)
        self.declare_parameter('cargo_wait_timeout_sec', 600.0)
        self.declare_parameter('dock_max_speed', 0.06)

        self.stations = self._load_station_db()
        self.state = MissionState.IDLE
        self.state_lock = threading.Lock()
        self.worker: Optional[threading.Thread] = None
        self.cargo_event = threading.Event()
        self.stop_event = threading.Event()

        self.nav_client = ActionClient(
            self, NavigateToPose, self.get_parameter('nav_action_name').value)
        self.dock_client = ActionClient(
            self, Dock, self.get_parameter('dock_action_name').value)
        self.nav_zero_pub = self.create_publisher(
            Twist, self.get_parameter('cmd_vel_nav_topic').value, 10)
        self.dock_zero_pub = self.create_publisher(
            Twist, self.get_parameter('cmd_vel_dock_topic').value, 10)
        self.status_pub = self.create_publisher(String, '/mission/status', 10)

        self.create_service(SubmitMission, '/mission/submit', self._submit_cb)
        self.create_service(Trigger, '/mission/pick_done', self._cargo_done_cb)
        self.create_service(Trigger, '/mission/drop_done', self._cargo_done_cb)
        self.create_service(Trigger, '/mission/cancel', self._cancel_cb)
        self.create_timer(1.0, self._publish_heartbeat)
        self.get_logger().info('Mission supervisor ready: /mission/submit')

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
        return stations

    def _set_state(self, state: MissionState, detail: str = ''):
        with self.state_lock:
            self.state = state
        msg = String()
        msg.data = f'{state.value}|{detail}' if detail else state.value
        self.status_pub.publish(msg)
        self.get_logger().info(f'mission state: {msg.data}')

    def _publish_heartbeat(self):
        with self.state_lock:
            state = self.state
        msg = String()
        msg.data = state.value
        self.status_pub.publish(msg)

    def _pose_from_station(self, pose: Pose2D) -> PoseStamped:
        msg = PoseStamped()
        msg.header.frame_id = pose.frame_id
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.position.x = pose.x
        msg.pose.position.y = pose.y
        qx, qy, qz, qw = yaw_to_quat(pose.yaw)
        msg.pose.orientation.x = qx
        msg.pose.orientation.y = qy
        msg.pose.orientation.z = qz
        msg.pose.orientation.w = qw
        return msg

    def _submit_cb(self, request, response):
        if not request.use_dynamic_poses and request.station_id not in self.stations:
            response.success = False
            response.message = f'Unknown station: {request.station_id}'
            return response
        if self.worker and self.worker.is_alive():
            response.success = False
            response.message = 'Mission supervisor is busy'
            return response

        mission = Mission(
            task_id=request.task_id or f'mission_{int(time.time())}',
            station_id=request.station_id,
            cargo_mode=(request.cargo_mode or 'PICK').upper(),
            next_goal=request.next_goal,
            has_next_goal=bool(request.has_next_goal),
            use_dynamic_poses=bool(request.use_dynamic_poses),
            pre_dock_pose=request.pre_dock_pose,
            dock_final_pose=request.dock_final_pose,
        )
        self.cargo_event.clear()
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run_mission, args=(mission,), daemon=True)
        self.worker.start()
        response.success = True
        response.message = f'Accepted {mission.task_id} for station {mission.station_id}'
        return response

    def _cargo_done_cb(self, request, response):
        del request
        self.cargo_event.set()
        response.success = True
        response.message = 'cargo done accepted'
        self.get_logger().info('cargo done signal received')
        return response

    def _cancel_cb(self, request, response):
        del request
        self.stop_event.set()
        self._publish_zero()
        response.success = True
        response.message = 'cancel requested'
        return response

    def _publish_zero(self, count: int = 8):
        zero = Twist()
        for _ in range(count):
            self.nav_zero_pub.publish(zero)
            self.dock_zero_pub.publish(zero)

    def _run_mission(self, mission: Mission):
        try:
            if mission.use_dynamic_poses:
                pose_a = mission.pre_dock_pose
                pose_a.header.stamp = self.get_clock().now().to_msg()
            else:
                station = self.stations[mission.station_id]
                pose_a = self._pose_from_station(station['pre_dock_pose_A'])

            self._set_state(MissionState.NAV_TO_PRE_DOCK_A, mission.station_id)
            self._navigate(pose_a, self.get_parameter('nav_to_a_timeout_sec').value)
            self._publish_zero()
            self._set_state(MissionState.ARRIVED_A, mission.station_id)

            self._set_state(MissionState.DOCKING_IN, mission.station_id)
            self._dock(mission, 'DOCK_IN')
            self._publish_zero()
            self._set_state(MissionState.DOCKED, 'READY_TO_PICK')

            self._set_state(MissionState.WAITING_CARGO, mission.cargo_mode)
            if not self.cargo_event.wait(self.get_parameter('cargo_wait_timeout_sec').value):
                raise RuntimeError('cargo wait timeout')
            if self.stop_event.is_set():
                raise RuntimeError('mission canceled')

            self._set_state(MissionState.UNDOCKING, mission.station_id)
            self._dock(mission, 'UNDOCK_OUT')
            self._publish_zero()
            self._set_state(MissionState.UNDOCKED, mission.station_id)

            if mission.has_next_goal:
                self._set_state(MissionState.NAV_TO_NEXT, mission.task_id)
                mission.next_goal.header.stamp = self.get_clock().now().to_msg()
                self._navigate(mission.next_goal, self.get_parameter('nav_to_next_timeout_sec').value)
            self._publish_zero()
            self._set_state(MissionState.MISSION_DONE, mission.task_id)
        except Exception as exc:
            self._publish_zero(12)
            self._set_state(MissionState.FAILED, str(exc))
            self.get_logger().error(f'mission failed: {exc}')

    def _navigate(self, pose: PoseStamped, timeout_sec: float):
        if self.stop_event.is_set():
            raise RuntimeError('mission canceled')
        if not self.nav_client.wait_for_server(timeout_sec=10.0):
            raise RuntimeError('Nav2 NavigateToPose action not ready')
        goal = NavigateToPose.Goal()
        goal.pose = pose
        send_future = self.nav_client.send_goal_async(goal)
        self._wait_future(send_future, 10.0, 'Nav2 goal response timeout')
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError('Nav2 goal rejected')
        result_future = goal_handle.get_result_async()
        deadline = self.get_clock().now() + Duration(seconds=float(timeout_sec))
        while rclpy.ok() and not result_future.done():
            if self.stop_event.is_set():
                goal_handle.cancel_goal_async()
                raise RuntimeError('mission canceled')
            if self.get_clock().now() > deadline:
                goal_handle.cancel_goal_async()
                raise RuntimeError('Nav2 timeout')
            time.sleep(0.05)
        result = result_future.result()
        if result.status != GoalStatus.STATUS_SUCCEEDED:
            raise RuntimeError(f'Nav2 failed with status {result.status}')

    def _dock(self, mission: Mission, mode: str):
        if self.stop_event.is_set():
            raise RuntimeError('mission canceled')
        if not self.dock_client.wait_for_server(timeout_sec=10.0):
            raise RuntimeError('Dock action server not ready')
        goal = Dock.Goal()
        goal.task_id = mission.task_id
        goal.station_id = mission.station_id
        goal.mode = mode
        goal.max_speed = float(self.get_parameter('dock_max_speed').value)
        if mission.use_dynamic_poses:
            goal.target_pose = mission.dock_final_pose if mode == 'DOCK_IN' else mission.pre_dock_pose
            goal.target_pose.header.stamp = self.get_clock().now().to_msg()
        send_future = self.dock_client.send_goal_async(goal, feedback_callback=self._dock_feedback_cb)
        self._wait_future(send_future, 10.0, f'Dock {mode} goal response timeout')
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError(f'Dock {mode} rejected')
        result_future = goal_handle.get_result_async()
        deadline = self.get_clock().now() + Duration(seconds=self.get_parameter('docking_timeout_sec').value)
        while rclpy.ok() and not result_future.done():
            if self.stop_event.is_set():
                goal_handle.cancel_goal_async()
                raise RuntimeError('mission canceled')
            if self.get_clock().now() > deadline:
                goal_handle.cancel_goal_async()
                raise RuntimeError(f'Dock {mode} timeout')
            time.sleep(0.05)
        result = result_future.result()
        if result.status != GoalStatus.STATUS_SUCCEEDED or not result.result.success:
            raise RuntimeError(f'Dock {mode} failed: {result.result.message}')

    def _wait_future(self, future, timeout_sec: float, timeout_message: str):
        deadline = time.monotonic() + float(timeout_sec)
        while rclpy.ok() and not future.done():
            if self.stop_event.is_set():
                raise RuntimeError('mission canceled')
            if time.monotonic() > deadline:
                raise RuntimeError(timeout_message)
            time.sleep(0.05)

    def _dock_feedback_cb(self, feedback_msg):
        fb = feedback_msg.feedback
        self.get_logger().info(
            f'dock feedback: {fb.state} dist={fb.distance_remaining:.3f} '
            f'yaw={math.degrees(fb.yaw_error):.2f}deg lateral={fb.lateral_error:.3f}')


def main():
    rclpy.init()
    node = MissionSupervisor()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node._publish_zero(10)
        node.destroy_node()
        rclpy.shutdown()
