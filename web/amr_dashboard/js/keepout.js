/**
 * Trình biên tập vùng cấm theo từng map.
 * Dữ liệu polygon được map_bridge chuyển thành OccupancyGrid cho KeepoutFilter.
 */
(function () {
  const canvas = document.getElementById('map-canvas');
  const nameInput = document.getElementById('keepout-name');
  const reasonInput = document.getElementById('keepout-reason');
  const drawButton = document.getElementById('btn-keepout-draw');
  const finishButton = document.getElementById('btn-keepout-finish');
  const cancelButton = document.getElementById('btn-keepout-cancel');
  const hint = document.getElementById('keepout-hint');
  const list = document.getElementById('keepout-list');
  const nav2State = document.getElementById('keepout-nav2-state');

  let zones = [];
  let draft = [];
  let drawing = false;
  let nav2Active = false;

  function cacheKey() {
    const mapName = window.AmrMapData?.getCurrentMapName?.() || 'offline';
    return 'amr-keepout-zones:' + mapName;
  }

  function cacheZones() {
    try {
      localStorage.setItem(cacheKey(), JSON.stringify(zones));
    } catch (_err) {}
  }

  function loadCachedZones() {
    try {
      const data = JSON.parse(localStorage.getItem(cacheKey()) || '[]');
      return Array.isArray(data) ? data : [];
    } catch (_err) {
      return [];
    }
  }

  function setNav2State(active, message) {
    nav2Active = !!active;
    nav2State.classList.toggle('safety-active', nav2Active);
    nav2State.classList.toggle('safety-pending', !nav2Active);
    const title = nav2State.querySelector('strong');
    const detail = nav2State.querySelector('span');
    title.textContent = nav2Active
      ? 'Nav2 đang áp dụng vùng cấm'
      : 'Vùng cấm chưa được Nav2 xác nhận';
    detail.textContent = message || (
      nav2Active
        ? 'Mask đang được phát cho global và local costmap.'
        : 'Dữ liệu chỉ đang hiển thị trên web; chưa được coi là vùng an toàn.'
    );
  }

  function emitChanged() {
    window.dispatchEvent(new CustomEvent('amr-keepout-changed', {
      detail: { zones: zones.slice(), draft: draft.slice(), nav2Active },
    }));
    window.AmrMap?.invalidate?.();
  }

  function setDrawing(enabled) {
    drawing = enabled;
    canvas.classList.toggle('keepout-draw-mode', enabled);
    drawButton.disabled = enabled;
    finishButton.disabled = !enabled || draft.length < 3;
    cancelButton.disabled = !enabled;
    if (!enabled) draft = [];
    hint.textContent = enabled
      ? 'Chọn các đỉnh của vùng cấm trên map. Cần ít nhất 3 điểm.'
      : 'Nhấn “Vẽ đa giác”, sau đó chọn ít nhất 3 điểm trên map.';
    emitChanged();
  }

  function startDrawing() {
    if (!window.AmrMap?.hasMap?.()) {
      hint.textContent = 'Chưa có map. Hãy nạp map trước khi vẽ vùng cấm.';
      return;
    }
    window.AmrNavigation?.setNavMode?.(false);
    window.AmrLocalization?.setPoseUiOn?.(false);
    draft = [];
    setDrawing(true);
  }

  function cancelDrawing() {
    setDrawing(false);
  }

  async function saveToServer() {
    cacheZones();
    renderList();
    emitChanged();
    if (!window.AmrMapData?.saveKeepoutZones) {
      setNav2State(false, 'Backend vùng cấm chưa sẵn sàng.');
      return;
    }
    try {
      const result = await window.AmrMapData.saveKeepoutZones(zones);
      setNav2State(result.nav2Active, result.message);
    } catch (err) {
      setNav2State(false, err.message || 'Không thể lưu vùng cấm lên robot.');
    }
  }

  function finishDrawing() {
    if (draft.length < 3) {
      hint.textContent = 'Cần ít nhất 3 điểm để khép vùng.';
      return;
    }
    const id = window.crypto?.randomUUID?.() || (
      'zone-' + Date.now() + '-' + Math.random().toString(16).slice(2)
    );
    zones.push({
      id,
      name: nameInput.value.trim() || ('Vùng cấm ' + (zones.length + 1)),
      reason: reasonInput.value.trim(),
      enabled: true,
      points: draft.map((point) => ({ x: point.x, y: point.y })),
    });
    nameInput.value = '';
    reasonInput.value = '';
    setDrawing(false);
    saveToServer();
  }

  function onCanvasClick(event) {
    if (!drawing) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const point = window.AmrMap?.clientPointToWorld?.(
      event.clientX,
      event.clientY
    );
    if (!point) return;
    draft.push(point);
    finishButton.disabled = draft.length < 3;
    hint.textContent = 'Đã chọn ' + draft.length + ' điểm'
      + (draft.length >= 3 ? ' — có thể khép vùng.' : '.');
    emitChanged();
  }

  function makeZoneButton(label, className, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
  }

  function renderList() {
    list.innerHTML = '';
    if (!zones.length) {
      const empty = document.createElement('li');
      empty.className = 'keepout-empty';
      empty.textContent = 'Map chưa có vùng cấm.';
      list.appendChild(empty);
      return;
    }

    zones.forEach((zone) => {
      const item = document.createElement('li');
      item.className = 'keepout-item';

      const toggle = document.createElement('input');
      toggle.type = 'checkbox';
      toggle.checked = zone.enabled !== false;
      toggle.setAttribute('aria-label', 'Bật vùng cấm ' + zone.name);
      toggle.addEventListener('change', () => {
        zone.enabled = toggle.checked;
        saveToServer();
      });

      const text = document.createElement('div');
      const title = document.createElement('strong');
      const detail = document.createElement('span');
      title.textContent = zone.name;
      detail.textContent = zone.reason || (zone.points.length + ' đỉnh');
      text.append(title, detail);

      const remove = makeZoneButton('Xóa', 'keepout-delete', () => {
        zones = zones.filter((candidate) => candidate.id !== zone.id);
        saveToServer();
      });

      item.append(toggle, text, remove);
      list.appendChild(item);
    });
  }

  async function reloadFromServer() {
    zones = loadCachedZones();
    renderList();
    emitChanged();
    if (!window.AmrMapData?.loadKeepoutZones) {
      setNav2State(false);
      return;
    }
    try {
      const result = await window.AmrMapData.loadKeepoutZones();
      zones = Array.isArray(result.zones) ? result.zones : [];
      cacheZones();
      renderList();
      emitChanged();
      setNav2State(result.nav2Active, result.message);
    } catch (err) {
      setNav2State(false, err.message || 'Không thể tải vùng cấm từ robot.');
    }
  }

  drawButton.addEventListener('click', startDrawing);
  finishButton.addEventListener('click', finishDrawing);
  cancelButton.addEventListener('click', cancelDrawing);
  canvas.addEventListener('click', onCanvasClick, true);

  window.addEventListener('amr-map-data-sync', reloadFromServer);
  window.addEventListener('amr-map-ready', reloadFromServer);
  window.addEventListener('amr-data-updated', (event) => {
    if (event.detail === 'keepout_zones') reloadFromServer();
  });
  window.addEventListener('amr-ros-disconnected', () => {
    setNav2State(false, 'Mất kết nối; không thể xác nhận KeepoutFilter.');
  });

  window.AmrKeepout = {
    getZones: () => zones.slice(),
    getDraft: () => draft.slice(),
    isDrawing: () => drawing,
    isNav2Active: () => nav2Active,
    reloadFromServer,
  };

  zones = loadCachedZones();
  renderList();
  setNav2State(false);
  emitChanged();
})();
