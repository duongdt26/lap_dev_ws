// /**
//  * navigation.js — Gửi goal tới Nav2 + hiển thị trạng thái
//  *
//  * Dùng ROSLIB.ActionClient → /navigate_to_pose
//  * Canvas click+drag trong nav mode → gửi goal
//  */

// const btnNavMode   = document.getElementById('btn-nav-mode');
// const btnNavCancel = document.getElementById('btn-nav-cancel');
// const navStatus    = document.getElementById('nav-status');

// let navClient  = null;
// let currentGoal = null;
// let navMode    = false;

// function updateNavStatus(msg, color = '#888') {
//   navStatus.textContent = msg;
//   navStatus.style.color = color;
// }

// function sendNavGoal(wx, wy, yaw) {
//   if (!navClient) { updateNavStatus('Chưa kết nối Nav2', '#f87171'); return; }
//   if (currentGoal) { currentGoal.cancel(); currentGoal = null; }

//   const q = { x: 0, y: 0, z: Math.sin(yaw / 2), w: Math.cos(yaw / 2) };
//   const goal = new ROSLIB.Goal({
//     actionClient: navClient,
//     goalMessage: {
//       pose: {
//         header: { stamp: { sec: 0, nanosec: 0 }, frame_id: 'map' },
//         pose: { position: { x: wx, y: wy, z: 0 }, orientation: q },
//       },
//       behavior_tree: '',
//     },
//   });

//   goal.on('feedback', (fb) => {
//     const d = (fb.current_pose) ? '' : '';
//     updateNavStatus(`Đang đi... còn ${(fb.distance_remaining || 0).toFixed(2)}m`, '#facc15');
//   });
//   goal.on('result', () => {
//     updateNavStatus('Đã đến đích ✓', '#4ade80');
//     currentGoal = null;
//     setNavMode(false);
//   });

//   goal.send();
//   currentGoal = goal;
//   updateNavStatus(`Goal: (${wx.toFixed(2)}, ${wy.toFixed(2)}) yaw=${(yaw * 180 / Math.PI).toFixed(0)}°`, '#facc15');
// }

// function setNavMode(enabled) {
//   navMode = enabled;
//   btnNavMode.textContent = `Nav mode: ${enabled ? 'BẬT' : 'TẮT'}`;
//   btnNavMode.classList.toggle('active', enabled);
//   if (window.AmrMap) window.AmrMap.setNavMode(enabled);
//   // Tắt pose mode khi bật nav mode
//   if (enabled && window.AmrLocalization) {
//     document.getElementById('btn-pose-mode').textContent = 'Đặt vị trí ban đầu: TẮT';
//     if (window.AmrMap) window.AmrMap.setPoseMode(false);
//   }
// }

// btnNavMode.addEventListener('click', () => setNavMode(!navMode));

// btnNavCancel.addEventListener('click', () => {
//   if (currentGoal) { currentGoal.cancel(); currentGoal = null; }
//   updateNavStatus('Đã huỷ goal', '#f87171');
//   setNavMode(false);
// });

// window.addEventListener('amr-ros-connected', () => {
//   const ros = window.AmrRos.getRos();
//   if (!ros) return;
//   navClient = new ROSLIB.ActionClient({
//     ros,
//     serverName: '/navigate_to_pose',
//     actionName: 'nav2_msgs/action/NavigateToPose',
//   });
//   if (window.AmrMap) window.AmrMap.setNavGoalCallback(sendNavGoal);
//   updateNavStatus('Sẵn sàng', '#4ade80');
// });

// window.AmrNavigation = { sendNavGoal, setNavMode };

/**
 * navigation.js — Gửi goal tới Nav2 + huỷ điều hướng
 */

// const btnNavMode   = document.getElementById('btn-nav-mode');
// const btnNavCancel = document.getElementById('btn-nav-cancel');
// const navStatus    = document.getElementById('nav-status');

// let navClient   = null;
// let currentGoal = null;
// // Đổi tên: KHÔNG dùng "navMode" — map.js đã dùng biến đó
// let navUiOn     = false;

// function updateNavStatus(msg, color = '#888') {
//   navStatus.textContent = msg;
//   navStatus.style.color = color;
// }

// function sendNavGoal(wx, wy, yaw) {
//   if (!navClient) { updateNavStatus('Chưa kết nối Nav2', '#f87171'); return; }
//   if (currentGoal) { currentGoal.cancel(); currentGoal = null; }

//   const q = { x: 0, y: 0, z: Math.sin(yaw / 2), w: Math.cos(yaw / 2) };
//   const goal = new ROSLIB.Goal({
//     actionClient: navClient,
//     goalMessage: {
//       pose: {
//         header: { stamp: { sec: 0, nanosec: 0 }, frame_id: 'map' },
//         pose: { position: { x: wx, y: wy, z: 0 }, orientation: q },
//       },
//       behavior_tree: '',
//     },
//   });

