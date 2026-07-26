/**
 * keepout.js — Vẽ polygon vùng cấm và đồng bộ Nav2 KeepoutFilter mask.
 */
(function () {
  const canvas = document.getElementById('map-canvas');
  const btnDraw = document.getElementById('btn-keepout-draw');
  const btnFinish = document.getElementById('btn-keepout-finish');
  const btnDelete = document.getElementById('btn-keepout-delete');
  const btnSave = document.getElementById('btn-keepout-save');
  const nameInput = document.getElementById('keepout-name');
  const listEl = document.getElementById('keepout-zone-list');
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

  function nextDefaultName() {
    return `NO-GO ZONE ${zones.length + 1}`;
  }

  function zonesCountLabel(count = zones.length) {
    return `${count} No-Go Zone${count === 1 ? '' : 's'}`;
  }

  function syncNamePlaceholder() {
    if (!nameInput) return;
    if (!nameInput.value.trim()) nameInput.placeholder = nextDefaultName();
  }

  function syncCanvas() {
    window.AmrMap?.setKeepoutZones?.(zones);
    window.AmrMap?.setKeepoutDraft?.(draft);
  }

  function renderZoneList() {
    if (!listEl) return;
    listEl.innerHTML = '';
    if (!zones.length) {
      const empty = document.createElement('li');
      empty.className = 'keepout-zone-empty';
      empty.textContent = 'No zones created';
      listEl.appendChild(empty);
      return;
    }
    zones.forEach((zone, index) => {
      const li = document.createElement('li');
      li.className = 'keepout-zone-item';
      li.dataset.index = String(index);

      const name = document.createElement('span');
      name.className = 'keepout-zone-name';
      name.textContent = zone.name || `NO-GO ZONE ${index + 1}`;

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'keepout-zone-remove';
      remove.title = 'Delete Zone';
      remove.setAttribute('aria-label', `Delete ${name.textContent}`);
      remove.textContent = '×';
      remove.addEventListener('click', () => removeZoneAt(index));

      li.appendChild(name);
      li.appendChild(remove);
      listEl.appendChild(li);
    });
  }

  function updateControls() {
    btnDraw.textContent = drawing ? 'Cancel Draw' : 'Draw Zone';
    btnDraw.classList.toggle('active', drawing);
    btnDraw.disabled = false;
    if (btnFinish) btnFinish.disabled = !drawing || draft.length < 3;
    if (btnDelete) btnDelete.disabled = zones.length === 0;
    if (btnSave) btnSave.disabled = drawing || !dirty;
    syncNamePlaceholder();
    renderZoneList();
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
    writeStatus(message || `${zonesCountLabel()} active`, 'ok');
  }

  function removeZoneAt(index) {
    if (index < 0 || index >= zones.length) return;
    const removed = zones.splice(index, 1)[0];
    dirty = true;
    syncCanvas();
    updateControls();
    writeStatus(
      `Deleted “${removed?.name || 'zone'}” · ${zonesCountLabel()} left · unsaved`,
      'warn'
    );
  }

  async function loadZones(mapName) {
    const name = await resolveMapName(mapName);
    if (!name || (!loadClient && !useApi())) {
      writeStatus('Load map before configuring No-Go Zones', 'warn');
      updateControls();
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
        if (!response.success) throw new Error(response.message || 'Failed to load No-Go Zones');
        data = JSON.parse(response.json_data || '[]');
      }
      applyZones(data, name, `${zonesCountLabel(data.length)} · mask for map ${name}`);
    } catch (err) {
      writeStatus(`Load No-Go Zones error: ${err.message || err}`, 'error');
    }
  }

  async function saveZones() {
    const name = await resolveMapName(currentMapName);
    if (!name) {
      writeStatus('No active map', 'error');
      return;
    }
    if (btnSave) btnSave.disabled = true;
    writeStatus('Rasterizing and applying KeepoutFilter…');
    try {
      if (useApi()) {
        if (!window.AmrApi.canWrite()) throw new Error('View-only account');
        await window.AmrApi.request(keepoutApiPath(name), {
          method: 'PUT',
          body: JSON.stringify(zones),
        });
      }
      let appliedToRos = false;
      if (saveClient) {
        const response = await callService(saveClient, {
          map_name: name,
          json_data: JSON.stringify(zones),
        });
        if (!response.success) throw new Error(response.message || 'Failed to apply No-Go Zones');
        appliedToRos = true;
      } else if (!useApi()) {
        throw new Error('Keepout service not ready');
      }
      dirty = false;
      updateControls();
      writeStatus(
        appliedToRos
          ? `Saved ${zonesCountLabel()} to global + local costmap`
          : `Saved ${zonesCountLabel()} to SQLite · ROS offline`,
        'ok'
      );
    } catch (err) {
      updateControls();
      writeStatus(`Save No-Go Zones error: ${err.message || err}`, 'error');
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
      writeStatus(`${zonesCountLabel()}${dirty ? ' · unsaved' : ''}`, dirty ? 'warn' : '');
      return;
    }
    if (!window.AmrMap?.hasMap?.()) {
      writeStatus('Chưa có map để vẽ', 'error');
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
    writeStatus(`${draft.length} điểm · bấm “Finish” để đóng polygon`);
  });

  btnFinish?.addEventListener('click', () => {
    if (!drawing || draft.length < 3) return;
    const typed = nameInput?.value.trim() || '';
    const zoneName = typed || nextDefaultName();
    zones.push({
      id: `keepout_${Date.now()}`,
      name: zoneName,
      enabled: true,
      points: draft.map((point) => ({ ...point })),
    });
    if (nameInput) nameInput.value = '';
    dirty = true;
    setDrawing(false);
    writeStatus(`${zonesCountLabel()} · press “Save”`, 'warn');
  });

  btnDelete?.addEventListener('click', () => {
    if (!zones.length) return;
    removeZoneAt(zones.length - 1);
  });

  btnSave?.addEventListener('click', saveZones);

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

  setTimeout(() => {
    const ros = window.AmrRos?.getRos?.();
    if (ros?.isConnected && !loadClient) {
      initClients();
      loadZones();
    }
  }, 1000);

  updateControls();
  writeStatus('Load map to load No-Go Zones');

  window.AmrKeepout = {
    getZones: () => zones.map((zone) => ({ ...zone, points: zone.points.map((p) => ({ ...p })) })),
    loadZones,
    saveZones,
  };
})();
