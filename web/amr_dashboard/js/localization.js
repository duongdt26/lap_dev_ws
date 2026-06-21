// /**
//  * localization.js — Danh sách map + nạp map + bật initial pose
//  */

//   const MAPS_DIR = '/home/duo/maps';

//   // const ros = window.AmrRos.getRos();
//   // if (!ros) {
//   //   console.error('ROS chưa có — bấm Kết nối trước');
//   //   return;
//   // }

//   const mapSelect = document.getElementById('map-select');
//   const loadStatus = document.getElementById('load-map-status');
//   const btnRefresh = document.getElementById('btn-refresh-maps');
//   const btnLoad = document.getElementById('btn-load-map');
//   const btnPoseMode = document.getElementById('btn-pose-mode');

//   // if (!mapSelect || !btnRefresh || !btnLoad || !btnPoseMode) {
//   //   console.error('Thiếu phần tử HTML localization — kiểm tra index.html');
//   //   return;
//   // }


//   let listMapsClient = null;
//   let loadMapClient = null;

//   // let listMapsClient = new ROSLIB.Service({
//   //   ros,
//   //   name: '/list_maps',
//   //   serviceType: 'std_srvs/srv/Trigger',
//   // });

//   // let loadMapClient = new ROSLIB.Service({
//   //   ros,
//   //   name: '/map_server/load_map',
//   //   serviceType: 'nav2_msgs/srv/LoadMap',
//   // });

//   let poseMode = false;

//   function refreshMapList() {
//     loadStatus.textContent = 'Đang tải danh sách...';
//     loadStatus.style.color = '#888';

//     listMapsClient.callService(
//       new ROSLIB.ServiceRequest({}),
//       (result) => {
//         mapSelect.innerHTML = '';
//         const names = (result.message || '')
//           .replace('(chưa có map trong ~/maps)', '')
//           .split(',')
//           .map((s) => s.trim())
//           .filter((s) => s.length > 0);

//         if (names.length === 0) {
//           const opt = document.createElement('option');
//           opt.value = '';
//           opt.textContent = '(không có map)';
//           mapSelect.appendChild(opt);
//           loadStatus.textContent = 'Không có map trong ~/maps';
//           loadStatus.style.color = '#f87171';
//           return;
//         }

//         names.forEach((name) => {
//           const opt = document.createElement('option');
//           opt.value = name;
//           opt.textContent = name;
//           mapSelect.appendChild(opt);
//         });
//         loadStatus.textContent = `Đã tải ${names.length} map`;
//         loadStatus.style.color = '#4ade80';
//       },
//       (err) => {
//         loadStatus.textContent = 'Lỗi /list_maps — map_bridge_node có chạy?';
//         loadStatus.style.color = '#f87171';
//         console.error(err);
//       }
//     );
//   }

//   btnRefresh.addEventListener('click', refreshMapList);

//   btnLoad.addEventListener('click', () => {
//     const name = mapSelect.value;
//     if (!name) {
//       loadStatus.textContent = 'Chọn map trước';
//       loadStatus.style.color = '#f87171';
//       return;
//     }

//     const mapUrl = `${MAPS_DIR}/${name}.yaml`;
//     loadStatus.textContent = 'Đang nạp map...';
//     loadStatus.style.color = '#888';

//     loadMapClient.callService(
//       new ROSLIB.ServiceRequest({ map_url: mapUrl }),
//       (result) => {
//         if (result.result === 0) {
//           loadStatus.textContent = `Đã nạp: ${name}`;
//           loadStatus.style.color = '#4ade80';
//         } else {
//           loadStatus.textContent = result.error_msg || 'Nạp map thất bại';
//           loadStatus.style.color = '#f87171';
//         }
//       },
//       (err) => {
//         loadStatus.textContent = 'Lỗi load_map — localization có chạy?';
//         loadStatus.style.color = '#f87171';
//         console.error(err);
//       }
//     );
//   });

//   btnPoseMode.addEventListener('click', () => {
//     poseMode = !poseMode;
//     btnPoseMode.textContent = `Đặt vị trí ban đầu: ${poseMode ? 'BẬT' : 'TẮT'}`;
//     btnPoseMode.classList.toggle('active', poseMode);

//     function applyPoseMode() {
//       if (window.AmrMap) {
//         window.AmrMap.setPoseMode(poseMode);
//       } else {
//         setTimeout(applyPoseMode, 200);
//       }
//     }
//     applyPoseMode();
//   });