//   goal.on('feedback', (fb) => {
//     updateNavStatus(`Đang đi... còn ${(fb.distance_remaining || 0).toFixed(2)}m`, '#facc15');
//   });
//   goal.on('result', (result) => {
//     if (result.status === 2) { // PREEMPTED = bị huỷ
//       updateNavStatus('Đã huỷ goal', '#f87171');
//     } else {
//       updateNavStatus('Đã đến đích ✓', '#4ade80');
//     }
//     currentGoal = null;
//     setNavMode(false);
//   });
//   goal.on('timeout', () => {
//     updateNavStatus('Timeout — Nav2 có chạy?', '#f87171');
//     currentGoal = null;
//   });

//   goal.send();
//   currentGoal = goal;
//   updateNavStatus(`Goal: (${wx.toFixed(2)}, ${wy.toFixed(2)}) yaw=${(yaw * 180 / Math.PI).toFixed(0)}°`, '#facc15');
// }

// function setNavMode(enabled) {
//   navUiOn = enabled;
//   btnNavMode.textContent = `Nav mode: ${enabled ? 'BẬT' : 'TẮT'}`;
//   btnNavMode.classList.toggle('active', enabled);
//   if (window.AmrMap) window.AmrMap.setNavMode(enabled);
//   // Bật nav → tắt pose
//   if (enabled && window.AmrLocalization) {
//     window.AmrLocalization.setPoseUiOn(false);
//   }
// }

// /** Huỷ mọi goal đang chạy (kể cả goal gửi từ RViz) */
// function cancelNavigation() {
//   if (currentGoal) {
//     currentGoal.cancel();
//     currentGoal = null;
//   }
//   // Quan trọng: huỷ TẤT CẢ goal trên action server
//   if (navClient && typeof navClient.cancelAllGoals === 'function') {
//     navClient.cancelAllGoals();
//   }
//   updateNavStatus('Đã huỷ goal', '#f87171');
//   setNavMode(false);
// }

// btnNavMode.addEventListener('click', () => setNavMode(!navUiOn));
// btnNavCancel.addEventListener('click', cancelNavigation);

// window.addEventListener('amr-ros-connected', () => {
//   const ros = window.AmrRos.getRos();
//   if (!ros) return;

//   navClient = new ROSLIB.ActionClient({
//     ros,
//     serverName: '/navigate_to_pose',
//     actionName: 'nav2_msgs/action/NavigateToPose',
//   });

//   // Đợi map.js tạo AmrMap (initMap chạy cùng event)
//   function wireNavCallback() {
//     if (window.AmrMap) {
//       window.AmrMap.setNavGoalCallback(sendNavGoal);
//       updateNavStatus('Sẵn sàng', '#4ade80');
//     } else {
//       setTimeout(wireNavCallback, 100);
//     }
//   }
//   wireNavCallback();
// });

// window.AmrNavigation = { sendNavGoal, setNavMode, cancelNavigation };


/**
 * navigation.js — Gửi/huỷ Nav2 qua service (ROS2 action qua rosbridge không ổn định)
 */

const btnNavMode   = document.getElementById('btn-nav-mode');
const btnNavCancel = document.getElementById('btn-nav-cancel');
const navStatus    = document.getElementById('nav-status');

let sendGoalClient  = null;
let cancelNavClient = null;
let navUiOn = false;
let navStatusTopic  = null;

function useNavigationApi() {
  return !!window.AmrApi?.isAvailable?.() && !!window.AmrApi?.getUser?.();
}

function parseNavStatus(data) {
  const parts = (data || '').split('|');
  return { state: parts[0] || '', detail: parts.slice(1).join('|') };
}

function dispatchNavStatus(state, detail) {
  window.dispatchEvent(
    new CustomEvent('amr-nav-status', { detail: { state, detail } })
  );
}

function renderNavStatusEvent(event) {
  const { state, detail } = event.detail || {};
  if (state === 'navigating') {
    const destName = findSetpointNameByLabel(detail);
    updateNavStatus(destName ? `Đang đi tới ${destName}...` : `Navigating... ${detail}`, '#facc15');
  } else if (state === 'arrived') {
    notifyNavArrived(detail);
  } else if (state === 'failed') {
    updateNavStatus(`Nav failed: ${detail}`, '#f87171');
  } else if (state === 'cancelled' || state === 'cancelling') {
    updateNavStatus('Navigation cancelled', '#f87171');
  }
}

window.addEventListener('amr-nav-status', renderNavStatusEvent);

function updateNavStatus(msg, color = '#888') {
  navStatus.textContent = msg;
  navStatus.style.color = color;
}

