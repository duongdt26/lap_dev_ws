/**
 * stations.js — Setpoint, station control, workflow timeline
 */

(function () {
  const STORAGE_KEY = 'amr-setpoints-v1';

  let setpoints = [];
  let selectedId = null;
  let workflowStep = 'connect';
  let pendingDeleteId = null;

  const modal = document.getElementById('setpoint-modal');
  const deleteModal = document.getElementById('delete-setpoint-modal');
  const listEl = document.getElementById('setpoints-list');
  const emptyEl = document.getElementById('setpoints-empty');
  const stationStatus = document.getElementById('station-status');
  const workflowDetail = document.getElementById('workflow-detail');
  const conveyor1El = document.getElementById('conveyor-1-status');
  const conveyor2El = document.getElementById('conveyor-2-status');

  const conveyorState = { belt1: 'Free', belt2: 'Free' };

  const BELT_CMD_OPTIONS = [
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
    return value === 'unload' ? 'unload' : 'load';
  }

  function loadSetpoints() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      setpoints = raw ? JSON.parse(raw) : [];
      setpoints = setpoints.map((pt) => ({
        ...pt,
        status: pt.status === 'Occupied' ? 'Occupied' : 'Free',
        belt1Cmd: normalizeBeltCmd(pt.belt1Cmd),
        belt2Cmd: normalizeBeltCmd(pt.belt2Cmd),
      }));
    } catch {
      setpoints = [];
    }
  }

  function saveSetpoints() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(setpoints));
    renderSetpointsList();
    setWorkflowStep('setpoint', setpoints.length
      ? `Đã lưu ${setpoints.length} setpoint`
      : 'Chưa có setpoint — bấm Setpoint để thêm');
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
    conveyor1El.className = `status-badge ${conveyorState.belt1 === 'Occupied' ? 'status-occupied' : 'status-free'}`;
    conveyor1El.textContent = conveyorState.belt1;
    conveyor2El.className = `status-badge ${conveyorState.belt2 === 'Occupied' ? 'status-occupied' : 'status-free'}`;
    conveyor2El.textContent = conveyorState.belt2;
  }

  function setConveyorStatus(belt, status) {
    const key = belt === 1 ? 'belt1' : 'belt2';
    conveyorState[key] = status === 'Occupied' ? 'Occupied' : 'Free';
    renderConveyorStatus();
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
        selectedId = pt.id;
        renderSetpointsList();
        updateStationStatus();
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
        ? 'Chọn setpoint trong danh sách bên phải'
        : 'Chưa có setpoint — bấm Setpoint để thêm';
      return;
    }
    const pt = setpoints.find((p) => p.id === selectedId);
    stationStatus.textContent = pt
      ? `Đã chọn: ${pt.name} (${formatPose(pt)}) | BT1: ${beltCmdLabel(pt.belt1Cmd)} | BT2: ${beltCmdLabel(pt.belt2Cmd)}`
      : 'Chưa có station nào được chọn';
  }

  function setWorkflowStep(step, detail) {
    workflowStep = step;
    document.querySelectorAll('.workflow-step').forEach((el) => {
      const s = el.dataset.step;
      el.classList.remove('active', 'done');
      const order = ['connect', 'map', 'localize', 'setpoint', 'route', 'goto', 'done'];
      const curIdx = order.indexOf(step);
      const elIdx = order.indexOf(s);
      if (elIdx < curIdx) el.classList.add('done');
      else if (elIdx === curIdx) el.classList.add('active');
    });
    if (detail) workflowDetail.textContent = detail;
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

  function openSetpointModal() {
    refreshModalPose();
    document.getElementById('setpoint-name').value = '';
    document.getElementById('setpoint-x').value = '';
    document.getElementById('setpoint-y').value = '';
    document.getElementById('setpoint-yaw').value = '';
    document.getElementById('setpoint-belt1-cmd').value = 'load';
    document.getElementById('setpoint-belt2-cmd').value = 'load';
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeSetpointModal() {
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

  function goToSelectedStation() {
    const pt = setpoints.find((p) => p.id === selectedId);
    if (!pt) {
      stationStatus.textContent = 'Chọn setpoint trong danh sách trước';
      return;
    }
    if (!window.AmrNavigation || !window.AmrNavigation.sendNavGoal) {
      stationStatus.textContent = 'Chưa kết nối Nav2';
      return;
    }
    const yawRad = (pt.yawDeg * Math.PI) / 180;
    window.AmrNavigation.sendNavGoal(pt.x, pt.y, yawRad);
    setWorkflowStep('goto', `Đang đi tới ${pt.name}...`);
    stationStatus.textContent = `Go to Station: ${pt.name}`;
  }

  function autoRoute() {
    if (setpoints.length < 2) {
      stationStatus.textContent = 'Cần ít nhất 2 setpoint cho Auto Route';
      return;
    }
    setWorkflowStep('route', `Auto Route: ${setpoints.length} điểm (chưa triển khai Nav2 waypoint)`);
    stationStatus.textContent =
      `Auto Route: ${setpoints.map((p) => p.name).join(' → ')} — sẽ gắn FollowWaypoints sau`;
  }

  function resetStation() {
    selectedId = null;
    renderSetpointsList();
    updateStationStatus('Đã reset lựa chọn station');
    setWorkflowStep('setpoint', setpoints.length
      ? `${setpoints.length} setpoint — chọn hoặc thêm mới`
      : 'Chưa có setpoint');
  }

  document.getElementById('btn-setpoint').addEventListener('click', openSetpointModal);
  document.getElementById('btn-auto-route').addEventListener('click', autoRoute);
  document.getElementById('btn-go-station').addEventListener('click', goToSelectedStation);
  document.getElementById('btn-station-reset').addEventListener('click', resetStation);
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

  window.addEventListener('amr-ros-connected', () => {
    setWorkflowStep('connect', 'Đã kết nối — nạp map hoặc chạy SLAM');
  });

  window.addEventListener('amr-ros-disconnected', () => {
    setWorkflowStep('connect', 'Chưa kết nối — bấm Kết nối trong Config');
  });

  window.addEventListener('amr-map-ready', () => {
    setWorkflowStep('map', 'Map đã sẵn sàng — đặt vị trí ban đầu nếu cần');
  });

  loadSetpoints();
  renderConveyorStatus();
  renderSetpointsList();
  updateStationStatus();
  setWorkflowStep('connect', 'Chưa kết nối — bấm Kết nối trong Config');

  window.AmrStations = {
    getSetpoints: () => [...setpoints],
    setWorkflowStep,
    setConveyorStatus,
    setSetpointStatus(id, status) {
      const pt = setpoints.find((p) => p.id === id);
      if (!pt) return;
      pt.status = status === 'Occupied' ? 'Occupied' : 'Free';
      saveSetpoints();
    },
  };
})();
