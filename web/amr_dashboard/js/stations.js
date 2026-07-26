/**
 * stations.js — Setpoint, station control, workflow status
 */

(function () {
  let setpoints = [];
  let selectedId = null;
  let pendingDeleteId = null;
  let editingId = null;
  let missionRequestTopic = null;
  let cargoDoneTopic = null;
  let missionStatusTopic = null;
  let dockRequestTopic = null;
  let dockResponseTopic = null;
  let costmapRequestTopic = null;
  let costmapResponseTopic = null;
  let missionWaiters = [];
  let dockWaiters = [];
  let costmapWaiters = [];

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

  function writeStationStatus(text) {
    if (stationStatus) stationStatus.textContent = text;
  }

  const conveyorState = { belt1: 'Free', belt2: 'Free' };

  const BELT_CMD_OPTIONS = [
    { value: 'none', label: 'None' },
    { value: 'load', label: 'Load' },
    { value: 'unload', label: 'Unload' },
  ];

  const POINT_TYPE_OPTIONS = [
    { value: 'normal', label: 'Normal' },
    { value: 'approach', label: 'Approach Station' },
    { value: 'home', label: 'Home' },
  ];

  function normalizePointType(value) {
    const v = String(value || '').toLowerCase();
    if (v === 'start_load' || v === 'start_unload' || v === 'approach_pose') {
      return 'approach';
    }
    if (v === 'approach') return v;
    if (v === 'home') return v;
    return 'normal';
  }

  function pointTypeLabel(value) {
    const opt = POINT_TYPE_OPTIONS.find((o) => o.value === normalizePointType(value));
    return opt ? opt.label : 'Normal';
  }

  function pointTypeHtml(value) {
    const t = normalizePointType(value);
    return `<span class="belt-cmd-tag belt-cmd-${t}">${pointTypeLabel(t)}</span>`;
  }

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
    if (v === 'load') return 'load';
    if (v === 'unload') return 'unload';
    return 'none';
  }

  function normalizeSetpoint(pt) {
    const pointType = normalizePointType(pt.pointType);
    const belt1Cmd = normalizeBeltCmd(pt.belt1Cmd);
    const belt2Cmd = normalizeBeltCmd(pt.belt2Cmd);
    return {
      ...pt,
      status: pt.status === 'Occupied' ? 'Occupied' : 'Free',
      pointType,
      // Normal chi dung Nav2; moi lenh bang tai cu deu duoc bo qua an toan.
      belt1Cmd: ['normal', 'home'].includes(pointType) ? 'none' : belt1Cmd,
      belt2Cmd: ['normal', 'home'].includes(pointType) ? 'none' : belt2Cmd,
    };
  }

  function stationKey(pt) {
    const raw = String(pt?.stationId || pt?.name || '').trim();
    const trailingNumber = raw.match(/(\d+)\s*$/);
    if (trailingNumber) return trailingNumber[1];

    return raw
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/đ/g, 'd')
      .replace(/Đ/g, 'D')
      .toLowerCase()
      .trim()
      .replace(/^approach\s+pose\s+/i, '')
      .replace(/^approach\s+/i, '')
      .replace(/^start\s+(load|unload)\s+/i, '')
      .replace(/^(load|unload)\s+/i, '')
      .replace(/^tram\s+tra\s+hang\s+/i, '')
      .replace(/^tram\s+hang\s+/i, '')
      .replace(/^nhan\s+hang\s+/i, '')
      .replace(/^tra\s+hang\s+/i, '')
      .replace(/[_-]+/g, ' ')
      .trim()
  }

  function isApproachPoint(pt) {
    return normalizePointType(pt?.pointType) === 'approach';
  }

  function isHomePoint(pt) {
    return normalizePointType(pt?.pointType) === 'home';
  }

  function isMagneticLinePoint(pt) {
    return isApproachPoint(pt) || isHomePoint(pt);
  }

  function poseJson(pt) {
    return {
      frame_id: 'map',
      x: Number(pt.x),
      y: Number(pt.y),
      yaw: (Number(pt.yawDeg) * Math.PI) / 180,
    };
  }

  function missionStateFromData(data) {
    const parts = String(data || '').split('|');
    return { state: parts[0] || '', detail: parts.slice(1).join('|') };
  }

  function waitForMission(taskId, states, timeoutMs) {
    return new Promise((resolve, reject) => {
      const wanted = new Set(states);
      const deadline = window.setTimeout(() => {
        missionWaiters = missionWaiters.filter((w) => w !== waiter);
        reject(new Error(`Timeout mission ${taskId}`));
      }, timeoutMs);

      const waiter = {
        taskId,
        onStatus(status) {
          if (status.state === 'FAILED') {
            window.clearTimeout(deadline);
            missionWaiters = missionWaiters.filter((w) => w !== waiter);
            reject(new Error(status.detail || 'Mission failed'));
            return;
          }
          if (wanted.has(status.state)) {
            window.clearTimeout(deadline);
            missionWaiters = missionWaiters.filter((w) => w !== waiter);
            resolve(status);
          }
        },
      };
      missionWaiters.push(waiter);
    });
  }

  function waitForDock(taskId, mode, timeoutMs = 180000) {
    return new Promise((resolve, reject) => {
      const deadline = window.setTimeout(() => {
        dockWaiters = dockWaiters.filter((w) => w !== waiter);
        reject(new Error(`Timeout docking ${mode}`));
      }, timeoutMs);

      const waiter = {
        taskId,
        mode,
        onStatus(status) {
          if (status.task_id !== taskId || status.mode !== mode) return;
          if (status.status === 'failed' || status.status === 'error'
              || status.status === 'rejected' || status.status === 'unavailable') {
            window.clearTimeout(deadline);
            dockWaiters = dockWaiters.filter((w) => w !== waiter);
            reject(new Error(status.detail || `Dock ${mode} failed`));
            return;
          }
          if (status.status === 'succeeded') {
            window.clearTimeout(deadline);
            dockWaiters = dockWaiters.filter((w) => w !== waiter);
            resolve(status);
          }
        },
      };
      dockWaiters.push(waiter);
    });
  }

  function waitForCostmap(requestId, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
      const deadline = window.setTimeout(() => {
        costmapWaiters = costmapWaiters.filter((w) => w !== waiter);
        reject(new Error(`Timeout costmap request ${requestId}`));
      }, timeoutMs);

      const waiter = {
        requestId,
        onStatus(status) {
          if (status.request_id !== requestId) return;
          if (status.status === 'error' || status.status === 'failed') {
            window.clearTimeout(deadline);
            costmapWaiters = costmapWaiters.filter((w) => w !== waiter);
            reject(new Error(status.detail || 'Costmap tuning failed'));
            return;
          }
          if (status.status === 'succeeded') {
            window.clearTimeout(deadline);
            costmapWaiters = costmapWaiters.filter((w) => w !== waiter);
            resolve(status);
          }
        },
      };
      costmapWaiters.push(waiter);
    });
  }

  async function setDockCostmapMode(mode, radius = 0.35) {
    if (!costmapRequestTopic) throw new Error('Chưa kết nối costmap tuning bridge');
    const requestId = `WEB_COSTMAP_${mode}_${Date.now()}`;
    const resultPromise = waitForCostmap(requestId);
    costmapRequestTopic.publish(new ROSLIB.Message({
      data: JSON.stringify({
        request_id: requestId,
        mode,
        radius,
      }),
    }));
    return resultPromise;
  }

  async function runDockAction(mode, targetPt, taskId, stationId) {
    if (!dockRequestTopic) throw new Error('Chưa kết nối Docking Server');
    const resultPromise = waitForDock(taskId, mode);
    const payload = {
      task_id: taskId,
      station_id: stationId,
      mode,
      target_pose: poseJson(targetPt),
      max_speed: 0.04,
    };
    dockRequestTopic.publish(new ROSLIB.Message({ data: JSON.stringify(payload) }));
    return resultPromise;
  }

  function publishCargoDone(mode) {
    if (!cargoDoneTopic) throw new Error('Chưa kết nối mission cargo topic');
    cargoDoneTopic.publish(new ROSLIB.Message({ data: mode === 'UNLOAD' ? 'DROP' : 'PICK' }));
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
      writeStationStatus(`Lỗi tải setpoint: ${err.message}`);
    }
  }

  function saveSetpoints() {
    renderSetpointsList();
    renderStationPicker();
    window.dispatchEvent(new CustomEvent('amr-setpoints-changed'));
    setWorkflowStep('setpoint', setpoints.length
      ? `Đã lưu ${setpoints.length} setpoint`
      : 'Chưa có station');

    if (!window.AmrMapData?.saveSetpoints) return;
    const mapName = window.AmrMapData.getCurrentMapName();
    if (!mapName) {
      writeStationStatus('Nạp map trước khi lưu setpoint');
      return;
    }
    window.AmrMapData.saveSetpoints(setpoints, mapName).catch((err) => {
      writeStationStatus(`Lỗi lưu setpoint: ${err.message}`);
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
      stationSelect.innerHTML = '<option value="">-- Chưa có station --</option>';
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
    window.dispatchEvent(new CustomEvent('amr-setpoints-changed'));
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
        `<td class="col-type">${pointTypeHtml(pt.pointType)}</td>` +
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
      writeStationStatus(msg);
      return;
    }
    if (!selectedId) {
      writeStationStatus(setpoints.length
        ? 'Chọn setpoint trong dropdown hoặc danh sách bên phải'
        : 'Chưa có station');
      return;
    }
    const pt = setpoints.find((p) => p.id === selectedId);
    writeStationStatus(pt
      ? `Đã chọn: ${pt.name} (${formatPose(pt)}) | BT1: ${beltCmdLabel(pt.belt1Cmd)} | BT2: ${beltCmdLabel(pt.belt2Cmd)}`
      : 'Chưa có station nào được chọn');
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
    document.getElementById('setpoint-point-type').value = 'normal';
    document.getElementById('setpoint-belt1-cmd').value = 'none';
    document.getElementById('setpoint-belt2-cmd').value = 'none';
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
    applyPointTypeDefaults(false);
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
  }

  function openEditSetpointModal() {
    if (!selectedId) {
      writeStationStatus('Chọn setpoint trước khi sửa');
      return;
    }
    const pt = setpoints.find((p) => p.id === selectedId);
    if (!pt) {
      writeStationStatus('Setpoint không tồn tại');
      return;
    }

    editingId = selectedId;
    setModalMode('edit');
    refreshModalPose();
    document.getElementById('setpoint-name').value = pt.name;
    document.getElementById('setpoint-x').value = Number(pt.x).toFixed(2);
    document.getElementById('setpoint-y').value = Number(pt.y).toFixed(2);
    document.getElementById('setpoint-yaw').value = Number(pt.yawDeg).toFixed(1);
    document.getElementById('setpoint-point-type').value = normalizePointType(pt.pointType);
    document.getElementById('setpoint-belt1-cmd').value = normalizeBeltCmd(pt.belt1Cmd);
    document.getElementById('setpoint-belt2-cmd').value = normalizeBeltCmd(pt.belt2Cmd);
    // Setpoint Approach cu co None se duoc giu de nguoi dung tu chon lai,
    // khong tu dong doi thanh Load/Unload.
    applyPointTypeDefaults(false);
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeSetpointModal() {
    editingId = null;
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
  }

  function applyPointTypeDefaults(defaultApproachCommands = true) {
    const type = normalizePointType(document.getElementById('setpoint-point-type').value);
    const beltSelects = [
      document.getElementById('setpoint-belt1-cmd'),
      document.getElementById('setpoint-belt2-cmd'),
    ];
    beltSelects.forEach((select) => {
      const noneOption = Array.from(select.options).find((option) => option.value === 'none');
      if (noneOption) noneOption.disabled = false;
      select.disabled = type !== 'approach';
      if (type !== 'approach') {
        select.value = 'none';
      } else if (defaultApproachCommands && select.value === 'none') {
        select.value = 'load';
      }
    });
  }

  function useCurrentPosition() {
    const p = getRobotPose();
    if (p.x == null) {
      writeStationStatus('Chưa có vị trí robot — cần AMCL/SLAM');
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
    const pointType = normalizePointType(document.getElementById('setpoint-point-type').value);
    const belt1Cmd = normalizeBeltCmd(document.getElementById('setpoint-belt1-cmd').value);
    const belt2Cmd = normalizeBeltCmd(document.getElementById('setpoint-belt2-cmd').value);

    if (pointType === 'approach' && belt1Cmd === 'none' && belt2Cmd === 'none') {
      writeStationStatus('Approach Station phải chọn ít nhất một băng tải');
      return;
    }

    if (!name) {
      writeStationStatus('Nhập tên vị trí trước khi lưu');
      return;
    }
    if ([x, y, yawDeg].some((v) => Number.isNaN(v))) {
      writeStationStatus('Nhập đủ X, Y, Yaw hoặc bấm Sử dụng vị trí hiện tại');
      return;
    }

    if (editingId) {
      const pt = setpoints.find((p) => p.id === editingId);
      if (!pt) {
        writeStationStatus('Setpoint không tồn tại');
        return;
      }
      pt.name = name;
      pt.x = x;
      pt.y = y;
      pt.yawDeg = yawDeg;
      pt.pointType = pointType;
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
      pointType,
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
    writeStationStatus(message);
  }

  async function runArrivalBeltCommands(pt) {
    const needsBelt = window.AmrStm32?.setpointNeedsBelt?.(pt);
    if (!needsBelt) return;

    if (!window.AmrStm32?.isBeltAvailable?.()) {
      throw new Error('STM32 chưa kết nối — không thể chạy lệnh băng tải');
    }

    const bt1 = pt.belt1Cmd || 'none';
    const bt2 = pt.belt2Cmd || 'none';
    setWorkflowStep('belt', `Đã đến ${pt.name} — chạy băng tải (BT1:${bt1}, BT2:${bt2})`);
    writeStationStatus(`Băng tải: ${pt.name} — chờ ACK STM32`);

    await window.AmrStm32.runSetpointBelts(pt);

    setWorkflowStep('belt', `Băng tải xong tại ${pt.name}`);
    writeStationStatus(`Băng tải xong: ${pt.name}`);
  }

  async function goToSelectedStation() {
    const pt = setpoints.find((p) => p.id === selectedId);
    if (!pt) {
      writeStationStatus('Chọn setpoint trong danh sách trước');
      return;
    }
    if (!window.AmrNavigation?.navigateAndWait) {
      writeStationStatus('Chưa kết nối Nav2');
      return;
    }
    const yawRad = (pt.yawDeg * Math.PI) / 180;
    if (window.AmrMap?.resetViewAfterNavGoal) {
      window.AmrMap.resetViewAfterNavGoal();
    }
    setWorkflowStep('goto', `Đang đi tới ${pt.name}...`);
    writeStationStatus(`Đang đi tới: ${pt.name}`);

    try {
      if (isMagneticLinePoint(pt)) {
        await window.AmrNavigation.navigateAndWait(pt.x, pt.y, yawRad, {
          destinationName: pt.name,
        });
        if (!window.AmrNavigation?.cancelNavigationAsync) {
          throw new Error('Không có dịch vụ chuyển quyền điều khiển khỏi Nav2');
        }
        await window.AmrNavigation.cancelNavigationAsync();
        if (!window.AmrMagneticLine?.start) {
          throw new Error('Line follower chưa sẵn sàng');
        }
        const lineMode = isHomePoint(pt) ? 'lùi theo line vào sạc' : 'bám line vào trạm';
        writeStationStatus(`Đã đến ${pt.name} — ${lineMode}`);
        await window.AmrMagneticLine.start(pt);
        writeStationStatus(`Đã vào trạm ${pt.name} ✓`);
      } else {
        await window.AmrNavigation.navigateAndWait(pt.x, pt.y, yawRad, {
          destinationName: pt.name,
        });
        await runArrivalBeltCommands(pt);
      }
    } catch (err) {
      const msg = err?.message || 'Workflow thất bại';
      writeStationStatus(`Thất bại tại ${pt.name}: ${msg}`);
      setWorkflowStep('goto', `Thất bại: ${pt.name}`);
    }
  }

  function autoRoute() {
    if (window.AmrProcess && window.AmrProcess.runAutoRoute) {
      window.AmrProcess.runAutoRoute();
      return;
    }
    writeStationStatus('Chưa có quy trình — thêm bước trong panel Quy trình');
  }

  function resetStation() {
    // Reset tiến trình Auto Route về ban đầu (giữ nguyên setpoint đang chọn).
    const ok = window.AmrProcess?.resetRoute?.();
    if (ok === false) {
      updateStationStatus('Auto Route đang chạy — nhấn Cancel trước khi Reset');
      return;
    }

    const stm32Promise = window.AmrStm32?.resetEstop?.()
      ?.then((res) => {
        console.info('[STM32] RESET_ESTOP ACK:', res?.message || 'ok');
        updateStationStatus(`Đã reset quy trình + STM32 RESET_ESTOP (${res?.stm32_state || 'ok'})`);
        return res;
      })
      .catch((err) => {
        console.error('[STM32] RESET_ESTOP failed:', err?.message || err);
        updateStationStatus(`Đã reset quy trình — STM32 RESET_ESTOP lỗi: ${err?.message || err}`);
      });

    if (!stm32Promise) {
      updateStationStatus('Đã reset quy trình — Auto Route sẽ chạy lại từ bước 1');
    }
    setWorkflowStep('setpoint', 'Đã reset quy trình chạy — sẵn sàng chạy lại từ đầu');
  }

  document.getElementById('btn-setpoint')?.addEventListener('click', openSetpointModal);
  document.getElementById('btn-auto-route').addEventListener('click', autoRoute);
  document.getElementById('btn-go-station').addEventListener('click', goToSelectedStation);
  document.getElementById('btn-station-reset').addEventListener('click', resetStation);
  if (stationSelect) {
    stationSelect.addEventListener('change', () => {
      selectSetpoint(stationSelect.value || null);
    });
  }
  btnEditSetpoint?.addEventListener('click', openEditSetpointModal);
  document.getElementById('btn-use-current').addEventListener('click', useCurrentPosition);
  document.getElementById('btn-save-point').addEventListener('click', savePoint);
  document.getElementById('btn-cancel-setpoint').addEventListener('click', closeSetpointModal);
  document.getElementById('setpoint-point-type').addEventListener(
    'change', () => applyPointTypeDefaults(true));
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
    const ros = window.AmrRos?.getRos?.();
    if (ros) {
      missionRequestTopic = new ROSLIB.Topic({
        ros,
        name: '/web_mission_request',
        messageType: 'std_msgs/msg/String',
      });
      cargoDoneTopic = new ROSLIB.Topic({
        ros,
        name: '/web_cargo_done',
        messageType: 'std_msgs/msg/String',
      });
      missionStatusTopic = new ROSLIB.Topic({
        ros,
        name: '/mission/status',
        messageType: 'std_msgs/msg/String',
      });
      missionStatusTopic.subscribe((msg) => {
        const status = missionStateFromData(msg.data);
        missionWaiters.slice().forEach((w) => w.onStatus(status));
      });
      dockRequestTopic = new ROSLIB.Topic({
        ros,
        name: '/web_dock_request',
        messageType: 'std_msgs/msg/String',
      });
      dockResponseTopic = new ROSLIB.Topic({
        ros,
        name: '/web_dock_response',
        messageType: 'std_msgs/msg/String',
      });
      dockResponseTopic.subscribe((msg) => {
        let status = null;
        try {
          status = JSON.parse(msg.data);
        } catch (err) {
          console.warn('dock response JSON:', err);
          return;
        }
        if (status.status === 'feedback') {
          const dist = Number(status.distance_remaining || 0).toFixed(2);
          setWorkflowStep('dock', `${status.mode}: ${status.detail} còn ${dist}m`);
        }
        dockWaiters.slice().forEach((w) => w.onStatus(status));
      });
      costmapRequestTopic = new ROSLIB.Topic({
        ros,
        name: '/web_costmap_request',
        messageType: 'std_msgs/msg/String',
      });
      costmapResponseTopic = new ROSLIB.Topic({
        ros,
        name: '/web_costmap_response',
        messageType: 'std_msgs/msg/String',
      });
      costmapResponseTopic.subscribe((msg) => {
        let status = null;
        try {
          status = JSON.parse(msg.data);
        } catch (err) {
          console.warn('costmap response JSON:', err);
          return;
        }
        if (status.status === 'succeeded') {
          setWorkflowStep('costmap', status.detail || 'Costmap updated');
        }
        costmapWaiters.slice().forEach((w) => w.onStatus(status));
      });
    }
    setWorkflowStep('connect', 'connected — load map or run SLAM');
  });

  window.addEventListener('amr-ros-disconnected', () => {
    if (missionStatusTopic) missionStatusTopic.unsubscribe();
    if (dockResponseTopic) dockResponseTopic.unsubscribe();
    if (costmapResponseTopic) costmapResponseTopic.unsubscribe();
    missionRequestTopic = null;
    cargoDoneTopic = null;
    missionStatusTopic = null;
    dockRequestTopic = null;
    dockResponseTopic = null;
    costmapRequestTopic = null;
    costmapResponseTopic = null;
    missionWaiters = [];
    dockWaiters = [];
    costmapWaiters = [];
  });

  window.addEventListener('amr-map-data-sync', (e) => {
    reloadSetpointsFromServer(e.detail?.name);
  });

  window.addEventListener('amr-ros-disconnected', () => {
    setWorkflowStep('connect', 'disconnected — chờ kết nối lại');
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
  setWorkflowStep('connect', 'đang kết nối…');

  window.AmrStations = {
    getSetpoints: () => [...setpoints],
    getSelectedId: () => selectedId,
    reloadFromServer: reloadSetpointsFromServer,
    setWorkflowStep,
    isApproachPoint,
    isHomePoint,
    isMagneticLinePoint,
    pointTypeLabel,
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
