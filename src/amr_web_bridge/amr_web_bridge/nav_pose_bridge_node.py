#!/usr/bin/env python3
"""Bridge Nav2 action + pose map frame cho web (rosbridge không gửi ROS2 action trực tiếp)."""

import math

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener
from tf2_ros import TransformException

from action_msgs.srv import CancelGoal
from action_msgs.msg import GoalInfo
from unique_identifier_msgs.msg import UUID
from geometry_msgs.msg import Twist


class NavPoseBridgeNode(Node):
    def __init__(self):
        super().__init__('nav_pose_bridge_node')

        # Web set x,y,yaw trước khi gọi /send_nav_goal (giống map_name)
        self.declare_parameter('goal_x', 0.0)
        self.declare_parameter('goal_y', 0.0)
        self.declare_parameter('goal_yaw', 0.0)

        self._action = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self._goal_handle = None

        self.create_service(Trigger, '/send_nav_goal', self._send_goal_cb)
        self.create_service(Trigger, '/cancel_nav', self._cancel_cb)

        # Tạo sẵn client/publisher — tránh hasattr + import trong callback
        self._cancel_goal_cli = self.create_client(
            CancelGoal, '/navigate_to_pose/_action/cancel_goal')
        self._stop_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        from nav_msgs.msg import Path
        self._plan_clear_pub = self.create_publisher(Path, '/web_plan_clear', 10)

        # Pose robot trong frame map — web subscribe thay cho TF
        self._pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, '/robot_pose_map', 10)
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        # self.create_timer(0.1, self._publish_pose)  # 10 Hz, đủ real-time

        # self.get_logger().info('Services: /send_nav_goal, /cancel_nav')
        # self.get_logger().info('Topic: /robot_pose_map (10 Hz)')
        self.create_timer(0.25, self._publish_pose)  # 4 Hz, đủ real-time

        self.get_logger().info('Services: /send_nav_goal, /cancel_nav')
        self.get_logger().info('Topic: /robot_pose_map (4 Hz)')

    def _yaw_to_quat(self, yaw):
        return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))

    def _send_goal_cb(self, request, response):
        del request
        x = self.get_parameter('goal_x').value
        y = self.get_parameter('goal_y').value
        yaw = self.get_parameter('goal_yaw').value

        if not self._action.wait_for_server(timeout_sec=2.0):
            response.success = False
            response.message = 'Nav2 action /navigate_to_pose chưa sẵn sàng'
            return response

        # Huỷ goal cũ nếu có
        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        qx, qy, qz, qw = self._yaw_to_quat(float(yaw))
        goal.pose.pose.orientation.x = qx
        goal.pose.pose.orientation.y = qy
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw

        send_future = self._action.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=5.0)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            response.success = False
            response.message = 'Goal bị Nav2 từ chối'
            return response

        self._goal_handle = goal_handle
        response.success = True
        response.message = f'Goal accepted: ({x:.2f}, {y:.2f}) yaw={math.degrees(yaw):.1f}°'
        return response

    def _cancel_cb(self, request, response):
        del request

        # 1) Huỷ goal do bridge này gửi
        if self._goal_handle is not None:
            cancel_future = self._goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=2.0)
            self._goal_handle = None

        # 2) Huỷ MỌI goal (kể cả RViz) — dùng CancelGoal đã import ở đầu file
        if self._cancel_goal_cli.wait_for_service(timeout_sec=1.0):
            req = CancelGoal.Request()
            req.goal_info = GoalInfo()
            req.goal_info.goal_id.uuid = [0] * 16
            future = self._cancel_goal_cli.call_async(req)
            rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)

        # 3) Dừng robot ngay
        stop = Twist()
        for _ in range(5):
            self._stop_pub.publish(stop)

        # 4) Báo web xóa path trên canvas
        from nav_msgs.msg import Path
        empty_plan = Path()
        empty_plan.header.frame_id = 'map'
        self._plan_clear_pub.publish(empty_plan)

        response.success = True
        response.message = 'Đã huỷ navigation'
        return response

    # def _cancel_cb(self, request, response):
    #     del request
    #     if self._goal_handle is not None:
    #         cancel_future = self._goal_handle.cancel_goal_async()
    #         rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=2.0)
    #         self._goal_handle = None

    #     # Fallback: dừng robot ngay (Nav2 sẽ dừng sau vài giây nếu action cancel chậm)
    #     from geometry_msgs.msg import Twist
    #     pub = self.create_publisher(Twist, '/cmd_vel', 10)
    #     stop = Twist()
    #     for _ in range(5):
    #         pub.publish(stop)

    #     response.success = True
    #     response.message = 'Đã huỷ navigation'
    #     return response

    def _publish_pose(self):
        try:
            t = self._tf_buffer.lookup_transform(
                'map', 'base_footprint', rclpy.time.Time())
        except TransformException:
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
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()