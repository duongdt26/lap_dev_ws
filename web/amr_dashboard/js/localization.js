// /**
//  * localization.js — Danh sách map + nạp map + bật initial pose
//  */

//   const MAPS_DIR = '/home/laptop/maps';

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

// const MAPS_DIR = '/home/laptop/maps';

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

const MAPS_DIR = '/home/laptop/maps';

function mapYamlPath(name) {
  return `${MAPS_DIR}/${name}.yaml`;
}

const mapSelect   = document.getElementById('map-select');
const loadStatus  = document.getElementById('load-map-status');
const btnLoad     = document.getElementById('btn-load-map');

let listMapsClient = null;
let loadMapClient  = null;

function setLoadMapStatus(message, color = '') {
  if (!loadStatus) return;
  loadStatus.textContent = message || '';
  loadStatus.style.color = color;
}

function refreshActiveMapStatus() {
  if (!window.AmrMapSync?.getMapStatus) return;
  window.AmrMapSync.getMapStatus()
    .then((status) => {
      if (status.loaded && !mapSelect.value && status.map_name) {
        const opt = Array.from(mapSelect.options).find((o) => o.value === status.map_name);
        if (opt) mapSelect.value = status.map_name;
      }
      // Không ghi trạng thái Active map lên #load-map-status — chỉ hiện khi nạp thành công/lỗi.
    })
    .catch(() => { /* bridge chưa sẵn sàng */ });
}

async function notifyMapLoaded(name) {
  if (!window.AmrMapSync?.getMapStatus) return;

  const waitMs = 200;
  const maxAttempts = 30;

  function waitForMapReady(attempt) {
    return window.AmrMapSync.getMapStatus().then((status) => {
      if (status.loaded) return status;
      if (attempt >= maxAttempts) {
        throw new Error('Map server chưa publish /map sau khi load');
      }
      return new Promise((resolve) => {
        setTimeout(resolve, waitMs);
      }).then(() => waitForMapReady(attempt + 1));
    });
  }

  const warnings = [];

  try {
    await waitForMapReady(0);
    await window.AmrMapSync.requestMapSync();
  } catch (err) {
    // map.js còn subscribe trực tiếp /map, nên lỗi bridge không được coi là lỗi load map.
    console.warn('map bridge sync:', err);
    warnings.push('bridge sync chậm');
  }

  try {
    if (window.AmrMapData?.syncForMap) {
      await window.AmrMapData.syncForMap(name);
    } else if (window.AmrMapSync.setActiveMapName) {
      await window.AmrMapSync.setActiveMapName(name);
    }
  } catch (err) {
    console.warn('map data sync:', err);
    warnings.push('setpoint/process chưa đồng bộ');
  }

  // Tự đưa về origin (0, 0, 0) của map vừa nạp.
  const originOk = window.AmrMap?.publishInitialPose?.(0, 0, 0);
  if (!originOk) {
    warnings.push('chưa set được origin 0,0,0');
  }

  refreshActiveMapStatus();
  window.dispatchEvent(new CustomEvent('amr-map-loaded', { detail: { name } }));

  if (warnings.length > 0) {
    setLoadMapStatus(`Nạp map thành công: ${name} (${warnings.join(', ')})`, '#facc15');
  } else {
    setLoadMapStatus(`Nạp map thành công: ${name} · origin (0,0,0)`, '#4ade80');
  }

  // Ép sync thêm lần nữa — rosbridge đôi khi trễ 1 nhịp.
  setTimeout(() => {
    if (window.AmrMapSync?.forceMapResync) {
      window.AmrMapSync.forceMapResync().catch(() => {});
    }
  }, 500);
}

// Đổi tên: KHÔNG dùng "poseMode" — map.js đã dùng biến đó
let poseUiOn = false;

/** Cập nhật nút + báo map.js bật/tắt chế độ kéo trên canvas (giữ API cũ) */
function setPoseUiOn(enabled) {
  poseUiOn = enabled;
  if (window.AmrMap) {
    window.AmrMap.setPoseMode(enabled);
  }
}

/** Publish /initialpose tại (0, 0, yaw=0) */
function loadOriginPose(options = {}) {
  const silent = !!options.silent;
  if (window.AmrNavigation) {
    window.AmrNavigation.setNavMode?.(false);
  }
  setPoseUiOn(false);

  const ok = window.AmrMap?.publishInitialPose?.(0, 0, 0);
  if (!ok) {
    if (!silent) {
      setLoadMapStatus('Chưa kết nối ROS — không load được vị trí ban đầu', '#f87171');
    }
    return false;
  }

  if (!silent) {
    setLoadMapStatus('Đã load vị trí ban đầu (0, 0, 0)', '#4ade80');
  }
  return true;
}

function refreshMapList(options = {}) {
  const silent = !!options.silent;
  if (!listMapsClient) {
    if (!silent) setLoadMapStatus('Chưa kết nối ROS', '#f87171');
    return;
  }
  if (!silent) setLoadMapStatus('');
  listMapsClient.callService(new ROSLIB.ServiceRequest({}),
    (result) => {
      mapSelect.innerHTML = '';
      const names = (result.message || '')
        .replace('(chưa có map trong ~/maps)', '')
        .split(',').map(s => s.trim()).filter(s => s.length > 0);
      if (names.length === 0) {
        mapSelect.innerHTML = '<option value="">(không có map)</option>';
        if (!silent) setLoadMapStatus('Không có map trong ~/maps', '#f87171');
        return;
      }
      names.forEach(name => {
        const opt = document.createElement('option');
        opt.value = opt.textContent = name;
        mapSelect.appendChild(opt);
      });
      if (!silent) setLoadMapStatus('');
    },
    (err) => {
      if (!silent) setLoadMapStatus('Lỗi tải danh sách map', '#f87171');
      console.error(err);
    }
  );
}

