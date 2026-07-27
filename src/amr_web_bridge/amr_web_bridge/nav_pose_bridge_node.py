#!/usr/bin/env python3
"""Bridge Nav2 action + pose map frame cho web (rosbridge không gửi ROS2 action trực tiếp)."""

import math

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from action_msgs.msg import GoalInfo, GoalStatus
from action_msgs.srv import CancelGoal
from builtin_interfaces.msg import Duration as DurationMsg
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import DriveOnHeading, NavigateToPose
from nav_msgs.msg import Path
from std_msgs.msg import String
from std_srvs.srv import Trigger
from amr_web_interfaces.srv import SendNavGoal
from tf2_ros import Buffer, TransformListener
from tf2_ros import TransformException


class NavPoseBridgeNode(Node):
    def __init__(self):
        super().__init__('nav_pose_bridge_node')

        self.declare_parameter('nav_wait_timeout_sec', 300.0)
        self.declare_parameter('home_x', 0.0)
        self.declare_parameter('home_y', 0.0)
        self.declare_parameter('near_home_threshold_m', 0.30)
        self.declare_parameter('undock_distance_m', 0.50)
        self.declare_parameter('undock_speed_mps', 0.08)
        self.declare_parameter('undock_time_allowance_sec', 20.0)

        self._home_x = float(self.get_parameter('home_x').value)
        self._home_y = float(self.get_parameter('home_y').value)
        self._near_home_m = float(self.get_parameter('near_home_threshold_m').value)
        self._undock_dist_m = float(self.get_parameter('undock_distance_m').value)
        self._undock_speed = float(self.get_parameter('undock_speed_mps').value)
        self._undock_timeout_sec = float(
            self.get_parameter('undock_time_allowance_sec').value)

        self._nav_cb_group = MutuallyExclusiveCallbackGroup()
        self._action = ActionClient(
            self, NavigateToPose, 'navigate_to_pose',
            callback_group=self._nav_cb_group)
        self._drive_action = ActionClient(
            self, DriveOnHeading, 'drive_on_heading',
            callback_group=self._nav_cb_group)
        self._goal_handle = None
        self._undock_handle = None
        self._result_future = None
        self._nav_label = ''
        self._nav_finished = False
        self._pending_nav_goal = None

        self.create_service(
            SendNavGoal, '/send_nav_goal', self._send_goal_cb,
            callback_group=self._nav_cb_group)
        self.create_service(
            Trigger, '/cancel_nav', self._cancel_cb,
            callback_group=self._nav_cb_group)

        self._cancel_goal_cli = self.create_client(
            CancelGoal, '/navigate_to_pose/_action/cancel_goal',
            callback_group=self._nav_cb_group)
        self._stop_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self._plan_clear_pub = self.create_publisher(Path, '/web_plan_clear', 10)
        self._nav_status_pub = self.create_publisher(String, '/web_nav_status', 10)

        self._pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, '/robot_pose_map', 10)
        self._tf_buffer = Buffer(cache_time=Duration(seconds=30.0))
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self.create_timer(0.1, self._publish_pose)

        use_sim = self.get_parameter('use_sim_time').value
        self.get_logger().info(f'use_sim_time={use_sim}')
        self.get_logger().info(
            'Services: /send_nav_goal | Topics: /robot_pose_map, /web_nav_status'
        )
        self.get_logger().info(
            f'Undock near home: threshold={self._near_home_m:.2f} m, '
            f'distance={self._undock_dist_m:.2f} m, '
            f'home=({self._home_x:.2f}, {self._home_y:.2f})'
        )

    def _publish_nav_status(self, status: str, detail: str = ''):
        msg = String()
        msg.data = f'{status}|{detail}' if detail else status
        self._nav_status_pub.publish(msg)
        self.get_logger().info(f'nav status: {msg.data}')

    def _yaw_to_quat(self, yaw):
        return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))

    def _clear_nav_track(self):
        self._goal_handle = None
        self._undock_handle = None
        self._result_future = None
        self._nav_label = ''
        self._nav_finished = False
        self._pending_nav_goal = None

    def _finish_nav(self, status: str, label: str):
        if self._nav_finished:
            return
        self._nav_finished = True
        self._publish_nav_status(status, label)
        self._clear_nav_track()

    def _lookup_robot_xy(self):
        for when in (self.get_clock().now(), rclpy.time.Time()):
            try:
                t = self._tf_buffer.lookup_transform(
                    'map',
                    'base_footprint',
                    when,
                    timeout=Duration(seconds=0.05),
                )
                return (
                    t.transform.translation.x,
                    t.transform.translation.y,
                )
            except TransformException:
                continue
        return None

    def _distance_to_home(self):
        xy = self._lookup_robot_xy()
        if xy is None:
            return None
        dx = xy[0] - self._home_x
        dy = xy[1] - self._home_y
        return math.hypot(dx, dy)

    def _build_nav_goal(self, x, y, yaw):
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        qx, qy, qz, qw = self._yaw_to_quat(yaw)
        goal.pose.pose.orientation.x = qx
        goal.pose.pose.orientation.y = qy
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw
        return goal

    def _start_navigate(self, goal, label):
        self._nav_label = label
        self._nav_finished = False
        self._pending_nav_goal = None
        send_future = self._action.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)

    def _start_undock_then_nav(self, nav_goal, label):
        undock = DriveOnHeading.Goal()
        undock.target.x = self._undock_dist_m
        undock.target.y = 0.0
        undock.target.z = 0.0
        undock.speed = self._undock_speed
        undock.time_allowance = DurationMsg(
            sec=int(self._undock_timeout_sec),
            nanosec=int(
                (self._undock_timeout_sec - int(self._undock_timeout_sec))
                * 1e9
            ),
        )

        self._nav_label = label
        self._nav_finished = False
        self._pending_nav_goal = nav_goal
        self._publish_nav_status(
            'undocking',
            f'{self._undock_dist_m:.2f}m from home',
        )
        send_future = self._drive_action.send_goal_async(undock)
        send_future.add_done_callback(self._on_undock_goal_response)

    def _on_undock_goal_response(self, future):
        if self._nav_finished or self._pending_nav_goal is None:
            return
        label = self._nav_label
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.get_logger().error(f'undock goal response error: {exc}')
            self._finish_nav('failed', f'undock: {exc}')
            return

        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().warn('Undock rejected; sending NavigateToPose anyway')
            self._start_navigate(self._pending_nav_goal, label)
            return

        self._undock_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_undock_result)

    def _on_undock_result(self, future):
        if self._nav_finished or self._pending_nav_goal is None:
            return
        label = self._nav_label
        nav_goal = self._pending_nav_goal
        try:
            result = future.result()
            goal_status = result.status
        except Exception as exc:
            self.get_logger().error(f'undock result error: {exc}')
            self._finish_nav('failed', f'undock: {exc}')
            return

        self._undock_handle = None
        if goal_status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('Undock done; starting NavigateToPose')
            self._start_navigate(nav_goal, label)
            return

        if goal_status == GoalStatus.STATUS_CANCELED:
            self._finish_nav('cancelled', label)
            return

        self.get_logger().warn(
            f'Undock failed (status={goal_status}); sending NavigateToPose anyway'
        )
        self._start_navigate(nav_goal, label)

    def _on_result_future(self, future):
        if self._nav_finished:
            return
        label = self._nav_label
        try:
            result = future.result()
            goal_status = result.status
        except Exception as exc:
            self.get_logger().error(f'nav result error: {exc}')
            self._finish_nav('failed', str(exc))
            return

        if goal_status == GoalStatus.STATUS_SUCCEEDED:
            self._finish_nav('arrived', label)
        elif goal_status == GoalStatus.STATUS_CANCELED:
            self._finish_nav('cancelled', label)
        else:
            self._finish_nav('failed', f'status_{goal_status}')

    def _on_goal_response(self, future):
        if self._nav_finished:
            return
        label = self._nav_label
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.get_logger().error(f'nav goal response error: {exc}')
            self._finish_nav('failed', str(exc))
            return

        if goal_handle is None or not goal_handle.accepted:
            self._finish_nav('failed', label)
            return

        self._goal_handle = goal_handle
        self._nav_finished = False
        self._result_future = goal_handle.get_result_async()
        self._result_future.add_done_callback(self._on_result_future)
        self._publish_nav_status('navigating', label)

    def _cancel_active_actions(self):
        if self._undock_handle is not None:
            try:
                self._undock_handle.cancel_goal_async()
            except Exception as exc:
                self.get_logger().warn(f'cancel undock: {exc}')
        if self._goal_handle is not None:
            try:
                self._goal_handle.cancel_goal_async()
            except Exception as exc:
                self.get_logger().warn(f'cancel previous goal: {exc}')

    def _send_goal_cb(self, request, response):
        x = float(request.x)
        y = float(request.y)
        yaw = float(request.yaw)
        controller_id = str(getattr(request, 'controller_id', '') or '').strip()
        label = f'{x:.2f},{y:.2f},{math.degrees(yaw):.1f}'

        if controller_id:
            response.success = False
            response.message = f'Controller-specific navigation is unavailable: {controller_id}'
            self._publish_nav_status('failed', 'controller_unavailable')
            return response

        if not self._action.server_is_ready():
            response.success = False
            response.message = 'Nav2 action /navigate_to_pose chưa sẵn sàng'
            self._publish_nav_status('failed', 'nav2_not_ready')
            return response

        self._nav_finished = True
        self._cancel_active_actions()
        self._clear_nav_track()

        nav_goal = self._build_nav_goal(x, y, yaw)

        dist_home = self._distance_to_home()
        need_undock = (
            dist_home is not None
            and dist_home <= self._near_home_m
            and self._undock_dist_m > 0.0
        )

        if need_undock:
            if not self._drive_action.server_is_ready():
                self.get_logger().warn(
                    'Gần home nhưng /drive_on_heading chưa sẵn sàng; '
                    'bỏ undock, gửi NavigateToPose'
                )
                self._start_navigate(nav_goal, label)
                response.message = (
                    f'Goal queued (skip undock, drive_on_heading not ready): '
                    f'({x:.2f}, {y:.2f}) yaw={math.degrees(yaw):.1f}°'
                )
            else:
                self.get_logger().info(
                    f'Gần home ({dist_home:.3f} m ≤ {self._near_home_m:.2f} m); '
                    f'undock {self._undock_dist_m:.2f} m trước khi nav'
                )
                self._start_undock_then_nav(nav_goal, label)
                response.message = (
                    f'Undock {self._undock_dist_m:.2f} m rồi nav tới '
                    f'({x:.2f}, {y:.2f}) yaw={math.degrees(yaw):.1f}°'
                )
        else:
            if dist_home is None:
                self.get_logger().warn(
                    'Không lấy được TF map→base_footprint; bỏ check undock'
                )
            self._start_navigate(nav_goal, label)
            response.message = (
                f'Goal queued: ({x:.2f}, {y:.2f}) '
                f'yaw={math.degrees(yaw):.1f}°'
            )

        response.success = True
        return response

    def _cancel_cb(self, request, response):
        del request
        self._publish_nav_status('cancelling', '')

        self._nav_finished = True
        self._cancel_active_actions()
        self._clear_nav_track()

        if self._cancel_goal_cli.service_is_ready():
            req = CancelGoal.Request()
            req.goal_info = GoalInfo()
            req.goal_info.goal_id.uuid = [0] * 16
            self._cancel_goal_cli.call_async(req)

        stop = Twist()
        for _ in range(5):
            self._stop_pub.publish(stop)

        empty_plan = Path()
        empty_plan.header.frame_id = 'map'
        self._plan_clear_pub.publish(empty_plan)

        response.success = True
        response.message = 'Đã dừng navigation (tạm thời)'
        self._publish_nav_status('cancelled', '')
        return response

    def _publish_pose(self):
        """Pose robot trong frame map — chỉ dùng TF."""
        for when in (self.get_clock().now(), rclpy.time.Time()):
            try:
                t = self._tf_buffer.lookup_transform(
                    'map',
                    'base_footprint',
                    when,
                    timeout=Duration(seconds=0.05),
                )
                break
            except TransformException:
                t = None
        if t is None:
            return

        msg = PoseWithCovarianceStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        msg.pose.pose.position.x = t.transform.translation.x
        msg.pose.pose.position.y = t.transform.translation.y
        msg.pose.pose.position.z = t.transform.translation.z
        msg.pose.pose.orientation = t.transform.rotation
        self._pose_pub.publish(msg)


def main():
    rclpy.init()
    node = NavPoseBridgeNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
