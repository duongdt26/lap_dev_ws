/**
 * teleop.js — Điều khiển thủ công qua /cmd_vel_web
 * + Stop/Start: đè /cmd_vel_pause = 0 (không hủy Nav2)
 *
 * Luồng:
 *   Web publish /cmd_vel_web  → twist_mux priority 80
 *   Pause publish /cmd_vel_pause → twist_mux priority 90 (> nav)
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
  let pauseVelPub = null;
  let controlSocket = null;
  if (useApi) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    controlSocket = new WebSocket(`${protocol}//${window.location.host}/api/ws/control`);
    controlSocket.addEventListener('close', () => {
      if (publishTimer) stopMotion();
      clearNavPauseLocal();
      teleopReady = false;
    });
  } else {
    cmdVelPub = new ROSLIB.Topic({
      ros,
      name: '/cmd_vel_web',
      messageType: 'geometry_msgs/msg/Twist',
    });
    pauseVelPub = new ROSLIB.Topic({
      ros,
      name: '/cmd_vel_pause',
      messageType: 'geometry_msgs/msg/Twist',
    });
  }

  const slider = document.getElementById('speed-slider');
  const speedLabel = document.getElementById('speed-label');
  const angularSlider = document.getElementById('angular-slider');
  const angularLabel = document.getElementById('angular-label');
  const btnStop = document.getElementById('btn-stop');

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
  let pauseTimer = null;
  let navPaused = false;
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

  function publishPauseZero() {
    if (controlSocket) {
      // Server giữ timer 10 Hz khi paused=true
      return;
    }
    if (!pauseVelPub) return;
    pauseVelPub.publish(new ROSLIB.Message({
      linear:  { x: 0, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 0 },
    }));
  }

  function updateStopButtonUi() {
    if (!btnStop) return;
    if (navPaused) {
      btnStop.textContent = 'Start';
      btnStop.setAttribute('aria-label', 'Tiếp tục Nav2');
      btnStop.classList.add('teleop-start');
      btnStop.classList.remove('teleop-stop');
    } else {
      btnStop.textContent = 'Stop';
      btnStop.setAttribute('aria-label', 'Dừng đứng yên (giữ Nav2)');
      btnStop.classList.add('teleop-stop');
      btnStop.classList.remove('teleop-start');
    }
  }

  function clearNavPauseLocal() {
    if (pauseTimer) {
      clearInterval(pauseTimer);
      pauseTimer = null;
    }
    navPaused = false;
    updateStopButtonUi();
  }

  function setNavPaused(paused) {
    if (paused === navPaused) return navPaused;

    if (paused) {
      // Dừng lệnh teleop đang hold, bắt đầu đè 0 lên mux.
      stopMotion();
      if (controlSocket) {
        if (controlSocket.readyState === WebSocket.OPEN) {
          controlSocket.send(JSON.stringify({ type: 'nav_pause', paused: true }));
        }
      } else {
        publishPauseZero();
        if (!pauseTimer) {
          pauseTimer = setInterval(publishPauseZero, 1000 / PUBLISH_HZ);
        }
      }
      navPaused = true;
      updateStopButtonUi();
      window.dispatchEvent(new CustomEvent('amr-nav-pause', { detail: { paused: true } }));
      return true;
    }

    if (controlSocket) {
      if (controlSocket.readyState === WebSocket.OPEN) {
        controlSocket.send(JSON.stringify({ type: 'nav_pause', paused: false }));
      }
    } else if (pauseTimer) {
      clearInterval(pauseTimer);
      pauseTimer = null;
    }
    navPaused = false;
    updateStopButtonUi();
    window.dispatchEvent(new CustomEvent('amr-nav-pause', { detail: { paused: false } }));
    return false;
  }

  function toggleNavPause() {
    return setNavPaused(!navPaused);
  }

  function stopMotion() {
    if (publishTimer) {
      clearInterval(publishTimer);
      publishTimer = null;
    }
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

  /** Dừng teleop + bỏ pause (dùng cho EMERGENCY). */
  function stop() {
    setNavPaused(false);
    stopMotion();
  }

  function startHold(getLinear, getAngular) {
    // Teleop tay: nhả pause để điều khiển ưu tiên web.
    if (navPaused) setNavPaused(false);
    stopMotion();
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
      stopMotion();
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

  if (btnStop) {
    btnStop.addEventListener('click', () => toggleNavPause());
    updateStopButtonUi();
  }

  window.AmrTeleop = {
    stop,
    stopMotion,
    setNavPaused,
    toggleNavPause,
    isNavPaused: () => navPaused,
  };

  window.addEventListener('pointerup', () => {
    activePointerId = null;
    if (publishTimer) stopMotion();
  });
  window.addEventListener('pointercancel', () => {
    activePointerId = null;
    if (publishTimer) stopMotion();
  });
  window.addEventListener('blur', () => {
    activePointerId = null;
    if (publishTimer) stopMotion();
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
