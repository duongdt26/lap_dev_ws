/**
 * status.js — Đọc odom, pose và pin, hiển thị lên HUD
 *
 * Pose: nhận từ amr-pose (map.js /robot_pose_map) — tránh subscribe trùng /amcl_pose.
 * Pin: /battery_state (sensor_msgs/BatteryState) nếu có node PZEM.
 */

let statusReady = false;
let telemetrySocket = null;

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

function updateBatteryPanel(msg) {
  const el = document.getElementById('val-battery');
  if (!el) return;
  let pct = Number(msg?.percentage);
  if (!Number.isFinite(pct)) {
    el.textContent = 'N/A';
    return;
  }
  // ROS BatteryState.percentage thường 0..1; một số driver gửi 0..100
  if (pct <= 1.0) pct *= 100;
  pct = Math.max(0, Math.min(100, pct));
  el.textContent = `${Math.round(pct)}%`;
}

window.addEventListener('amr-pose', (e) => {
  updatePosePanel(e.detail);
});

window.addEventListener('amr-ros-connected', () => {
  setTimeout(startSubscriptions, 200);
});

window.addEventListener('amr-auth-ready', () => {
  setTimeout(startSubscriptions, 200);
});

window.addEventListener('amr-ros-disconnected', () => {
  statusReady = false;
  telemetrySocket?.close();
  telemetrySocket = null;
  const bat = document.getElementById('val-battery');
  if (bat) bat.textContent = 'N/A';
});

function startSubscriptions() {
  if (statusReady) return;
  statusReady = true;

  const useApi = !!window.AmrApi?.isAvailable?.() && !!window.AmrApi?.getUser?.();
  const ros = window.AmrRos?.getRos?.();
  if (useApi) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    telemetrySocket = new WebSocket(`${protocol}//${window.location.host}/api/ws/telemetry`);
    telemetrySocket.addEventListener('message', (event) => {
      const snapshot = JSON.parse(event.data || '{}');
      if (snapshot.pose) {
        updatePosePanel(snapshot.pose);
        window.dispatchEvent(new CustomEvent('amr-pose', { detail: snapshot.pose }));
      }
      if (snapshot.battery) updateBatteryPanel(snapshot.battery);
      if (snapshot.odometry) {
        const vx = Number(snapshot.odometry.linearX);
        const vyaw = Number(snapshot.odometry.angularZ);
        document.getElementById('val-vx').textContent = fmtNum(vx, 2);
        document.getElementById('val-vyaw').textContent = fmtNum(vyaw, 1);
        window.dispatchEvent(new CustomEvent('amr-odom', { detail: { vx, vyaw } }));
      }
      if (snapshot.navigation) {
        const parts = String(snapshot.navigation).split('|');
        window.dispatchEvent(new CustomEvent('amr-nav-status', {
          detail: { state: parts[0] || '', detail: parts.slice(1).join('|') },
        }));
      }
    });
    telemetrySocket.addEventListener('close', () => { statusReady = false; });
    return;
  }
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

  const batteryTopic = new ROSLIB.Topic({
    ros,
    name: '/battery_state',
    messageType: 'sensor_msgs/msg/BatteryState',
  });
  batteryTopic.subscribe((msg) => updateBatteryPanel(msg));

  if (window.__amrPose) {
    updatePosePanel(window.__amrPose);
  }
}
