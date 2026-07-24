/**
 * process.js — Robot process steps (setpoint sequence)
 */

(function () {
  let savedProcessNames = [];
  let currentProcessName = null;
  let processSteps = [];
  let dragFromIndex = null;
  let routeState = {
    running: false,
    activeIndex: -1,
    paused: false,
    pausedIndex: -1,
  };

  const stepsEl = document.getElementById('process-steps');
  const stationStatus = document.getElementById('station-status');
  const emptyEl = document.getElementById('process-empty');
  const addBar = document.getElementById('process-add-bar');
  const addSelect = document.getElementById('process-add-select');
  const btnAdd = document.getElementById('btn-process-add');
  const btnOpen = document.getElementById('btn-process-open');
  const btnSave = document.getElementById('btn-process-save');
  const workflowDetail = document.getElementById('workflow-detail');
  const workflowHeading = document.querySelector('.workflow-heading');

  const saveModal = document.getElementById('save-process-modal');
  const saveNameInput = document.getElementById('process-save-name');
  const saveNameList = document.getElementById('process-name-list');
  const openModal = document.getElementById('open-process-modal');
  const openSelect = document.getElementById('process-open-select');
  const openDetail = document.getElementById('open-process-detail');

  function getSetpoints() {
    return window.AmrStations ? window.AmrStations.getSetpoints() : [];
  }

  function setDetail(msg) {
    if (workflowDetail) workflowDetail.textContent = msg;
    if (window.AmrStations && window.AmrStations.setWorkflowStep) {
      window.AmrStations.setWorkflowStep(null, msg);
    }
  }

  function getProcessNames() {
    return [...savedProcessNames].sort((a, b) => a.localeCompare(b, 'vi'));
  }

  let boundMapName = null;

  async function refreshProcessList(mapName) {
    if (!window.AmrMapData?.listProcesses) return;
    try {
      const name = await window.AmrMapData.resolveMapName(mapName);
      if (!name) {
        savedProcessNames = [];
        return;
      }
      savedProcessNames = await window.AmrMapData.listProcesses(name);
    } catch (err) {
      console.warn('list processes:', err);
      savedProcessNames = [];
    }
  }

  function updateProcessHeading() {
    if (!workflowHeading) return;
    workflowHeading.textContent = currentProcessName
      ? `Process: ${currentProcessName}`
      : 'Process';
  }

  function migrateStepNames(steps) {
    if (!Array.isArray(steps)) return [];
    const setpoints = getSetpoints();
    const byId = Object.fromEntries(setpoints.map((sp) => [sp.id, sp]));
    return steps.map((step) => {
      if (typeof step !== 'string') return String(step);
      if (byId[step]) return byId[step].name;
      return step;
    });
  }

  async function reloadFromServer(mapName) {
    const name = await window.AmrMapData?.resolveMapName?.(mapName);
    if (!name) {
      savedProcessNames = [];
      if (!currentProcessName) {
        processSteps = [];
      }
      updateProcessHeading();
      renderProcessSteps();
      return;
    }

    await refreshProcessList(name);

    if (!currentProcessName) {
      updateProcessHeading();
      renderProcessSteps();
      return;
    }

    if (!window.AmrMapData?.loadProcess) return;
    try {
      const data = await window.AmrMapData.loadProcess(currentProcessName, name);
      processSteps = migrateStepNames(data.steps || []);
    } catch (err) {
      console.warn('load process:', err);
      processSteps = [];
      currentProcessName = null;
    }
    updateProcessHeading();
    renderProcessSteps();
  }

  async function switchToMap(mapName) {
    const name = (mapName || '').trim();
    if (!name) return;

    const changed = name !== boundMapName;
    boundMapName = name;

    if (changed) {
      currentProcessName = null;
      processSteps = [];
    }

    await reloadFromServer(name);
  }

  function populateProcessNameOptions() {
    const names = getProcessNames();
    if (saveNameList) {
      saveNameList.innerHTML = '';
      names.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        saveNameList.appendChild(opt);
      });
    }
    if (openSelect) {
      openSelect.innerHTML = '';
      if (!names.length) {
        openSelect.innerHTML = '<option value="">-- Chưa có process đã lưu --</option>';
        openSelect.disabled = true;
        if (openDetail) openDetail.textContent = 'Bấm Save process để lưu quy trình đầu tiên';
        return;
      }
      openSelect.disabled = false;
      names.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        openSelect.appendChild(opt);
      });
      updateOpenProcessDetail();
    }
  }

  async function updateOpenProcessDetail() {
    if (!openDetail || !openSelect) return;
    const name = openSelect.value;
    if (!name) {
      openDetail.textContent = '';
      return;
    }
    if (!window.AmrMapData?.loadProcess) return;
    try {
      const mapName = await window.AmrMapData.resolveMapName();
      const data = await window.AmrMapData.loadProcess(name, mapName);
      const labels = migrateStepNames(data.steps || []).join(' → ');
      openDetail.textContent = labels || 'Process trống';
    } catch {
      openDetail.textContent = '';
    }
  }

  async function openSaveProcessModal() {
    if (!saveModal) return;
    await refreshProcessList();
    populateProcessNameOptions();
    if (saveNameInput) {
      saveNameInput.value = currentProcessName || '';
      saveNameInput.focus();
      saveNameInput.select();
    }
    saveModal.classList.remove('hidden');
    saveModal.setAttribute('aria-hidden', 'false');
  }

  function closeSaveProcessModal() {
    if (!saveModal) return;
    saveModal.classList.add('hidden');
    saveModal.setAttribute('aria-hidden', 'true');
  }

  async function openOpenProcessModal() {
    if (!openModal) return;
    await refreshProcessList();
    populateProcessNameOptions();
    openModal.classList.remove('hidden');
    openModal.setAttribute('aria-hidden', 'false');
  }

  function closeOpenProcessModal() {
    if (!openModal) return;
    openModal.classList.add('hidden');
    openModal.setAttribute('aria-hidden', 'true');
  }

  async function confirmSaveProcess() {
    const name = saveNameInput?.value.trim();
    if (!name) {
      setDetail('Nhập tên process trước khi lưu');
      return;
    }
    if (!window.AmrMapData?.saveProcess) {
      setDetail('Chưa kết nối server — bấm Connect');
      return;
    }

    const mapName = window.AmrMapData.getCurrentMapName();
    if (!mapName) {
      setDetail('Nạp map trước khi lưu process');
      return;
    }

    try {
      await window.AmrMapData.saveProcess(name, {
        steps: [...processSteps],
        updatedAt: new Date().toISOString(),
      }, mapName);
      currentProcessName = name;
      await refreshProcessList();
      updateProcessHeading();
      closeSaveProcessModal();

      const n = processSteps.length;
      setDetail(n ? `Đã lưu process "${name}" (${n} bước)` : `Đã lưu process trống "${name}"`);
    } catch (err) {
      setDetail(`Lỗi lưu process: ${err.message}`);
    }
  }

  async function confirmOpenProcess() {
    const name = openSelect?.value;
    if (!name) {
      setDetail('Chọn process để mở');
      return;
    }
    if (!window.AmrMapData?.loadProcess) {
      setDetail('Chưa kết nối server — bấm Connect');
      return;
    }

    try {
      const mapName = await window.AmrMapData.resolveMapName();
      const data = await window.AmrMapData.loadProcess(name, mapName);
      processSteps = migrateStepNames(data.steps || []);
      currentProcessName = name;
      updateProcessHeading();
      renderProcessSteps();
      closeOpenProcessModal();

      const n = processSteps.length;
      setDetail(n ? `Đã mở process "${name}" (${n} bước)` : `Đã mở process trống "${name}"`);
    } catch (err) {
      setDetail(`Lỗi mở process: ${err.message}`);
    }
  }

  function populateAddSelect() {
    const setpoints = getSetpoints();
    addSelect.innerHTML = '<option value="">-- Chọn setpoint --</option>';
    setpoints.forEach((sp) => {
      const opt = document.createElement('option');
      opt.value = sp.id;
      opt.textContent = sp.name;
      addSelect.appendChild(opt);
    });
  }

  function reorderProcessSteps(fromIndex, toIndex) {
    if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
    const [item] = processSteps.splice(fromIndex, 1);
    processSteps.splice(toIndex, 0, item);
  }

  function computeDropIndex(targetIndex, insertAfter) {
    if (dragFromIndex == null) return null;
    let toIndex = insertAfter ? targetIndex + 1 : targetIndex;
    if (dragFromIndex < toIndex) toIndex -= 1;
    return toIndex;
  }

  function clearDropIndicators() {
    stepsEl.querySelectorAll('.process-step').forEach((el) => {
      el.classList.remove('drop-before', 'drop-after');
    });
  }

  function setStationStatus(msg) {
    if (stationStatus) stationStatus.textContent = msg;
  }

  window.addEventListener('amr-line-status', (event) => {
    const status = event.detail || {};
    if (!status.request_id || status.state === 'idle') return;
    const markerText = status.marker > 0
      ? (status.workflow === 'home'
        ? ' | line ngang sạc'
        : ` | line ngang ${status.marker}/3`)
      : '';
    const message = `Line từ: ${status.message || status.state}${markerText}`;
    setDetail(message);
    setStationStatus(message);
  });

  function stopAutoRoute() {
    // Cancel = dừng tạm thời (STOP). Nếu Auto Route đang chạy thì nhớ bước
    // đang dở để lần sau nhấn Auto Route đi lại từ đầu bước đó (resume).
    if (routeState.running) {
      routeState.paused = true;
      routeState.pausedIndex = routeState.activeIndex;
      routeState.running = false;
      const stepName = processSteps[routeState.pausedIndex] || '?';
      setDetail(`Auto Route tạm dừng tại bước ${routeState.pausedIndex + 1} (${stepName}) — nhấn Auto Route để đi tiếp`);
      setStationStatus(`Tạm dừng: ${stepName} (nhấn Auto Route để tiếp tục)`);
      renderProcessSteps();
    }
    if (window.AmrNavigation?.cancelNavigation) {
      window.AmrNavigation.cancelNavigation();
    }
    if (window.AmrMagneticLine?.cancel) {
      window.AmrMagneticLine.cancel();
    }
  }

  // Reset tiến trình Auto Route về ban đầu (chưa chạy). Chỉ khi KHÔNG đang chạy.
  function resetRoute() {
    if (routeState.running) {
      setDetail('Auto Route đang chạy — nhấn Cancel trước khi Reset');
      setStationStatus('Đang chạy — Cancel trước khi Reset');
      return false;
    }
    const hadProgress = routeState.paused || routeState.activeIndex >= 0;
    routeState = {
      running: false,
      activeIndex: -1,
      paused: false,
      pausedIndex: -1,
    };
    renderProcessSteps();
    if (hadProgress) {
      setDetail('Đã reset quy trình — Auto Route sẽ chạy lại từ bước 1');
      setStationStatus('Đã reset quy trình — chạy lại từ bước 1');
    }
    return true;
  }

  async function runBeltStep(setpoint) {
    const needsBelt = window.AmrStm32?.setpointNeedsBelt?.(setpoint);
    if (!needsBelt) return;

    if (!window.AmrStm32?.isBeltAvailable?.()) {
      throw new Error('STM32 chưa kết nối — không thể chạy lệnh băng tải');
    }

    const bt1 = setpoint.belt1Cmd || 'none';
    const bt2 = setpoint.belt2Cmd || 'none';
    setDetail(`Auto Route: băng tải tại ${setpoint.name} (BT1:${bt1}, BT2:${bt2})...`);
    setStationStatus(`Băng tải: ${setpoint.name} — chờ ACK STM32`);

    await window.AmrStm32.runSetpointBelts(setpoint);

    setDetail(`Auto Route: hoàn thành băng tải tại ${setpoint.name}`);
    setStationStatus(`Băng tải xong: ${setpoint.name} — sẵn sàng điểm tiếp theo`);
  }

  async function runAutoRoute() {
    if (routeState.running) {
      setDetail('Auto Route đang chạy...');
      return;
    }

    if (!processSteps.length) {
      setDetail('Chưa có bước trong quy trình — bấm + để thêm');
      setStationStatus('Chưa có quy trình để chạy');
      return;
    }

    if (!window.AmrNavigation?.sendNavGoalAsync) {
      setDetail('Chưa kết nối Nav2');
      setStationStatus('Chưa kết nối Nav2');
      return;
    }

    const byName = Object.fromEntries(getSetpoints().map((sp) => [sp.name, sp]));
    // Resume: nếu đang pause thì đi lại từ đầu bước bị cancel (redo_step).
    const resuming = routeState.paused && routeState.pausedIndex >= 0;
    const startIndex = resuming
      ? Math.min(routeState.pausedIndex, processSteps.length - 1)
      : 0;
    routeState = {
      running: true,
      activeIndex: startIndex,
      paused: false,
      pausedIndex: -1,
    };
    renderProcessSteps();

    const names = processSteps.map((n) => n || '?').join(' → ');
    if (resuming) {
      setStationStatus(`Auto Route tiếp tục từ bước ${startIndex + 1}: ${names}`);
    } else {
      setStationStatus(`Auto Route: ${names}`);
    }

    for (let i = startIndex; i < processSteps.length; i += 1) {
      if (!routeState.running) break;

      const sp = byName[processSteps[i]];
      if (!sp) {
        setDetail(`Bước ${i + 1}: setpoint không tồn tại`);
        setStationStatus(`Lỗi bước ${i + 1}: setpoint đã xóa`);
        break;
      }

      routeState.activeIndex = i;
      renderProcessSteps();
      scrollActiveStepIntoView();

      const label = `${sp.name} (${i + 1}/${processSteps.length})`;
      setDetail(`Auto Route: đang đi tới ${label}`);
      setStationStatus(`Auto Route: đang đi tới ${label}`);

      try {
        if (window.AmrStations?.isMagneticLinePoint?.(sp)) {
          const yawRad = (sp.yawDeg * Math.PI) / 180;
          const isHome = window.AmrStations?.isHomePoint?.(sp);
          const pointLabel = isHome ? 'Home' : 'Approach Pose';
          setDetail(`Auto Route: tới ${pointLabel} ${label}`);
          setStationStatus(`${pointLabel}: đang đi tới ${label}`);
          await window.AmrNavigation.navigateAndWait(sp.x, sp.y, yawRad, {
            postArrivalDelayMs: 500,
            destinationName: sp.name,
          });
          if (!window.AmrNavigation?.cancelNavigationAsync) {
            throw new Error('Không có dịch vụ chuyển quyền điều khiển khỏi Nav2');
          }
          setDetail(`Auto Route: đã đến ${sp.name}, dừng Nav2`);
          await window.AmrNavigation.cancelNavigationAsync();
          if (!window.AmrMagneticLine?.start) {
            throw new Error('Line follower chưa sẵn sàng');
          }
          const lineAction = isHome ? 'lùi theo line vào sạc' : 'bám line vào trạm';
          setDetail(`Auto Route: đã đến ${sp.name}, ${lineAction}`);
          setStationStatus(`${pointLabel} ${sp.name}: ${lineAction}`);
          await window.AmrMagneticLine.start(sp);
          const arrivedMsg = isHome
            ? `Đã lùi vào Home ${sp.name} ✓ — dừng tại line ngang sạc`
            : `Đã vào trạm ${sp.name} ✓ — line ngang cuối`;
          setDetail(`Auto Route: ${arrivedMsg}`);
          setStationStatus(arrivedMsg);
        } else {
          const yawRad = (sp.yawDeg * Math.PI) / 180;
          await window.AmrNavigation.navigateAndWait(sp.x, sp.y, yawRad, {
            postArrivalDelayMs: 2000,
            destinationName: sp.name,
          });

          if (!routeState.running) break;

          const arrivedMsg = `Đã đến ${sp.name} ✓ — goal success`;
          setDetail(`Auto Route: ${arrivedMsg}`);
          setStationStatus(arrivedMsg);
          await runBeltStep(sp);
        }

        if (!routeState.running) break;

        if (!routeState.running) break;

        if (i < processSteps.length - 1) {
          const nextName = processSteps[i + 1];
          setDetail(`Auto Route: chuyển sang ${nextName} (${i + 2}/${processSteps.length})`);
        }
      } catch (err) {
        // Người dùng bấm Cancel = tạm dừng, không phải lỗi. stopAutoRoute đã
        // lưu pausedIndex; giữ nguyên trạng thái để lần sau resume.
        if (routeState.paused) {
          renderProcessSteps();
          return;
        }
        const msg = err?.message || 'Lỗi navigation';
        setDetail(`Auto Route dừng tại ${sp.name}: ${msg}`);
        setStationStatus(`Auto Route dừng: ${msg}`);
        routeState = {
          running: false,
          activeIndex: -1,
          paused: false,
          pausedIndex: -1,
        };
        renderProcessSteps();
        return;
      }
    }

    // Bị pause giữa chừng (break do running=false + paused): giữ trạng thái.
    if (routeState.paused) {
      renderProcessSteps();
      return;
    }

    const finished = routeState.running;
    routeState = {
      running: false,
      activeIndex: -1,
      paused: false,
      pausedIndex: -1,
    };
    renderProcessSteps();

    if (finished) {
      setDetail(`Auto Route hoàn thành (${processSteps.length} bước)`);
      setStationStatus('Auto Route hoàn thành ✓');
    }
  }

  function scrollActiveStepIntoView() {
    const active = stepsEl.querySelector('.process-step.running');
    if (active) active.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function applyRouteClasses(li, index) {
    if (routeState.paused && routeState.pausedIndex >= 0) {
      if (index === routeState.pausedIndex) li.classList.add('running');
      else if (index < routeState.pausedIndex) li.classList.add('completed');
      return;
    }
    if (!routeState.running) return;
    if (index === routeState.activeIndex) li.classList.add('running');
    else if (index < routeState.activeIndex) li.classList.add('completed');
  }

  function bindStepInteractions(li, stepName, index) {
    li.draggable = !routeState.running;

    li.addEventListener('dragstart', (e) => {
      if (routeState.running) {
        e.preventDefault();
        return;
      }
      if (e.target.closest('.process-step-remove')) {
        e.preventDefault();
        return;
      }
      dragFromIndex = index;
      li.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(index));
    });

    li.addEventListener('dragend', () => {
      dragFromIndex = null;
      li.classList.remove('dragging');
      clearDropIndicators();
    });

    li.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (dragFromIndex == null) return;

      const rect = li.getBoundingClientRect();
      const insertAfter = e.clientY > rect.top + rect.height / 2;
      clearDropIndicators();
      li.classList.add(insertAfter ? 'drop-after' : 'drop-before');
    });

    li.addEventListener('dragleave', (e) => {
      if (!li.contains(e.relatedTarget)) {
        li.classList.remove('drop-before', 'drop-after');
      }
    });

    li.addEventListener('drop', (e) => {
      e.preventDefault();
      if (dragFromIndex == null) return;

      const targetIndex = [...stepsEl.children].indexOf(li);
      const rect = li.getBoundingClientRect();
      const insertAfter = e.clientY > rect.top + rect.height / 2;
      const toIndex = computeDropIndex(targetIndex, insertAfter);

      clearDropIndicators();
      if (toIndex == null || toIndex === dragFromIndex) return;

      reorderProcessSteps(dragFromIndex, toIndex);
      dragFromIndex = null;
      renderProcessSteps();
      setDetail('Đã sắp xếp lại thứ tự bước');
    });

    li.querySelector('.process-step-remove').addEventListener('click', (e) => {
      e.stopPropagation();
      if (routeState.running) return;
      const idx = processSteps.indexOf(stepName);
      if (idx >= 0) processSteps.splice(idx, 1);
      renderProcessSteps();
    });
  }

  function renderProcessSteps() {
    const setpoints = getSetpoints();
    const byName = Object.fromEntries(setpoints.map((sp) => [sp.name, sp]));

    stepsEl.innerHTML = '';
    emptyEl.style.display = processSteps.length ? 'none' : 'block';

    processSteps.forEach((stepName, index) => {
      const sp = byName[stepName];
      const li = document.createElement('li');
      li.className = 'process-step';
      li.dataset.stepName = stepName;

      const name = sp ? sp.name : `(đã xóa: ${stepName})`;
      li.innerHTML =
        `<span class="process-step-num">${index + 1}</span>` +
        `<span class="process-step-name">${escapeHtml(name)}</span>` +
        `<button type="button" class="process-step-remove" aria-label="Xóa bước" title="Xóa">×</button>`;

      applyRouteClasses(li, index);
      bindStepInteractions(li, stepName, index);
      stepsEl.appendChild(li);
    });
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function showAddBar() {
    const setpoints = getSetpoints();
    if (!setpoints.length) {
      setDetail('Chưa có setpoint — bấm Setpoint để thêm');
      return;
    }
    populateAddSelect();
    addBar.classList.remove('hidden');
    addSelect.focus();
  }

  function hideAddBar() {
    addBar.classList.add('hidden');
    addSelect.value = '';
  }

  function addStep(setpointId) {
    if (!setpointId) return;
    const sp = getSetpoints().find((p) => p.id === setpointId);
    if (!sp) return;
    processSteps.push(sp.name);
    renderProcessSteps();
    addSelect.value = '';
    setDetail(`Đã thêm: ${sp.name}`);
  }

  btnAdd.addEventListener('click', (e) => {
    e.stopPropagation();
    showAddBar();
  });

  addBar.addEventListener('click', (e) => {
    e.stopPropagation();
  });

  addSelect.addEventListener('change', () => {
    addStep(addSelect.value);
    addBar.classList.remove('hidden');
  });

  document.addEventListener('mousedown', (e) => {
    if (addBar.classList.contains('hidden')) return;
    if (addBar.contains(e.target) || btnAdd.contains(e.target)) return;
    hideAddBar();
  });

  btnSave.addEventListener('click', openSaveProcessModal);
  btnOpen?.addEventListener('click', openOpenProcessModal);

  document.getElementById('btn-process-save-confirm')?.addEventListener('click', confirmSaveProcess);
  document.getElementById('btn-process-save-cancel')?.addEventListener('click', closeSaveProcessModal);
  document.getElementById('btn-process-open-confirm')?.addEventListener('click', confirmOpenProcess);
  document.getElementById('btn-process-open-cancel')?.addEventListener('click', closeOpenProcessModal);
  openSelect?.addEventListener('change', updateOpenProcessDetail);

  saveModal?.addEventListener('click', (e) => {
    if (e.target === saveModal) closeSaveProcessModal();
  });
  openModal?.addEventListener('click', (e) => {
    if (e.target === openModal) closeOpenProcessModal();
  });

  saveNameInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') confirmSaveProcess();
  });

  document.getElementById('btn-nav-cancel')?.addEventListener('click', stopAutoRoute);

  renderProcessSteps();

  window.addEventListener('amr-setpoints-changed', renderProcessSteps);

  window.addEventListener('amr-map-data-sync', (e) => {
    switchToMap(e.detail?.name);
  });

  window.addEventListener('amr-data-updated', (e) => {
    if (e.detail === 'process') {
      reloadFromServer(window.AmrMapData?.getCurrentMapName());
    }
  });

  window.AmrProcess = {
    getSteps: () => [...processSteps],
    getCurrentName: () => currentProcessName,
    getSavedNames: () => getProcessNames(),
    runAutoRoute,
    stopAutoRoute,
    resetRoute,
    reload: reloadFromServer,
    reloadFromServer,
    switchToMap,
  };
})();
