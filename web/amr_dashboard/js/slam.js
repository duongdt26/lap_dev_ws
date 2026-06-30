/**
 * slam.js — Gọi service /save_map_named từ web
 */

  let slamUiReady = false;
  window.addEventListener('amr-ros-connected', initSlamControls);

  function initSlamControls() {
    if (slamUiReady) return;
    slamUiReady = true;
    const ros = window.AmrRos.getRos();
    if (!ros) return;

    const statusEl = document.getElementById('save-map-status');
    const nameInput = document.getElementById('map-name-input');
    const btnSave = document.getElementById('btn-save-map');

    const saveMapClient = new ROSLIB.Service({
      ros,
      name: '/save_map_named',
      serviceType: 'amr_web_interfaces/srv/SaveMap',
    });

    btnSave.addEventListener('click', () => {
      const mapName = nameInput.value.trim();
      if (!mapName) {
        statusEl.textContent = 'Nhập tên map trước (vd: obs_4_map_save)';
        statusEl.style.color = '#f87171';
        return;
      }

      statusEl.textContent = 'Đang lưu map...';
      statusEl.style.color = '#888';

      saveMapClient.callService(
        new ROSLIB.ServiceRequest({ map_name: mapName }),
        (result) => {
          statusEl.textContent = result.message;
          statusEl.style.color = result.success ? '#4ade80' : '#f87171';
          if (result.success && window.AmrMapData?.syncForMap) {
            window.AmrMapData.syncForMap(mapName).catch(() => {});
          }
        },
        (err) => {
          statusEl.textContent = 'Lỗi service — map_bridge_node có chạy không?';
          statusEl.style.color = '#f87171';
          console.error(err);
        }
      );
    });
  }
