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
let goalXParam = null;
let goalYParam = null;
let goalYawParam = null;
let navUiOn = false;

function updateNavStatus(msg, color = '#888') {
  navStatus.textContent = msg;
  navStatus.style.color = color;
}

function sendNavGoal(wx, wy, yaw) {
  if (!sendGoalClient) {
    updateNavStatus('Chưa kết nối — nav_pose_bridge_node có chạy?', '#f87171');
    return;
  }

  updateNavStatus('Đang gửi goal...', '#888');

  // Bước 1: set parameter (giống save_map)
  goalXParam.set(wx, () => {
    goalYParam.set(wy, () => {
      goalYawParam.set(yaw, () => {
        // Bước 2: gọi service
        sendGoalClient.callService(
          new ROSLIB.ServiceRequest({}),
          (result) => {
            updateNavStatus(result.message, result.success ? '#4ade80' : '#f87171');
          },
          (err) => {
            updateNavStatus('Lỗi /send_nav_goal', '#f87171');
            console.error(err);
          }
        );
      });
    });
  });
}

function setNavMode(enabled) {
  navUiOn = enabled;
  btnNavMode.textContent = `Nav mode: ${enabled ? 'BẬT' : 'TẮT'}`;
  btnNavMode.classList.toggle('active', enabled);
  if (window.AmrMap) window.AmrMap.setNavMode(enabled);
  if (enabled && window.AmrLocalization) {
    window.AmrLocalization.setPoseUiOn(false);
  }
}

function cancelNavigation() {
  if (!cancelNavClient) {
    updateNavStatus('Chưa kết nối', '#f87171');
    return;
  }
  if (window.AmrMap) window.AmrMap.clearPlanPath();
  cancelNavClient.callService(
    new ROSLIB.ServiceRequest({}),
    (result) => {
      updateNavStatus(result.message, result.success ? '#f87171' : '#f87171');
      setNavMode(false);
    },
    (err) => {
      updateNavStatus('Lỗi /cancel_nav', '#f87171');
      console.error(err);
    }
  );
}

btnNavMode.addEventListener('click', () => setNavMode(!navUiOn));
btnNavCancel.addEventListener('click', cancelNavigation);

window.addEventListener('amr-ros-connected', () => {
  const ros = window.AmrRos.getRos();
  if (!ros) return;

  sendGoalClient  = new ROSLIB.Service({ ros, name: '/send_nav_goal', serviceType: 'std_srvs/srv/Trigger' });
  cancelNavClient = new ROSLIB.Service({ ros, name: '/cancel_nav',     serviceType: 'std_srvs/srv/Trigger' });
  goalXParam   = new ROSLIB.Param({ ros, name: '/nav_pose_bridge_node:goal_x' });
  goalYParam   = new ROSLIB.Param({ ros, name: '/nav_pose_bridge_node:goal_y' });
  goalYawParam = new ROSLIB.Param({ ros, name: '/nav_pose_bridge_node:goal_yaw' });

  function wireNavCallback() {
    if (window.AmrMap) {
      window.AmrMap.setNavGoalCallback(sendNavGoal);
      updateNavStatus('Sẵn sàng (service Nav2)', '#4ade80');
    } else {
      setTimeout(wireNavCallback, 100);
    }
  }
  wireNavCallback();
});

window.AmrNavigation = { sendNavGoal, setNavMode, cancelNavigation };