/**
 * keepout.js — Vẽ polygon vùng cấm và đồng bộ Nav2 KeepoutFilter mask.
 */
(function () {
  const canvas = document.getElementById('map-canvas');
  const btnDraw = document.getElementById('btn-keepout-draw');
  const btnFinish = document.getElementById('btn-keepout-finish');
  const btnUndo = document.getElementById('btn-keepout-undo');
  const btnDelete = document.getElementById('btn-keepout-delete');
  const btnClear = document.getElementById('btn-keepout-clear');
  const btnSave = document.getElementById('btn-keepout-save');
  const statusEl = document.getElementById('keepout-status');
  if (!canvas || !btnDraw || !statusEl) return;

  let loadClient = null;
  let saveClient = null;
  let zones = [];
  let draft = [];
  let drawing = false;
  let dirty = false;
  let currentMapName = '';

  function writeStatus(message, kind = '') {
    statusEl.textContent = message;
    statusEl.classList.toggle('keepout-ok', kind === 'ok');
    statusEl.classList.toggle('keepout-warn', kind === 'warn');
    statusEl.classList.toggle('keepout-error', kind === 'error');
  }

  function callService(client, request) {
    return new Promise((resolve, reject) => {
      if (!client) {
        reject(new Error('Keepout service chưa sẵn sàng'));
        return;
      }
      client.callService(new ROSLIB.ServiceRequest(request), resolve, reject);
    });
  }

  function useApi() {
    return !!window.AmrApi?.isAvailable?.() && !!window.AmrApi?.getUser?.();
  }

  function keepoutApiPath(mapName) {
    return `/api/maps/${encodeURIComponent(mapName)}/keepout`;
  }

  function syncCanvas() {
    window.AmrMap?.setKeepoutZones?.(zones);
    window.AmrMap?.setKeepoutDraft?.(draft);
  }

  function updateControls() {
    btnDraw.textContent = drawing ? 'Hủy vẽ' : 'Vẽ vùng cấm';
    btnDraw.classList.toggle('active', drawing);
    btnFinish.disabled = !drawing || draft.length < 3;
    btnUndo.disabled = !drawing || draft.length === 0;
    btnDelete.disabled = drawing || zones.length === 0;
    btnClear.disabled = drawing || zones.length === 0;
    btnSave.disabled = drawing || !dirty;
  }

  function setDrawing(enabled) {
    drawing = !!enabled;
    if (!drawing) draft = [];
    window.AmrMap?.setKeepoutMode?.(drawing);
    syncCanvas();
    updateControls();
  }

  async function resolveMapName(explicitName) {
    const explicit = String(explicitName || '').trim();
    if (explicit) return explicit;
    const fromData = window.AmrMapData?.getCurrentMapName?.() || '';
    if (fromData) return fromData;
    try {
      const status = await window.AmrMapSync?.getMapStatus?.();
      return String(status?.map_name || '').trim();
    } catch {
      return '';
    }
  }

  function applyZones(nextZones, mapName, message) {
    zones = Array.isArray(nextZones) ? nextZones : [];
    draft = [];
    drawing = false;
    dirty = false;
    currentMapName = mapName || currentMapName;
    window.AmrMap?.setKeepoutMode?.(false);
    syncCanvas();
    updateControls();
    writeStatus(message || `${zones.length} vùng cấm đang áp dụng`, 'ok');
  }

  async function loadZones(mapName) {
    const name = await resolveMapName(mapName);
    if (!name || (!loadClient && !useApi())) {
      writeStatus('Nạp map trước khi cấu hình vùng cấm', 'warn');
      return;
    }
    try {
      let data;
      if (useApi()) {
        try {
          data = await window.AmrApi.request(keepoutApiPath(name));
        } catch (error) {
          if (error.status !== 404) throw error;
          data = [];
        }
      } else {
        const response = await callService(loadClient, { map_name: name });
        if (!response.success) throw new Error(response.message || 'Không tải được vùng cấm');
        data = JSON.parse(response.json_data || '[]');
      }
      applyZones(data, name, `${data.length} vùng cấm · mask theo map ${name}`);
    } catch (err) {
      writeStatus(`Lỗi tải vùng cấm: ${err.message || err}`, 'error');
    }
  }

  async function saveZones() {
    const name = await resolveMapName(currentMapName);
    if (!name) {
      writeStatus('Chưa có map active', 'error');
      return;
    }
    btnSave.disabled = true;
    writeStatus('Đang raster hóa và áp dụng KeepoutFilter…');
    try {
      if (useApi()) {
        if (!window.AmrApi.canWrite()) throw new Error('Tài khoản chỉ có quyền xem');
        await window.AmrApi.request(keepoutApiPath(name), {
          method: 'PUT',
          body: JSON.stringify(zones),
        });
      }
      // Trong giai đoạn chuyển đổi vẫn gọi ROS service để raster hóa và publish mask.
      let appliedToRos = false;
      if (saveClient) {
        const response = await callService(saveClient, {
          map_name: name,
          json_data: JSON.stringify(zones),
        });
        if (!response.success) throw new Error(response.message || 'Áp dụng vùng cấm thất bại');
        appliedToRos = true;
      } else if (!useApi()) {
        throw new Error('Keepout service chưa sẵn sàng');
      }
      dirty = false;
      updateControls();
      writeStatus(
        appliedToRos
          ? `Đã áp dụng ${zones.length} vùng cấm cho global + local costmap`
          : `Đã lưu ${zones.length} vùng cấm vào SQLite · ROS đang offline`,
        'ok'
      );
    } catch (err) {
      updateControls();
      writeStatus(`Lỗi lưu vùng cấm: ${err.message || err}`, 'error');
    }
  }

  function initClients() {
    const ros = window.AmrRos?.getRos?.();
    if (!ros) return;
    loadClient = new ROSLIB.Service({
      ros,
      name: '/load_keepout_zones',
      serviceType: 'amr_web_interfaces/srv/LoadKeepoutZones',
    });
    saveClient = new ROSLIB.Service({
      ros,
      name: '/save_keepout_zones',
      serviceType: 'amr_web_interfaces/srv/SaveKeepoutZones',
    });

    new ROSLIB.Topic({
      ros,
      name: '/web/keepout_zones',
      messageType: 'std_msgs/msg/String',
    }).subscribe((message) => {
      try {
        const payload = JSON.parse(message.data || '{}');
        if (drawing || dirty) return;
        const payloadMap = String(payload.mapName || '');
        if (currentMapName && payloadMap && payloadMap !== currentMapName) return;
        applyZones(payload.zones || [], payloadMap, undefined);
      } catch (err) {
        console.warn('keepout zones topic:', err);
      }
    });
  }

  btnDraw.addEventListener('click', () => {
    if (drawing) {
      setDrawing(false);
      writeStatus(`${zones.length} vùng cấm${dirty ? ' · chưa lưu' : ''}`, dirty ? 'warn' : '');
      return;
    }
    if (!window.AmrMap?.hasMap?.()) {
      writeStatus('Chưa có map để vẽ', 'error');
      return;
    }
    if (!window.AmrMap?.canEditKeepout?.()) {
      writeStatus('Dừng robot/Nav trước khi vẽ vùng cấm', 'warn');
      return;
    }
    if (window.AmrLocalization?.setPoseUiOn) window.AmrLocalization.setPoseUiOn(false);
    if (window.AmrNavigation?.setNavMode) window.AmrNavigation.setNavMode(false);
    draft = [];
    setDrawing(true);
    writeStatus('Click các đỉnh polygon trên map, tối thiểu 3 điểm');
  });

  canvas.addEventListener('click', (event) => {
    if (!drawing) return;
    event.preventDefault();
    event.stopPropagation();
    const point = window.AmrMap?.clientToWorld?.(event.clientX, event.clientY);
    if (!point) return;
    draft.push({
      x: Math.round(point.x * 1000) / 1000,
      y: Math.round(point.y * 1000) / 1000,
    });
    syncCanvas();
    updateControls();
    writeStatus(`${draft.length} điểm · bấm “Hoàn tất” để đóng polygon`);
  });

  btnFinish.addEventListener('click', () => {
    if (!drawing || draft.length < 3) return;
    zones.push({
      id: `keepout_${Date.now()}`,
      name: `Vùng cấm ${zones.length + 1}`,
      enabled: true,
      points: draft.map((point) => ({ ...point })),
    });
    dirty = true;
    setDrawing(false);
    writeStatus(`${zones.length} vùng cấm · bấm “Lưu & áp dụng”`, 'warn');
  });

  btnUndo.addEventListener('click', () => {
    if (!drawing || !draft.length) return;
    draft.pop();
    syncCanvas();
    updateControls();
    writeStatus(`${draft.length} điểm trong polygon đang vẽ`);
  });

  btnDelete.addEventListener('click', () => {
    if (!zones.length) return;
    zones.pop();
    dirty = true;
    syncCanvas();
    updateControls();
    writeStatus(`Đã xóa vùng cuối · còn ${zones.length} vùng · chưa lưu`, 'warn');
  });

  btnClear.addEventListener('click', () => {
    if (!zones.length || !window.confirm('Xóa toàn bộ vùng cấm của map này?')) return;
    zones = [];
    dirty = true;
    syncCanvas();
    updateControls();
    writeStatus('Đã xóa trên bản vẽ · bấm “Lưu & áp dụng”', 'warn');
  });

  btnSave.addEventListener('click', saveZones);

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && drawing) {
      setDrawing(false);
      writeStatus('Đã hủy polygon đang vẽ');
    }
  });

  window.addEventListener('amr-ros-connected', () => {
    initClients();
    setTimeout(() => loadZones(), 800);
  });
  window.addEventListener('amr-ros-disconnected', () => {
    loadClient = null;
    saveClient = null;
    setDrawing(false);
    writeStatus('ROS disconnected', 'error');
  });
  window.addEventListener('amr-map-data-sync', (event) => loadZones(event.detail?.name));
  window.addEventListener('amr-data-updated', (event) => {
    if (event.detail === 'keepout' && !dirty && !drawing) loadZones(currentMapName);
  });

  // Không phụ thuộc hoàn toàn vào event: rosbridge có thể connect trước khi file này tải xong.
  setTimeout(() => {
    const ros = window.AmrRos?.getRos?.();
    if (ros?.isConnected && !loadClient) {
      initClients();
      loadZones();
    }
  }, 1000);

  updateControls();
  writeStatus('Nạp map để tải vùng cấm');

  window.AmrKeepout = {
    getZones: () => zones.map((zone) => ({ ...zone, points: zone.points.map((p) => ({ ...p })) })),
    loadZones,
    saveZones,
  };
})();