function callSendNavGoal(wx, wy, yaw, options = {}) {
  return new Promise((resolve, reject) => {
    if (useNavigationApi()) {
      window.AmrApi.request('/api/navigation/goal', {
        method: 'POST',
        body: JSON.stringify({
          x: wx,
          y: wy,
          yaw,
          controllerId: options.controllerId || options.controller_id || '',
        }),
      }).then((result) => {
        if (result.success) resolve(result);
        else reject(new Error(result.message || 'Navigation goal rejected'));
      }).catch(reject);
      return;
    }
    if (!sendGoalClient) {
      reject(new Error('Not connected to Nav2'));
      return;
    }

    sendGoalClient.callService(
      new ROSLIB.ServiceRequest({
        x: wx,
        y: wy,
        yaw,
        controller_id: options.controllerId || options.controller_id || '',
      }),
      (result) => {
        if (result.success) resolve(result);
        else reject(new Error(result.message || 'Navigation goal rejected'));
      },
      (err) => reject(err)
    );
  });
}

function sendNavGoal(wx, wy, yaw) {
  if (!sendGoalClient && !useNavigationApi()) {
    updateNavStatus('disconnected — is nav_pose_bridge_node running?', '#f87171');
    return;
  }

  updateNavStatus('Sending goal...', '#888');

  callSendNavGoal(wx, wy, yaw)
    .then((result) => {
      updateNavStatus(result.message, '#4ade80');
    })
    .catch((err) => {
      updateNavStatus(err.message || 'Error /send_nav_goal', '#f87171');
      console.error(err);
    });
}

function goalLabel(wx, wy, yaw) {
  const yawDeg = (yaw * 180) / Math.PI;
  return `${Number(wx).toFixed(2)},${Number(wy).toFixed(2)},${yawDeg.toFixed(1)}`;
}

function labelsMatch(a, b) {
  if (!a || !b) return false;
  const pa = a.split(',').map(Number);
  const pb = b.split(',').map(Number);
  if (pa.length < 2 || pb.length < 2) return false;
  return Math.hypot(pa[0] - pb[0], pa[1] - pb[1]) < 0.05;
}

function findSetpointNameByLabel(label) {
  const setpoints = window.AmrStations?.getSetpoints?.() || [];
  for (const sp of setpoints) {
    const yawRad = (sp.yawDeg * Math.PI) / 180;
    if (labelsMatch(label, goalLabel(sp.x, sp.y, yawRad))) {
      return sp.name;
    }
  }
  return '';
}

function formatArrivalMessage(detail, destinationName) {
  const name = destinationName || findSetpointNameByLabel(detail);
  if (name) {
    return `Đã đến ${name} ✓ — goal success`;
  }
  return `Đã đến ✓ ${detail} — goal success`;
}

function notifyNavArrived(detail, options = {}) {
  const destinationName = options.destinationName || findSetpointNameByLabel(detail);
  const message = formatArrivalMessage(detail, destinationName);
  updateNavStatus(message, '#4ade80');
  window.dispatchEvent(new CustomEvent('amr-nav-arrived', {
    detail: {
      state: 'arrived',
      detail,
      name: destinationName,
      message,
    },
  }));
}

function waitForNavArrived(expectedLabel, timeoutMs = 300000) {
  return new Promise((resolve, reject) => {
    let settled = false;

    function finish(ok, value) {
      if (settled) return;
      settled = true;
      window.removeEventListener('amr-nav-status', onStatus);
      clearTimeout(timer);
      if (ok) resolve(value);
      else reject(value);
    }

    function onStatus(e) {
      const { state, detail } = e.detail || {};
      if (state === 'arrived' && labelsMatch(detail, expectedLabel)) {
        finish(true, detail);
      } else if (state === 'failed' && labelsMatch(detail, expectedLabel)) {
        finish(false, new Error(detail || 'Navigation failed'));
      } else if (state === 'cancelled') {
        finish(false, new Error('Navigation cancelled'));
      }
    }

    const timer = setTimeout(() => {
      finish(false, new Error('Timeout chờ đến đích'));
    }, timeoutMs);

    window.addEventListener('amr-nav-status', onStatus);
  });
}


function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function navigateAndWait(wx, wy, yaw, options = {}) {
  const destName = options.destinationName || '';
  const coordLabel = `(${Number(wx).toFixed(2)}, ${Number(wy).toFixed(2)})`;
  const statusLabel = goalLabel(wx, wy, yaw);
  const postArrivalDelayMs = Number(options.postArrivalDelayMs) || 0;
  const navigatingMsg = destName
    ? `Đang đi tới ${destName}...`
    : `Navigating to ${coordLabel}...`;
  updateNavStatus(navigatingMsg, '#facc15');

  const result = await callSendNavGoal(wx, wy, yaw, options);
  await waitForNavArrived(statusLabel);

  notifyNavArrived(statusLabel, { destinationName: destName });

  if (postArrivalDelayMs > 0) {
    updateNavStatus(
      `${formatArrivalMessage(statusLabel, destName)} — chờ ${postArrivalDelayMs / 1000}s...`,
      '#4ade80'
    );
    await delay(postArrivalDelayMs);
  }

  return result;
}