//   window.AmrLocalization = { refreshMapList };

//   window.addEventListener('amr-ros-connected', () => {
//     const ros = window.AmrRos.getRos();
//     if (!ros) return;
//     listMapsClient = new ROSLIB.Service({
//       ros, name: '/list_maps', serviceType: 'std_srvs/srv/Trigger',
//     });
//     loadMapClient = new ROSLIB.Service({
//       ros, name: '/map_server/load_map', serviceType: 'nav2_msgs/srv/LoadMap',
//     });
//     refreshMapList();
//   });

/**
 * localization.js — Danh sách map + nạp map + đặt initial pose
 */

// const MAPS_DIR = '/home/duo/maps';

// const mapSelect   = document.getElementById('map-select');
// const loadStatus  = document.getElementById('load-map-status');
// const btnRefresh  = document.getElementById('btn-refresh-maps');
// const btnLoad     = document.getElementById('btn-load-map');
// const btnPoseMode = document.getElementById('btn-pose-mode');

// let listMapsClient = null;
// let loadMapClient  = null;
// let poseMode = false;

// function refreshMapList() {
//   if (!listMapsClient) {
//     loadStatus.textContent = 'Chưa kết nối — bấm Kết nối trước';
//     loadStatus.style.color = '#f87171';
//     return;
//   }
//   loadStatus.textContent = 'Đang tải danh sách...';
//   loadStatus.style.color = '#888';
//   listMapsClient.callService(new ROSLIB.ServiceRequest({}),
//     (result) => {
//       mapSelect.innerHTML = '';
//       const names = (result.message || '')
//         .replace('(chưa có map trong ~/maps)', '')
//         .split(',').map(s => s.trim()).filter(s => s.length > 0);
//       if (names.length === 0) {
//         mapSelect.innerHTML = '<option value="">(không có map)</option>';
//         loadStatus.textContent = 'Không có map trong ~/maps';
//         loadStatus.style.color = '#f87171';
//         return;
//       }
//       names.forEach(name => {
//         const opt = document.createElement('option');
//         opt.value = opt.textContent = name;
//         mapSelect.appendChild(opt);
//       });
//       loadStatus.textContent = `Đã tải ${names.length} map`;
//       loadStatus.style.color = '#4ade80';
//     },
//     (err) => {
//       loadStatus.textContent = 'Lỗi /list_maps — map_bridge_node có chạy?';
//       loadStatus.style.color = '#f87171';
//       console.error(err);
//     }
//   );
// }

// btnRefresh.addEventListener('click', refreshMapList);

// btnLoad.addEventListener('click', () => {
//   const name = mapSelect.value;
//   if (!name) { loadStatus.textContent = 'Chọn map trước'; loadStatus.style.color = '#f87171'; return; }
//   if (!loadMapClient) { loadStatus.textContent = 'Chưa kết nối'; loadStatus.style.color = '#f87171'; return; }
//   loadStatus.textContent = 'Đang nạp map...';
//   loadStatus.style.color = '#888';
//   loadMapClient.callService(
//     new ROSLIB.ServiceRequest({ map_url: `${MAPS_DIR}/${name}.yaml` }),
//     (result) => {
//       if (result.result === 0) {
//         loadStatus.textContent = `Đã nạp: ${name}`;
//         loadStatus.style.color = '#4ade80';
//       } else {
//         loadStatus.textContent = result.error_msg || 'Nạp map thất bại';
//         loadStatus.style.color = '#f87171';
//       }
//     },
//     (err) => { loadStatus.textContent = 'Lỗi load_map'; loadStatus.style.color = '#f87171'; console.error(err); }
//   );
// });

// btnPoseMode.addEventListener('click', () => {
//   poseMode = !poseMode;
//   btnPoseMode.textContent = `Đặt vị trí ban đầu: ${poseMode ? 'BẬT' : 'TẮT'}`;
//   btnPoseMode.classList.toggle('active', poseMode);
//   if (window.AmrMap) window.AmrMap.setPoseMode(poseMode);
// });

// window.addEventListener('amr-ros-connected', () => {
//   const ros = window.AmrRos.getRos();
//   if (!ros) return;
//   listMapsClient = new ROSLIB.Service({ ros, name: '/list_maps', serviceType: 'std_srvs/srv/Trigger' });
//   loadMapClient  = new ROSLIB.Service({ ros, name: '/map_server/load_map', serviceType: 'nav2_msgs/srv/LoadMap' });
//   refreshMapList();
// });