btnLoad?.addEventListener('click', () => {
  const name = mapSelect.value;
  if (!name) { setLoadMapStatus('Chọn map trước', '#f87171'); return; }
  if (!loadMapClient) { setLoadMapStatus('Chưa kết nối ROS', '#f87171'); return; }
  setLoadMapStatus('Đang nạp map...', '#888');
  loadMapClient.callService(
    new ROSLIB.ServiceRequest({ map_url: mapYamlPath(name) }),
    (result) => {
      if (result.result === 0) {
        setLoadMapStatus(`Nạp map thành công: ${name}`, '#4ade80');
        notifyMapLoaded(name);
      } else {
        setLoadMapStatus(result.error_msg || 'Nạp map thất bại', '#f87171');
      }
    },
    (err) => { setLoadMapStatus('Lỗi nạp map', '#f87171'); console.error(err); }
  );
});

const btnImport = document.getElementById('btn-import-map');
const importFiles = document.getElementById('import-map-files');

/** Ghép file chọn từng lần hoặc chọn cả 2 cùng lúc. */
const pendingImport = { yaml: null, image: null };

function ensureMapOption(name) {
  if (!mapSelect || !name) return;
  let opt = Array.from(mapSelect.options).find((o) => o.value === name);
  if (!opt) {
    opt = document.createElement('option');
    opt.value = opt.textContent = name;
    mapSelect.appendChild(opt);
  }
  mapSelect.value = name;
}

function isYamlFile(file) {
  return /\.ya?ml$/i.test(file?.name || '');
}

function isImageFile(file) {
  return /\.(pgm|png|jpe?g)$/i.test(file?.name || '');
}

function pendingStatusText() {
  const parts = [];
  if (pendingImport.yaml) parts.push(`YAML: ${pendingImport.yaml.name}`);
  else parts.push('YAML: (chưa có)');
  if (pendingImport.image) parts.push(`Image: ${pendingImport.image.name}`);
  else parts.push('Image: (chưa có)');
  if (pendingImport.yaml && pendingImport.image) {
    return `${parts.join(' · ')} — đang upload...`;
  }
  const missing = !pendingImport.yaml ? 'YAML' : 'ảnh (.pgm/.png)';
  return `${parts.join(' · ')} — chọn tiếp file ${missing} (hoặc chọn cả 2 cùng lúc)`;
}

function clearPendingImport() {
  pendingImport.yaml = null;
  pendingImport.image = null;
}

async function uploadPendingImport() {
  if (!pendingImport.yaml && !pendingImport.image) return;
  if (!window.AmrApi?.isAvailable?.()) {
    setLoadMapStatus('API chưa sẵn sàng — restart backend rồi thử lại', '#f87171');
    return;
  }

  const form = new FormData();
  if (pendingImport.yaml) {
    form.append('files', pendingImport.yaml, pendingImport.yaml.name);
  }
  if (pendingImport.image) {
    form.append('files', pendingImport.image, pendingImport.image.name);
  }

  const label = [
    pendingImport.yaml?.name,
    pendingImport.image?.name,
  ].filter(Boolean).join(' + ');

  setLoadMapStatus(`Đang import: ${label}`, '#888');
  if (btnImport) btnImport.setAttribute('aria-disabled', 'true');
  try {
    const result = await window.AmrApi.request('/api/map-import', {
      method: 'POST',
      body: form,
    });
    const name = result?.name || '';
    clearPendingImport();
    setLoadMapStatus(name ? `Imported: ${name}` : 'Import map thành công', '#4ade80');
    ensureMapOption(name);
    refreshMapList({ silent: true });
  } catch (err) {
    console.error('Import map failed:', err);
    // Thiếu file còn lại → giữ pending, hướng dẫn chọn tiếp.
    if (!pendingImport.yaml || !pendingImport.image) {
      setLoadMapStatus(pendingStatusText(), '#facc15');
      return;
    }
    setLoadMapStatus(err.message || 'Import map thất bại', '#f87171');
  } finally {
    if (btnImport) btnImport.removeAttribute('aria-disabled');
  }
}

function ingestImportFiles(fileList) {
  const selected = Array.from(fileList || []);
  if (!selected.length) return;

  let added = 0;
  selected.forEach((file) => {
    if (isYamlFile(file)) {
      pendingImport.yaml = file;
      added += 1;
    } else if (isImageFile(file)) {
      pendingImport.image = file;
      added += 1;
    }
  });

  if (!added) {
    setLoadMapStatus(
      `Bỏ qua: ${selected.map((f) => f.name).join(', ')} — cần .yaml/.yml hoặc .pgm/.png`,
      '#f87171'
    );
    return;
  }

  setLoadMapStatus(pendingStatusText(), '#facc15');
  uploadPendingImport();
}

importFiles?.addEventListener('change', () => {
  const copy = importFiles.files ? Array.from(importFiles.files) : [];
  importFiles.value = '';
  ingestImportFiles(copy);
});

window.addEventListener('amr-ros-connected', () => {
  const ros = window.AmrRos.getRos();
  if (!ros) return;
  listMapsClient = new ROSLIB.Service({ ros, name: '/list_maps', serviceType: 'std_srvs/srv/Trigger' });
  loadMapClient  = new ROSLIB.Service({ ros, name: '/map_server/load_map', serviceType: 'nav2_msgs/srv/LoadMap' });
  refreshMapList({ silent: true });
  setTimeout(refreshActiveMapStatus, 800);
});

window.addEventListener('amr-map-ready', refreshActiveMapStatus);

window.AmrLocalization = { refreshMapList, setPoseUiOn, loadOriginPose };