function sendNavGoalAsync(wx, wy, yaw, options = {}) {
  if (!sendGoalClient && !useNavigationApi()) {
    return Promise.reject(new Error('Not connected to Nav2'));
  }
  return navigateAndWait(wx, wy, yaw, options);
}

function setNavMode(enabled) {
  if (enabled && window.AmrSlam?.isScanOn?.()) {
    window.AmrSlam.setScanMode(false);
  }
  navUiOn = enabled;
  if (btnNavMode) {
    btnNavMode.textContent = `Chọn điểm đến: ${enabled ? 'BẬT' : 'TẮT'}`;
    btnNavMode.classList.toggle('active', enabled);
  }
  if (window.AmrMap) window.AmrMap.setNavMode(enabled);
  if (enabled && window.AmrLocalization) {
    window.AmrLocalization.setPoseUiOn?.(false);
  }
}

function cancelNavigationAsync() {
  if (useNavigationApi()) {
    if (window.AmrMap) window.AmrMap.clearPlanPath();
    return window.AmrApi.request('/api/navigation/cancel', { method: 'POST' })
      .then((result) => {
        updateNavStatus(result.message || 'Emergency stop', '#f87171');
        setNavMode(false);
        if (!result.success) throw new Error(result.message || 'Không dừng được Nav2');
        return result;
      });
  }
  if (!cancelNavClient) {
    updateNavStatus('disconnected', '#f87171');
    return Promise.reject(new Error('Chưa kết nối /cancel_nav'));
  }
  if (window.AmrMap) window.AmrMap.clearPlanPath();
  return new Promise((resolve, reject) => {
    cancelNavClient.callService(
      new ROSLIB.ServiceRequest({}),
      (result) => {
        updateNavStatus(result.message || 'Emergency stop', result.success ? '#f87171' : '#f87171');
        setNavMode(false);
        if (result.success) resolve(result);
        else reject(new Error(result.message || 'Không dừng được Nav2'));
      },
      (err) => {
        updateNavStatus('Lỗi /cancel_nav', '#f87171');
        console.error(err);
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    );
  });
}

function cancelNavigation() {
  window.AmrTeleop?.stop?.();
  cancelNavigationAsync().catch((err) => console.error(err));
}

function triggerEmergency() {
  updateNavStatus('EMERGENCY — đang dừng...', '#f87171');
  window.AmrTeleop?.stop?.();
  window.AmrProcess?.stopAutoRoute?.();
  cancelNavigationAsync()
    .then(() => updateNavStatus('EMERGENCY — đã dừng', '#f87171'))
    .catch(() => updateNavStatus('EMERGENCY — đã gửi lệnh dừng', '#f87171'));
}

if (btnNavMode) {
  btnNavMode.addEventListener('click', () => setNavMode(!navUiOn));
}
if (btnNavCancel) {
  btnNavCancel.addEventListener('click', triggerEmergency);
}

window.addEventListener('amr-auth-ready', () => {
  if (!useNavigationApi()) return;
  if (window.AmrMap) {
    window.AmrMap.setNavGoalCallback(sendNavGoal);
    updateNavStatus('🟢 Navigation Ready', '#4ade80');
  }
});

window.addEventListener('amr-ros-connected', () => {
  const ros = window.AmrRos.getRos();
  if (!ros) return;

  sendGoalClient  = new ROSLIB.Service({
    ros,
    name: '/send_nav_goal',
    serviceType: 'amr_web_interfaces/srv/SendNavGoal',
  });
  cancelNavClient = new ROSLIB.Service({
    ros,
    name: '/cancel_nav',
    serviceType: 'std_srvs/srv/Trigger',
  });

  if (navStatusTopic) navStatusTopic.unsubscribe();
  navStatusTopic = new ROSLIB.Topic({
    ros,
    name: '/web_nav_status',
    messageType: 'std_msgs/msg/String',
  });
  navStatusTopic.subscribe((msg) => {
    const { state, detail } = parseNavStatus(msg.data);
    dispatchNavStatus(state, detail);
  });

  function wireNavCallback() {
    if (window.AmrMap) {
      window.AmrMap.setNavGoalCallback(sendNavGoal);
      updateNavStatus('🟢 Navigation Ready', '#4ade80');
    } else {
      setTimeout(wireNavCallback, 100);
    }
  }
  wireNavCallback();
});

window.AmrNavigation = {
  sendNavGoal,
  sendNavGoalAsync,
  navigateAndWait,
  waitForNavArrived,
  setNavMode,
  cancelNavigation,
  cancelNavigationAsync,
};