// window.AmrLocalization = { refreshMapList };


/**
 * localization.js — Danh sách map + nạp map + đặt initial pose
 */

const MAPS_DIR = '/home/duo/maps';

const mapSelect   = document.getElementById('map-select');
const loadStatus  = document.getElementById('load-map-status');
const btnRefresh  = document.getElementById('btn-refresh-maps');
const btnLoad     = document.getElementById('btn-load-map');
const btnPoseMode = document.getElementById('btn-pose-mode');

let listMapsClient = null;
let loadMapClient  = null;

// Đổi tên: KHÔNG dùng "poseMode" — map.js đã dùng biến đó
let poseUiOn = false;

/** Cập nhật nút + báo map.js bật/tắt chế độ kéo trên canvas */
function setPoseUiOn(enabled) {
  poseUiOn = enabled;
  btnPoseMode.textContent = `Đặt vị trí ban đầu: ${enabled ? 'BẬT' : 'TẮT'}`;
  btnPoseMode.classList.toggle('active', enabled);
  if (window.AmrMap) {
    window.AmrMap.setPoseMode(enabled);
  }
}

function refreshMapList() {
  if (!listMapsClient) {
    loadStatus.textContent = 'Chưa kết nối — bấm Kết nối trước';
    loadStatus.style.color = '#f87171';
    return;
  }
  loadStatus.textContent = 'Đang tải danh sách...';
  loadStatus.style.color = '#888';
  listMapsClient.callService(new ROSLIB.ServiceRequest({}),
    (result) => {
      mapSelect.innerHTML = '';
      const names = (result.message || '')
        .replace('(chưa có map trong ~/maps)', '')
        .split(',').map(s => s.trim()).filter(s => s.length > 0);
      if (names.length === 0) {
        mapSelect.innerHTML = '<option value="">(không có map)</option>';
        loadStatus.textContent = 'Không có map trong ~/maps';
        loadStatus.style.color = '#f87171';
        return;
      }
      names.forEach(name => {
        const opt = document.createElement('option');
        opt.value = opt.textContent = name;
        mapSelect.appendChild(opt);
      });
      loadStatus.textContent = `Đã tải ${names.length} map`;
      loadStatus.style.color = '#4ade80';
    },
    (err) => {
      loadStatus.textContent = 'Lỗi /list_maps — map_bridge_node có chạy?';
      loadStatus.style.color = '#f87171';
      console.error(err);
    }
  );
}

btnRefresh.addEventListener('click', refreshMapList);

btnLoad.addEventListener('click', () => {
  const name = mapSelect.value;
  if (!name) { loadStatus.textContent = 'Chọn map trước'; loadStatus.style.color = '#f87171'; return; }
  if (!loadMapClient) { loadStatus.textContent = 'Chưa kết nối'; loadStatus.style.color = '#f87171'; return; }
  loadStatus.textContent = 'Đang nạp map...';
  loadStatus.style.color = '#888';
  loadMapClient.callService(
    new ROSLIB.ServiceRequest({ map_url: `${MAPS_DIR}/${name}.yaml` }),
    (result) => {
      if (result.result === 0) {
        loadStatus.textContent = `Đã nạp: ${name}`;
        loadStatus.style.color = '#4ade80';
      } else {
        loadStatus.textContent = result.error_msg || 'Nạp map thất bại';
        loadStatus.style.color = '#f87171';
      }
    },
    (err) => { loadStatus.textContent = 'Lỗi load_map'; loadStatus.style.color = '#f87171'; console.error(err); }
  );
});

btnPoseMode.addEventListener('click', () => {
  const next = !poseUiOn;
  // Bật pose → tắt nav (hai chế độ loại trừ nhau)
  if (next && window.AmrNavigation) {
    window.AmrNavigation.setNavMode(false);
  }
  setPoseUiOn(next);
});

window.addEventListener('amr-ros-connected', () => {
  const ros = window.AmrRos.getRos();
  if (!ros) return;
  listMapsClient = new ROSLIB.Service({ ros, name: '/list_maps', serviceType: 'std_srvs/srv/Trigger' });
  loadMapClient  = new ROSLIB.Service({ ros, name: '/map_server/load_map', serviceType: 'nav2_msgs/srv/LoadMap' });
  refreshMapList();
});

window.AmrLocalization = { refreshMapList, setPoseUiOn };