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

window.addEventListener('amr-auth-ready', () => {
  setTimeout(initTeleop, 200);
});

window.addEventListener('amr-ros-disconnected', () => {
  teleopReady = false;
});

function updateRangeFill(el) {
  if (!el) return;
  const min = parseFloat(el.min) || 0;
  const max = parseFloat(el.max) || 1;
  const val = parseFloat(el.value);
  const pct = ((val - min) / (max - min)) * 100;
  el.style.setProperty('--range-pct', `${pct}%`);
}

function initTeleop() {
  if (teleopReady) return;
  teleopReady = true;

  const useApi = !!window.AmrApi?.isAvailable?.() && !!window.AmrApi?.getUser?.();
  const ros = window.AmrRos?.getRos?.();
  if (!ros && !useApi) {
    teleopReady = false;
    return;
  }

  let cmdVelPub = null;
  let controlSocket = null;
  if (useApi) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    controlSocket = new WebSocket(`${protocol}//${window.location.host}/api/ws/control`);
    controlSocket.addEventListener('close', () => {
      if (publishTimer) stop();
      teleopReady = false;
    });
  } else {
    cmdVelPub = new ROSLIB.Topic({
      ros,
      name: '/cmd_vel_web',
      messageType: 'geometry_msgs/msg/Twist',
    });
  }

  const slider = document.getElementById('speed-slider');
  const speedLabel = document.getElementById('speed-label');
  const angularSlider = document.getElementById('angular-slider');
  const angularLabel = document.getElementById('angular-label');

  function syncSpeedUi() {
    speedLabel.textContent = parseFloat(slider.value).toFixed(2);
    updateRangeFill(slider);
  }
  function syncAngularUi() {
    angularLabel.textContent = parseFloat(angularSlider.value).toFixed(2);
    updateRangeFill(angularSlider);
  }

  slider.addEventListener('input', syncSpeedUi);
  angularSlider.addEventListener('input', syncAngularUi);
  syncSpeedUi();
  syncAngularUi();

  const PUBLISH_HZ = 10;
  let publishTimer = null;
  let activePointerId = null;

  function publishVel(linearX, angularZ) {
    if (controlSocket) {
      if (controlSocket.readyState !== WebSocket.OPEN) return;
      controlSocket.send(JSON.stringify({ type: 'teleop', linearX, angularZ }));
    } else {
      cmdVelPub.publish(new ROSLIB.Message({
        linear:  { x: linearX, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: angularZ },
      }));
    }
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
    // Luôn gửi vận tốc 0 xuống xe khi bấm Stop.
    if (controlSocket) {
      if (controlSocket.readyState === WebSocket.OPEN) {
        controlSocket.send(JSON.stringify({ type: 'teleop', linearX: 0, angularZ: 0 }));
        controlSocket.send(JSON.stringify({ type: 'stop' }));
      }
      window.dispatchEvent(new CustomEvent('amr-teleop-motion', {
        detail: { moving: false },
      }));
    } else if (cmdVelPub) {
      publishVel(0, 0);
    } else {
      window.dispatchEvent(new CustomEvent('amr-teleop-motion', {
        detail: { moving: false },
      }));
    }
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
  const angularSpeed = () => parseFloat(angularSlider.value);

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
  bindDirectional('btn-left',  0,  () => angularSpeed());
  bindDirectional('btn-right', 0, () => -angularSpeed());

  document.getElementById('btn-stop').addEventListener('click', stop);

  window.AmrTeleop = { stop };

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

// Fill thanh ngay cả trước khi ROS connect
document.addEventListener('DOMContentLoaded', () => {
  ['speed-slider', 'angular-slider'].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const sync = () => {
      const min = parseFloat(el.min) || 0;
      const max = parseFloat(el.max) || 1;
      const pct = ((parseFloat(el.value) - min) / (max - min)) * 100;
      el.style.setProperty('--range-pct', `${pct}%`);
    };
    el.addEventListener('input', sync);
    sync();
  });
});
