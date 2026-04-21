import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
import math

class LaserFilterNode(Node):
    def __init__(self):
        super().__init__('laser_filter_node')

        # Subscribe to receive "raw data" from Gazebo
        self.subscription = self.create_subscription(
            LaserScan,
            '/scan',
            self.listener_callback,
            10
        )

        # where publish "cleaned data" or "filtered data"
        self.publisher = self.create_publisher(LaserScan, '/scan_filtered', 10)
        self.get_logger().info("Laser Filter of Duo was started!!!")

    def  listener_callback(self, msg):
        # Create a new message to contain "filtered data"
        filtered_msg = LaserScan()

        # Copy metadata's parameters from root message
        filtered_msg.header = msg.header
        filtered_msg.angle_min = msg.angle_min
        filtered_msg.angle_max = msg.angle_max
        filtered_msg.angle_increment = msg.angle_increment
        filtered_msg.time_increment= msg.time_increment
        filtered_msg.scan_time = msg.scan_time
        filtered_msg.range_min = msg.range_min
        filtered_msg.range_max = msg.range_max

        # Convert tuple range to list in order to be modified
        new_ranges = list(msg.ranges)

        # Size of robot AMR's frame
        box_x_min, box_x_max = -0.7, 0.7 
        box_y_min, box_y_max = -0.35, 0.35

        for i in range (len(new_ranges)):
            r = new_ranges[i]

            # Passing invalid point (out range or in robot frame)
            if r < msg.range_min or r > msg.range_max or math.isinf(r) or math.isnan(r):
                continue

            # Calculate current scan angle
            angle = msg.angle_min + (i * msg.angle_increment)

            # Point coordinate in laser_frame
            x_l = r * math.cos(angle)
            y_l = r * math.sin(angle)

            # Convert coordinate to baselink (based on xyz and rpy parameters in xacro)
            x_base = -x_l + 0.545
            y_base = -y_l + 0.2925
            # x_base = -x_l + 0.2925
            # y_base = -y_l + 0.545

            # Check if current point into robot Frame
            if ((box_x_min <= x_base <= box_x_max) and (box_y_min <= y_base <= box_y_max)):
                # If have, convert to inf (no obstacle)
                new_ranges[i] = float('inf')

        filtered_msg.ranges = new_ranges
        # Keep intensities (if have)
        filtered_msg.intensities = msg.intensities 
        
        # Publish filtered data
        self.publisher.publish(filtered_msg)

def main(args=None):
    rclpy.init(args=args)
    node = LaserFilterNode()
    rclpy.spin(node=node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()