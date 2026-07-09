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
  let activePointerId = null;

  function publishVel(linearX, angularZ) {
    cmdVelPub.publish(new ROSLIB.Message({
      linear:  { x: linearX, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: angularZ },
    }));
    window.dispatchEvent(new CustomEvent('amr-teleop-motion', {
      detail: {
        moving: Math.abs(linearX) > 0.001 || Math.abs(angularZ) > 0.001,
      },
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
      if (e.pointerId !== undefined) {
        if (activePointerId !== null) return;
        activePointerId = e.pointerId;
        btn.setPointerCapture?.(e.pointerId);
      }
      startHold(getLinear, getAngular);
    };
    const onEnd = (e) => {
      if (e?.cancelable) e.preventDefault();
      if (e?.pointerId !== undefined && e.pointerId !== activePointerId) return;
      if (e?.pointerId !== undefined) {
        try {
          btn.releasePointerCapture?.(e.pointerId);
        } catch (_) {
          // Pointer capture may already be gone after a mobile cancel/lost event.
        }
      }
      activePointerId = null;
      stop();
    };

    btn.addEventListener('pointerdown', onStart);
    btn.addEventListener('pointerup', onEnd);
    btn.addEventListener('pointercancel', onEnd);
    btn.addEventListener('lostpointercapture', onEnd);
    btn.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  bindDirectional('btn-forward', () => speed(), 0);
  bindDirectional('btn-back',    () => -speed(), 0);
  bindDirectional('btn-left',  0,  ANGULAR_SPEED);
  bindDirectional('btn-right', 0, -ANGULAR_SPEED);

  document.getElementById('btn-stop').addEventListener('click', stop);

  window.addEventListener('pointerup', () => {
    activePointerId = null;
    if (publishTimer) stop();
  });
  window.addEventListener('pointercancel', () => {
    activePointerId = null;
    if (publishTimer) stop();
  });
  window.addEventListener('blur', () => {
    activePointerId = null;
    if (publishTimer) stop();
  });
}
