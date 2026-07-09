#!/usr/bin/env python3
"""Bridge Nav2 action + pose map frame cho web (rosbridge không gửi ROS2 action trực tiếp)."""

import math

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.action import ActionClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
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
        self.declare_parameter(
            'dock_dwb_bt_xml',
            get_package_share_directory('amr_lan_3') +
            '/behavior_trees/navigate_to_pose_dock_dwb.xml')

        self._nav_cb_group = MutuallyExclusiveCallbackGroup()
        self._action = ActionClient(
            self, NavigateToPose, 'navigate_to_pose',
            callback_group=self._nav_cb_group)
        self._goal_handle = None
        self._result_future = None
        self._nav_label = ''
        self._nav_finished = False

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

    def _send_goal_cb(self, request, response):
        x = float(request.x)
        y = float(request.y)
        yaw = float(request.yaw)
        controller_id = str(getattr(request, 'controller_id', '') or '').strip()
        label = f'{x:.2f},{y:.2f},{math.degrees(yaw):.1f}'

        if not self._action.server_is_ready():
            response.success = False
            response.message = 'Nav2 action /navigate_to_pose chưa sẵn sàng'
            self._publish_nav_status('failed', 'nav2_not_ready')
            return response

        if self._goal_handle is not None:
            self._nav_finished = True
            try:
                self._goal_handle.cancel_goal_async()
            except Exception as exc:
                self.get_logger().warn(f'cancel previous goal: {exc}')
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
        if controller_id == 'DockDWB':
            goal.behavior_tree = self.get_parameter('dock_dwb_bt_xml').value

        self._nav_label = label
        self._nav_finished = False
        send_future = self._action.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)

        response.success = True
        suffix = f' controller={controller_id}' if controller_id else ''
        response.message = f'Goal queued: ({x:.2f}, {y:.2f}) yaw={math.degrees(yaw):.1f}°{suffix}'
        return response

    def _cancel_cb(self, request, response):
        del request
        self._publish_nav_status('cancelling', '')

        if self._goal_handle is not None:
            self._nav_finished = True
            try:
                self._goal_handle.cancel_goal_async()
            except Exception as exc:
                self.get_logger().warn(f'cancel_goal_async lỗi: {exc}')

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
