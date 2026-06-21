/**
 * status.js — Đọc odom và pose, hiển thị lên panel
 *
 * Topic odom: EKF publish /odometry/filtered (KHÔNG phải /odom_filtered)
 * Topic pose: AMCL publish /amcl_pose (cần localization đang chạy)
 */

// Đợi user bấm "Kết nối" rồi mới subscribe
document.getElementById('btn-connect').addEventListener('click', () => {
    // Delay nhỏ để ros kịp connect
    setTimeout(startSubscriptions, 500);
  });
  
  function startSubscriptions() {
    const ros = window.AmrRos.getRos();
    if (!ros) return;
  
    // ── 1. Tốc độ từ odom đã lọc (EKF) ──
    const odomTopic = new ROSLIB.Topic({
      ros,
      name: '/odometry/filtered',
      messageType: 'nav_msgs/msg/Odometry',
    });
  
    odomTopic.subscribe((msg) => {
      // twist.linear.x  = vận tốc tiến (m/s)
      // twist.angular.z = vận tốc quay (rad/s)
      document.getElementById('val-vx').textContent =
        msg.twist.twist.linear.x.toFixed(3);
      document.getElementById('val-vyaw').textContent =
        msg.twist.twist.angular.z.toFixed(3);
    });
  
    // ── 2. Vị trí từ AMCL (chỉ có khi localization chạy) ──
    const poseTopic = new ROSLIB.Topic({
      ros,
      name: '/amcl_pose',
      messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
    });
  
    poseTopic.subscribe((msg) => {
      const p = msg.pose.pose.position;
      const q = msg.pose.pose.orientation;
  
      document.getElementById('val-x').textContent = p.x.toFixed(2);
      document.getElementById('val-y').textContent = p.y.toFixed(2);
  
      // Đổi quaternion → góc yaw (độ)
      const yaw = quaternionToYaw(q);
      document.getElementById('val-yaw').textContent = yaw.toFixed(1);
    });
  
    // Pin: chưa có topic → giữ N/A (thêm ở bước sau khi có driver pin)
  }
  
  /** Chuyển quaternion ROS → yaw (độ) */
  function quaternionToYaw(q) {
    const siny = 2 * (q.w * q.z + q.x * q.y);
    const cosy = 1 - 2 * (q.y * q.y + q.z * q.z);
    return (Math.atan2(siny, cosy) * 180) / Math.PI;
  }