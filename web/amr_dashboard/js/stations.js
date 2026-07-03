/**
 * stations.js — Setpoint, station control, workflow status
 */

(function () {
  let setpoints = [];
  let selectedId = null;
  let pendingDeleteId = null;
  let editingId = null;

  const modal = document.getElementById('setpoint-modal');
  const deleteModal = document.getElementById('delete-setpoint-modal');
  const listEl = document.getElementById('setpoints-list');
  const emptyEl = document.getElementById('setpoints-empty');
  const stationStatus = document.getElementById('station-status');
  const stationSelect = document.getElementById('station-setpoint-select');
  const btnEditSetpoint = document.getElementById('btn-edit-setpoint');
  const modalTitle = document.getElementById('setpoint-modal-title');
  const btnSavePoint = document.getElementById('btn-save-point');
  const workflowDetail = document.getElementById('workflow-detail');
  const conveyor1El = document.getElementById('conveyor-1-status');
  const conveyor2El = document.getElementById('conveyor-2-status');

  const conveyorState = { belt1: 'Free', belt2: 'Free' };

  const BELT_CMD_OPTIONS = [
    { value: 'none', label: 'None' },
    { value: 'load', label: 'Load' },
    { value: 'unload', label: 'Unload' },
  ];

  function beltCmdLabel(value) {
    const opt = BELT_CMD_OPTIONS.find((o) => o.value === value);
    return opt ? opt.label : '—';
  }

  function beltCmdHtml(value) {
    const cmd = normalizeBeltCmd(value);
    const label = beltCmdLabel(cmd);
    return `<span class="belt-cmd-tag belt-cmd-${cmd}">${label}</span>`;
  }

  function normalizeBeltCmd(value) {
    const v = String(value || '').toLowerCase();
    if (v === 'unload') return 'unload';
    if (v === 'none') return 'none';
    return 'load';
  }

  function normalizeSetpoint(pt) {
    return {
      ...pt,
      status: pt.status === 'Occupied' ? 'Occupied' : 'Free',
      belt1Cmd: normalizeBeltCmd(pt.belt1Cmd),
      belt2Cmd: normalizeBeltCmd(pt.belt2Cmd),
    };
  }

  async function reloadSetpointsFromServer(mapName) {
    if (!window.AmrMapData?.loadSetpoints) return;
    try {
      const name = await window.AmrMapData.resolveMapName(mapName);
      if (!name) {
        setpoints = [];
        selectedId = null;
        renderSetpointsList();
        renderStationPicker();
        updateStationStatus('Nạp map để xem setpoint');
        return;
      }
      const data = await window.AmrMapData.loadSetpoints(name);
      setpoints = (data || []).map(normalizeSetpoint);
      selectedId = null;
      renderSetpointsList();
      renderStationPicker();
      updateStationStatus();
      window.dispatchEvent(new CustomEvent('amr-setpoints-changed'));
    } catch (err) {
      console.warn('load setpoints:', err);
      stationStatus.textContent = `Lỗi tải setpoint: ${err.message}`;
    }
  }

  function saveSetpoints() {
    renderSetpointsList();
    renderStationPicker();
    window.dispatchEvent(new CustomEvent('amr-setpoints-changed'));
    setWorkflowStep('setpoint', setpoints.length
      ? `Đã lưu ${setpoints.length} setpoint`
      : 'Chưa có setpoint — bấm Setpoint để thêm');

    if (!window.AmrMapData?.saveSetpoints) return;
    const mapName = window.AmrMapData.getCurrentMapName();
    if (!mapName) {
      stationStatus.textContent = 'Nạp map trước khi lưu setpoint';
      return;
    }
    window.AmrMapData.saveSetpoints(setpoints, mapName).catch((err) => {
      stationStatus.textContent = `Lỗi lưu setpoint: ${err.message}`;
    });
  }

  function getRobotPose() {
    return window.__amrPose || { x: null, y: null, yawDeg: null };
  }

  function fmtComma(n, decimals) {
    return Number(n).toFixed(decimals).replace('.', ',');
  }

  function formatPositionCol(pt) {
    return `${fmtComma(pt.x, 3)}  |  ${fmtComma(pt.y, 3)}  |  ${fmtComma(pt.yawDeg, 2)}`;
  }

  function formatPose(p) {
    if (p.x == null) return '--';
    return `${Number(p.x).toFixed(2)}, ${Number(p.y).toFixed(2)}, ${Number(p.yawDeg).toFixed(1)}°`;
  }

  function statusBadgeHtml(status) {
    const cls = status === 'Occupied' ? 'status-occupied' : 'status-free';
    const label = status === 'Occupied' ? 'Occupied' : 'Free';
    return `<span class="status-badge ${cls}">${label}</span>`;
  }

  function renderConveyorStatus() {
    if (!conveyor1El || !conveyor2El) return;
    const cls1 = conveyorBadgeClass(conveyorState.belt1);
    const cls2 = conveyorBadgeClass(conveyorState.belt2);
    conveyor1El.className = `status-badge ${cls1}`;
    conveyor1El.textContent = conveyorState.belt1;
    conveyor2El.className = `status-badge ${cls2}`;
    conveyor2El.textContent = conveyorState.belt2;
  }

  function conveyorBadgeClass(status) {
    if (status === 'Delivering') return 'status-delivering';
    if (status === 'Occupied') return 'status-occupied';
    return 'status-free';
  }

  function normalizeConveyorStatus(status) {
    const s = String(status || 'Free');
    if (s === 'Delivering' || s === 'Occupied') return s;
    return 'Free';
  }

  function setConveyorStatus(belt, status) {
    const key = belt === 1 ? 'belt1' : 'belt2';
    conveyorState[key] = normalizeConveyorStatus(status);
    renderConveyorStatus();
  }

  function getConveyorStatus(belt) {
    return belt === 1 ? conveyorState.belt1 : conveyorState.belt2;
  }

  function renderStationPicker() {
    if (!stationSelect) return;

    stationSelect.innerHTML = '';
    if (!setpoints.length) {
      stationSelect.innerHTML = '<option value="">-- Chưa có setpoint --</option>';
      stationSelect.disabled = true;
      if (btnEditSetpoint) btnEditSetpoint.disabled = true;
      return;
    }

    stationSelect.disabled = false;
    const emptyOpt = document.createElement('option');
    emptyOpt.value = '';
    emptyOpt.textContent = '-- Chọn setpoint --';
    stationSelect.appendChild(emptyOpt);

    setpoints.forEach((pt) => {
      const opt = document.createElement('option');
      opt.value = pt.id;
      opt.textContent = pt.name;
      stationSelect.appendChild(opt);
    });

    stationSelect.value = selectedId || '';
    if (btnEditSetpoint) btnEditSetpoint.disabled = !selectedId;
  }

  function selectSetpoint(id) {
    selectedId = id || null;
    renderSetpointsList();
    renderStationPicker();
    updateStationStatus();
  }

  function renderSetpointsList() {
    listEl.innerHTML = '';
    emptyEl.style.display = setpoints.length ? 'none' : 'block';

    setpoints.forEach((pt, index) => {
      const tr = document.createElement('tr');
      tr.className = pt.id === selectedId ? 'selected' : '';
      tr.dataset.id = pt.id;

      tr.innerHTML =
        `<td class="col-order">${index + 1}</td>` +
        `<td class="col-name">${escapeHtml(pt.name)}</td>` +
        `<td class="col-position">${formatPositionCol(pt)}</td>` +
        `<td class="col-cmd-belt">${beltCmdHtml(pt.belt1Cmd)}</td>` +
        `<td class="col-cmd-belt">${beltCmdHtml(pt.belt2Cmd)}</td>` +
        `<td class="col-status">${statusBadgeHtml(pt.status)}</td>` +
        `<td class="col-action"><button type="button" class="setpoint-delete-btn" aria-label="Xóa setpoint" title="Xóa">×</button></td>`;

      tr.querySelector('.setpoint-delete-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        openDeleteConfirm(pt.id);
      });

      tr.addEventListener('click', () => {
        selectSetpoint(pt.id);
      });

      listEl.appendChild(tr);
    });
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function openDeleteConfirm(id) {
    const pt = setpoints.find((p) => p.id === id);
    if (!pt) return;
    pendingDeleteId = id;
    document.getElementById('delete-setpoint-msg').textContent =
      `Bạn muốn xóa Setpoint "${pt.name}"?`;
    deleteModal.classList.remove('hidden');
    deleteModal.setAttribute('aria-hidden', 'false');
  }

  function closeDeleteConfirm() {
    pendingDeleteId = null;
    deleteModal.classList.add('hidden');
    deleteModal.setAttribute('aria-hidden', 'true');
  }

  function confirmDeleteSetpoint() {
    if (!pendingDeleteId) return;
    const pt = setpoints.find((p) => p.id === pendingDeleteId);
    const name = pt ? pt.name : '';
    setpoints = setpoints.filter((p) => p.id !== pendingDeleteId);
    if (selectedId === pendingDeleteId) selectedId = null;
    closeDeleteConfirm();
    saveSetpoints();
    updateStationStatus(name ? `Đã xóa setpoint "${name}"` : undefined);
  }

  function updateStationStatus(msg) {
    if (msg) {
      stationStatus.textContent = msg;
      return;
    }
    if (!selectedId) {
      stationStatus.textContent = setpoints.length
        ? 'Chọn setpoint trong dropdown hoặc danh sách bên phải'
        : 'Chưa có setpoint — bấm Setpoint để thêm';
      return;
    }
    const pt = setpoints.find((p) => p.id === selectedId);
    stationStatus.textContent = pt
      ? `Đã chọn: ${pt.name} (${formatPose(pt)}) | BT1: ${beltCmdLabel(pt.belt1Cmd)} | BT2: ${beltCmdLabel(pt.belt2Cmd)}`
      : 'Chưa có station nào được chọn';
  }

  function setWorkflowStep(_step, detail) {
    if (detail && workflowDetail) workflowDetail.textContent = detail;
  }

  function refreshModalPose() {
    const p = getRobotPose();
    document.getElementById('modal-cur-x').textContent =
      p.x != null ? Number(p.x).toFixed(3) : '--';
    document.getElementById('modal-cur-y').textContent =
      p.y != null ? Number(p.y).toFixed(3) : '--';
    document.getElementById('modal-cur-yaw').textContent =
      p.yawDeg != null ? Number(p.yawDeg).toFixed(2) : '--';
  }

  function resetModalForm() {
    document.getElementById('setpoint-name').value = '';
    document.getElementById('setpoint-x').value = '';
    document.getElementById('setpoint-y').value = '';
    document.getElementById('setpoint-yaw').value = '';
    document.getElementById('setpoint-belt1-cmd').value = 'load';
    document.getElementById('setpoint-belt2-cmd').value = 'load';
  }

  function setModalMode(mode) {
    const isEdit = mode === 'edit';
    if (modalTitle) modalTitle.textContent = isEdit ? 'Sửa Setpoint' : 'Cấu hình Setpoint';
    if (btnSavePoint) btnSavePoint.textContent = isEdit ? 'Lưu thay đổi' : 'Save point';
  }

  function openSetpointModal() {
    editingId = null;
    setModalMode('create');
    refreshModalPose();
    resetModalForm();
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
  }

  function openEditSetpointModal() {
    if (!selectedId) {
      stationStatus.textContent = 'Chọn setpoint trước khi sửa';
      return;
    }
    const pt = setpoints.find((p) => p.id === selectedId);
    if (!pt) {
      stationStatus.textContent = 'Setpoint không tồn tại';
      return;
    }

    editingId = selectedId;
    setModalMode('edit');
    refreshModalPose();
    document.getElementById('setpoint-name').value = pt.name;
    document.getElementById('setpoint-x').value = Number(pt.x).toFixed(2);
    document.getElementById('setpoint-y').value = Number(pt.y).toFixed(2);
    document.getElementById('setpoint-yaw').value = Number(pt.yawDeg).toFixed(1);
    document.getElementById('setpoint-belt1-cmd').value = normalizeBeltCmd(pt.belt1Cmd);
    document.getElementById('setpoint-belt2-cmd').value = normalizeBeltCmd(pt.belt2Cmd);
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeSetpointModal() {
    editingId = null;
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
  }

  function useCurrentPosition() {
    const p = getRobotPose();
    if (p.x == null) {
      stationStatus.textContent = 'Chưa có vị trí robot — cần AMCL/SLAM';
      return;
    }
    document.getElementById('setpoint-x').value = Number(p.x).toFixed(2);
    document.getElementById('setpoint-y').value = Number(p.y).toFixed(2);
    document.getElementById('setpoint-yaw').value = Number(p.yawDeg).toFixed(1);
  }

  function savePoint() {
    const name = document.getElementById('setpoint-name').value.trim();
    const x = parseFloat(document.getElementById('setpoint-x').value);
    const y = parseFloat(document.getElementById('setpoint-y').value);
    const yawDeg = parseFloat(document.getElementById('setpoint-yaw').value);
    const belt1Cmd = normalizeBeltCmd(document.getElementById('setpoint-belt1-cmd').value);
    const belt2Cmd = normalizeBeltCmd(document.getElementById('setpoint-belt2-cmd').value);

    if (!name) {
      stationStatus.textContent = 'Nhập tên vị trí trước khi lưu';
      return;
    }
    if ([x, y, yawDeg].some((v) => Number.isNaN(v))) {
      stationStatus.textContent = 'Nhập đủ X, Y, Yaw hoặc bấm Sử dụng vị trí hiện tại';
      return;
    }

    if (editingId) {
      const pt = setpoints.find((p) => p.id === editingId);
      if (!pt) {
        stationStatus.textContent = 'Setpoint không tồn tại';
        return;
      }
      pt.name = name;
      pt.x = x;
      pt.y = y;
      pt.yawDeg = yawDeg;
      pt.belt1Cmd = belt1Cmd;
      pt.belt2Cmd = belt2Cmd;
      selectedId = editingId;
      saveSetpoints();
      closeSetpointModal();
      renderStationPicker();
      updateStationStatus(`Đã cập nhật setpoint "${name}"`);
      setWorkflowStep('setpoint', `Đã sửa: ${name}`);
      return;
    }

    const pt = {
      id: `sp_${Date.now()}`,
      name,
      x,
      y,
      yawDeg,
      status: 'Free',
      belt1Cmd,
      belt2Cmd,
      createdAt: new Date().toISOString(),
    };
    setpoints.push(pt);
    selectedId = pt.id;
    saveSetpoints();
    closeSetpointModal();
    updateStationStatus(`Đã lưu setpoint "${name}"`);
    setWorkflowStep('setpoint', `Đã lưu: ${name}`);
  }

  function onNavArrived(e) {
    const { message, name } = e.detail || {};
    if (!message) return;
    setWorkflowStep('goto', message);
    if (stationStatus) stationStatus.textContent = message;
  }

  async function goToSelectedStation() {
    const pt = setpoints.find((p) => p.id === selectedId);
    if (!pt) {
      stationStatus.textContent = 'Chọn setpoint trong danh sách trước';
      return;
    }
    if (!window.AmrNavigation?.navigateAndWait) {
      stationStatus.textContent = 'Chưa kết nối Nav2';
      return;
    }
    const yawRad = (pt.yawDeg * Math.PI) / 180;
    if (window.AmrMap?.resetViewAfterNavGoal) {
      window.AmrMap.resetViewAfterNavGoal();
    }
    setWorkflowStep('goto', `Đang đi tới ${pt.name}...`);
    stationStatus.textContent = `Đang đi tới: ${pt.name}`;

    try {
      await window.AmrNavigation.navigateAndWait(pt.x, pt.y, yawRad, {
        destinationName: pt.name,
      });
    } catch (err) {
      const msg = err?.message || 'Lỗi navigation';
      stationStatus.textContent = `Nav thất bại tới ${pt.name}: ${msg}`;
      setWorkflowStep('goto', `Nav thất bại: ${pt.name}`);
    }
  }

  function autoRoute() {
    if (window.AmrProcess && window.AmrProcess.runAutoRoute) {
      window.AmrProcess.runAutoRoute();
      return;
    }
    stationStatus.textContent = 'Chưa có quy trình — thêm bước trong panel Quy trình';
  }

  function resetStation() {
    selectSetpoint(null);
    updateStationStatus('Đã reset lựa chọn station');
    setWorkflowStep('setpoint', setpoints.length
      ? `${setpoints.length} setpoint — chọn hoặc thêm mới`
      : 'Chưa có setpoint');
  }

  document.getElementById('btn-setpoint').addEventListener('click', openSetpointModal);
  document.getElementById('btn-auto-route').addEventListener('click', autoRoute);
  document.getElementById('btn-go-station').addEventListener('click', goToSelectedStation);
  document.getElementById('btn-station-reset').addEventListener('click', resetStation);
  if (stationSelect) {
    stationSelect.addEventListener('change', () => {
      selectSetpoint(stationSelect.value || null);
    });
  }
  if (btnEditSetpoint) {
    btnEditSetpoint.addEventListener('click', openEditSetpointModal);
  }
  document.getElementById('btn-use-current').addEventListener('click', useCurrentPosition);
  document.getElementById('btn-save-point').addEventListener('click', savePoint);
  document.getElementById('btn-cancel-setpoint').addEventListener('click', closeSetpointModal);
  document.getElementById('btn-delete-cancel').addEventListener('click', closeDeleteConfirm);
  document.getElementById('btn-delete-confirm').addEventListener('click', confirmDeleteSetpoint);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeSetpointModal();
  });

  deleteModal.addEventListener('click', (e) => {
    if (e.target === deleteModal) closeDeleteConfirm();
  });

  window.addEventListener('amr-pose', () => {
    if (!modal.classList.contains('hidden')) refreshModalPose();
  });

  window.addEventListener('amr-nav-arrived', onNavArrived);

  window.addEventListener('amr-ros-connected', () => {
    setWorkflowStep('connect', 'connected — load map or run SLAM');
  });

  window.addEventListener('amr-map-data-sync', (e) => {
    reloadSetpointsFromServer(e.detail?.name);
  });

  window.addEventListener('amr-ros-disconnected', () => {
    setWorkflowStep('connect', 'disconnected — press Connect in Config');
  });

  window.addEventListener('amr-map-ready', () => {
    setWorkflowStep('map', 'Map đã sẵn sàng — đặt vị trí ban đầu nếu cần');
  });

  window.addEventListener('amr-data-updated', (e) => {
    if (e.detail === 'setpoints') {
      reloadSetpointsFromServer(window.AmrMapData?.getCurrentMapName());
    }
  });

  renderConveyorStatus();
  renderSetpointsList();
  renderStationPicker();
  updateStationStatus();
  setWorkflowStep('connect', 'disconnected — press Connect in Config');

  window.AmrStations = {
    getSetpoints: () => [...setpoints],
    reloadFromServer: reloadSetpointsFromServer,
    setWorkflowStep,
    setConveyorStatus,
    getConveyorStatus,
    setSetpointStatus(id, status) {
      const pt = setpoints.find((p) => p.id === id);
      if (!pt) return;
      pt.status = status === 'Occupied' ? 'Occupied' : 'Free';
      saveSetpoints();
    },
  };
})();
