/**
 * status.js — Đọc odom và pose, hiển thị lên panel
 *
 * Init khi rosbridge connected (auto-connect hoặc bấm Kết nối).
 */

let statusReady = false;

function fmtNum(value, decimals) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '--';
  const threshold = 0.5 * Math.pow(10, -decimals);
  if (Math.abs(n) < threshold) return (0).toFixed(decimals);
  return n.toFixed(decimals);
}

window.addEventListener('amr-ros-connected', () => {
  setTimeout(startSubscriptions, 200);
});

window.addEventListener('amr-ros-disconnected', () => {
  statusReady = false;
});

function startSubscriptions() {
  if (statusReady) return;
  statusReady = true;

  const ros = window.AmrRos.getRos();
  if (!ros) {
    statusReady = false;
    return;
  }

  const odomTopic = new ROSLIB.Topic({
    ros,
    name: '/odometry/filtered',
    messageType: 'nav_msgs/msg/Odometry',
  });

  odomTopic.subscribe((msg) => {
    const vx = msg.twist.twist.linear.x;
    const vyaw = msg.twist.twist.angular.z;
    document.getElementById('val-vx').textContent = fmtNum(vx, 2);
    document.getElementById('val-vyaw').textContent = fmtNum(vyaw, 1);
    window.dispatchEvent(new CustomEvent('amr-odom', {
      detail: { vx, vyaw },
    }));
  });

  const poseTopic = new ROSLIB.Topic({
    ros,
    name: '/amcl_pose',
    messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
  });

  poseTopic.subscribe((msg) => {
    const p = msg.pose.pose.position;
    const q = msg.pose.pose.orientation;
    const yawDeg = quaternionToYaw(q);

    document.getElementById('val-x').textContent = p.x.toFixed(2);
    document.getElementById('val-y').textContent = p.y.toFixed(2);
    document.getElementById('val-yaw').textContent = yawDeg.toFixed(1);

    window.__amrPose = { x: p.x, y: p.y, yawDeg };
    window.dispatchEvent(new CustomEvent('amr-pose', {
      detail: window.__amrPose,
    }));
  });
}

function quaternionToYaw(q) {
  const siny = 2 * (q.w * q.z + q.x * q.y);
  const cosy = 1 - 2 * (q.y * q.y + q.z * q.z);
  return (Math.atan2(siny, cosy) * 180) / Math.PI;
}
