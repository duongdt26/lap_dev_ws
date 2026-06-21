/**
 * slam.js — Gọi service /save_map từ web
 *
 * Điều kiện: map_bridge_node đang chạy + có topic /map (SLAM hoặc map_server)
 * 
 * Service: /save_map (std_srvs/Trigger)
 * Parameter: map_name (set trước khi gọi service)
 */

  let slamUiReady = false;
  window.addEventListener('amr-ros-connected', initSlamControls);

  function initSlamControls() {
    if (slamUiReady) return;   // ← thêm dòng này
    slamUiReady = true;         // ← thêm dòng này
    const ros = window.AmrRos.getRos();
    if (!ros) return;
  
    const statusEl = document.getElementById('save-map-status');
    const nameInput = document.getElementById('map-name-input');
    const btnSave = document.getElementById('btn-save-map');
  
    const mapNameParam = new ROSLIB.Param({
        ros,
        name: '/map_bridge_node:map_name',
      });
    
      const saveMapClient = new ROSLIB.Service({
        ros,
        name: '/save_map',
        serviceType: 'std_srvs/srv/Trigger',
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
    
        // Bước 1: gửi tên map lên node
        mapNameParam.set( mapName, ()  => {
            // Bước 2: gọi Trigger (request rỗng)
            saveMapClient.callService(
              new ROSLIB.ServiceRequest({}),
              (result) => {
                statusEl.textContent = result.message;
                statusEl.style.color = result.success ? '#4ade80' : '#f87171';
              },
              (err) => {
                statusEl.textContent = 'Lỗi service — map_bridge_node có chạy không?';
                statusEl.style.color = '#f87171';
                console.error(err);
              }
            );
          },
          (err) => {
            statusEl.textContent = 'Không set được parameter map_name';
            statusEl.style.color = '#f87171';
            console.error(err);
          }
        );
      });
  }