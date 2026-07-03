/**
 * teleop.js — Điều khiển thủ công qua /cmd_vel_web
 *
 * Luồng:
 *   Web publish /cmd_vel_web
 *     → twist_mux (priority 80)
 *     → diff_cont/cmd_vel_unstamped
 *
 * Init khi rosbridge connected (auto-connect hoặc bấm Kết nối).
 */

let teleopReady = false;

window.addEventListener('amr-ros-connected', () => {
  setTimeout(initTeleop, 200);
});

window.addEventListener('amr-ros-disconnected', () => {
  teleopReady = false;
});

function initTeleop() {
  if (teleopReady) return;
  teleopReady = true;

  const ros = window.AmrRos.getRos();
  if (!ros) {
    teleopReady = false;
    return;
  }

  const cmdVelPub = new ROSLIB.Topic({
    ros,
    name: '/cmd_vel_web',
    messageType: 'geometry_msgs/msg/Twist',
  });

  const slider = document.getElementById('speed-slider');
  const speedLabel = document.getElementById('speed-label');
  slider.addEventListener('input', () => {
    speedLabel.textContent = parseFloat(slider.value).toFixed(2);
  });

  const ANGULAR_SPEED = 0.4;
  const PUBLISH_HZ = 10;
  let publishTimer = null;

  function publishVel(linearX, angularZ) {
    cmdVelPub.publish(new ROSLIB.Message({
      linear:  { x: linearX, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: angularZ },
    }));
    window.dispatchEvent(new CustomEvent('amr-teleop-motion', {
      detail: { moving: Math.abs(linearX) > 0.001 },
    }));
  }

  function stop() {
    if (publishTimer) {
      clearInterval(publishTimer);
      publishTimer = null;
    }
    publishVel(0, 0);
  }

  function startHold(getLinear, getAngular) {
    stop();
    const tick = () => {
      const lx = typeof getLinear === 'function' ? getLinear() : getLinear;
      const az = typeof getAngular === 'function' ? getAngular() : getAngular;
      publishVel(lx, az);
    };
    tick();
    publishTimer = setInterval(tick, 1000 / PUBLISH_HZ);
  }

  const speed = () => parseFloat(slider.value);

  function bindDirectional(btnId, getLinear, getAngular) {
    const btn = document.getElementById(btnId);
    const onStart = (e) => {
      if (e.cancelable) e.preventDefault();
      startHold(getLinear, getAngular);
    };
    const onEnd = () => stop();

    btn.addEventListener('mousedown', onStart);
    btn.addEventListener('mouseup', onEnd);
    btn.addEventListener('touchstart', onStart, { passive: false });
    btn.addEventListener('touchend', onEnd);
    btn.addEventListener('touchcancel', onEnd);
  }

  bindDirectional('btn-forward', () => speed(), 0);
  bindDirectional('btn-back',    () => -speed(), 0);
  bindDirectional('btn-left',  0,  ANGULAR_SPEED);
  bindDirectional('btn-right', 0, -ANGULAR_SPEED);

  document.getElementById('btn-stop').addEventListener('click', stop);

  window.addEventListener('mouseup', () => {
    if (publishTimer) stop();
  });
}
