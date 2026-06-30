#!/usr/bin/env python3
"""Bridge Nav2 action + pose map frame cho web (rosbridge không gửi ROS2 action trực tiếp)."""

import math

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from action_msgs.msg import GoalInfo, GoalStatus
from action_msgs.srv import CancelGoal
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
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

        self._executor = None
        self._cb_group = ReentrantCallbackGroup()
        self._action = ActionClient(
            self, NavigateToPose, 'navigate_to_pose',
            callback_group=self._cb_group)
        self._goal_handle = None
        self._result_future = None
        self._nav_label = ''
        self._nav_finished = False

        self.create_service(
            SendNavGoal, '/send_nav_goal', self._send_goal_cb,
            callback_group=self._cb_group)
        self.create_service(
            Trigger, '/cancel_nav', self._cancel_cb,
            callback_group=self._cb_group)

        self._cancel_goal_cli = self.create_client(
            CancelGoal, '/navigate_to_pose/_action/cancel_goal',
            callback_group=self._cb_group)
        self._stop_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self._plan_clear_pub = self.create_publisher(Path, '/web_plan_clear', 10)
        self._nav_status_pub = self.create_publisher(String, '/web_nav_status', 10)

        self._pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, '/robot_pose_map', 10)
        self._tf_buffer = Buffer(cache_time=Duration(seconds=30.0))
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self.create_timer(0.1, self._publish_pose, callback_group=self._cb_group)
        self.create_timer(0.15, self._poll_nav_goal, callback_group=self._cb_group)

        use_sim = self.get_parameter('use_sim_time').value
        self.get_logger().info(f'use_sim_time={use_sim}')
        self.get_logger().info(
            'Services: /send_nav_goal | Topics: /robot_pose_map, /web_nav_status'
        )

    def set_executor(self, executor):
        self._executor = executor

    def _spin_until(self, future, timeout_sec):
        if self._executor is None:
            self.get_logger().error('executor chưa gán — dùng spin_until_future_complete không an toàn')
            return False
        rclpy.spin_until_future_complete(
            self, future, executor=self._executor, timeout_sec=timeout_sec)
        return future.done()

    def _publish_nav_status(self, status: str, detail: str = ''):
        msg = String()
        msg.data = f'{status}|{detail}' if detail else status
        self._nav_status_pub.publish(msg)
        self.get_logger().info(f'nav status: {msg.data}')

    def _yaw_to_quat(self, yaw):
        return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))

    def _clear_nav_track(self):
        self._goal_handle = None
        self._result_future = None
        self._nav_label = ''
        self._nav_finished = False

    def _finish_nav(self, status: str, label: str):
        if self._nav_finished:
            return
        self._nav_finished = True
        self._publish_nav_status(status, label)
        self._clear_nav_track()

    def _on_result_future(self, future):
        if self._nav_finished:
            return
        try:
            result = future.result()
            goal_status = result.status
        except Exception as exc:
            self.get_logger().error(f'nav result error: {exc}')
            self._finish_nav('failed', str(exc))
            return

        label = self._nav_label
        if goal_status == GoalStatus.STATUS_SUCCEEDED:
            self._finish_nav('arrived', label)
        elif goal_status == GoalStatus.STATUS_CANCELED:
            self._finish_nav('cancelled', label)
        else:
            self._finish_nav('failed', f'status_{goal_status}')

    def _poll_nav_goal(self):
        if self._goal_handle is None or self._nav_finished:
            return

        status = self._goal_handle.status
        label = self._nav_label

        if status == GoalStatus.STATUS_SUCCEEDED:
            self._finish_nav('arrived', label)
            return

        if status in (
            GoalStatus.STATUS_CANCELED,
            GoalStatus.STATUS_ABORTED,
        ):
            state = 'cancelled' if status == GoalStatus.STATUS_CANCELED else 'failed'
            self._finish_nav(state, label)
            return

        if self._result_future is not None and self._result_future.done():
            self._on_result_future(self._result_future)

    def _send_goal_cb(self, request, response):
        x = float(request.x)
        y = float(request.y)
        yaw = float(request.yaw)
        label = f'{x:.2f},{y:.2f},{math.degrees(yaw):.1f}'

        if not self._action.wait_for_server(timeout_sec=2.0):
            response.success = False
            response.message = 'Nav2 action /navigate_to_pose chưa sẵn sàng'
            self._publish_nav_status('failed', 'nav2_not_ready')
            return response

        if self._goal_handle is not None:
            self._nav_finished = True
            self._goal_handle.cancel_goal_async()
        self._clear_nav_track()

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

        send_future = self._action.send_goal_async(goal)
        if not self._spin_until(send_future, timeout_sec=5.0):
            response.success = False
            response.message = 'Timeout chờ Nav2 chấp nhận goal'
            self._publish_nav_status('failed', 'accept_timeout')
            return response

        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            response.success = False
            response.message = 'Goal bị Nav2 từ chối'
            self._publish_nav_status('failed', 'rejected')
            return response

        self._goal_handle = goal_handle
        self._nav_label = label
        self._nav_finished = False
        self._result_future = goal_handle.get_result_async()
        self._result_future.add_done_callback(self._on_result_future)

        self._publish_nav_status('navigating', label)

        response.success = True
        response.message = (
            f'Goal accepted: ({x:.2f}, {y:.2f}) yaw={math.degrees(yaw):.1f}°'
        )
        return response

    def _cancel_cb(self, request, response):
        del request
        self._publish_nav_status('cancelling', '')

        if self._goal_handle is not None:
            cancel_future = self._goal_handle.cancel_goal_async()
            self._spin_until(cancel_future, timeout_sec=2.0)

        self._clear_nav_track()

        if self._cancel_goal_cli.wait_for_service(timeout_sec=1.0):
            req = CancelGoal.Request()
            req.goal_info = GoalInfo()
            req.goal_info.goal_id.uuid = [0] * 16
            future = self._cancel_goal_cli.call_async(req)
            self._spin_until(future, timeout_sec=2.0)

        stop = Twist()
        for _ in range(5):
            self._stop_pub.publish(stop)

        empty_plan = Path()
        empty_plan.header.frame_id = 'map'
        self._plan_clear_pub.publish(empty_plan)

        response.success = True
        response.message = 'Đã huỷ navigation'
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
    executor = MultiThreadedExecutor(num_threads=4)
    node.set_executor(executor)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
