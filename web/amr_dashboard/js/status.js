/**
 * status.js — Đọc odom và pose, hiển thị lên panel
 *
 * Pose: nhận từ amr-pose (map.js /robot_pose_map) — tránh subscribe trùng /amcl_pose.
 */

let statusReady = false;

function fmtNum(value, decimals) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '--';
  const threshold = 0.5 * Math.pow(10, -decimals);
  if (Math.abs(n) < threshold) return (0).toFixed(decimals);
  return n.toFixed(decimals);
}

function updatePosePanel(pose) {
  if (!pose || pose.x == null) return;
  document.getElementById('val-x').textContent = Number(pose.x).toFixed(2);
  document.getElementById('val-y').textContent = Number(pose.y).toFixed(2);
  document.getElementById('val-yaw').textContent = Number(pose.yawDeg).toFixed(1);
}

window.addEventListener('amr-pose', (e) => {
  updatePosePanel(e.detail);
});

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

  if (window.__amrPose) {
    updatePosePanel(window.__amrPose);
  }
}
