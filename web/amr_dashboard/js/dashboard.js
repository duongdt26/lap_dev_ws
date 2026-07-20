/**
 * Trạng thái tổng quan dành cho người vận hành.
 */
(function () {
  const connection = document.getElementById('header-connection');
  const mission = document.getElementById('header-mission');
  const battery = document.getElementById('header-battery');
  const safety = document.getElementById('header-safety');
  const stopButton = document.getElementById('btn-header-stop');
  const guidance = document.getElementById('operator-guidance');
  const position = document.getElementById('operator-position');
  const speed = document.getElementById('operator-speed');
  const reconnectButton = document.getElementById('btn-operator-reconnect');

  let connected = false;
  let missionState = 'idle';
  let selectedStation = null;

  function updateConnection(isConnected, pending) {
    connected = !!isConnected;
    connection.classList.toggle('health-online', connected);
    connection.classList.toggle('health-offline', !connected && !pending);
    connection.classList.toggle('health-pending', !!pending);
    connection.innerHTML = '<i></i>' + (
      connected ? 'Đã kết nối' : pending ? 'Đang kết nối' : 'Mất kết nối'
    );
    if (!connected && !pending) {
      guidance.textContent =
        'Không thể điều khiển robot. Kỹ thuật viên cần kiểm tra kết nối.';
    }
    reconnectButton.hidden = connected || pending;
  }

  function updateMission(state, detail) {
    missionState = state || 'idle';
    const labels = {
      idle: 'Chưa có nhiệm vụ',
      selected: 'Đã chọn điểm đến',
      navigating: 'Robot đang di chuyển',
      arrived: 'Đã đến nơi',
      failed: 'Nhiệm vụ thất bại',
      cancelled: 'Đã dừng nhiệm vụ',
      cancelling: 'Đang dừng robot',
    };
    mission.textContent = labels[missionState] || 'Đang xử lý';
    mission.className = 'health-pill mission-' + missionState;
    const active = missionState === 'navigating' || missionState === 'cancelling';
    stopButton.disabled = !active;

    if (missionState === 'navigating') {
      guidance.textContent = selectedStation
        ? 'Robot đang đi tới ' + selectedStation.name + '.'
        : 'Robot đang di chuyển tới điểm đã chọn.';
    } else if (missionState === 'arrived') {
      guidance.textContent = selectedStation
        ? 'Robot đã đến ' + selectedStation.name + ' an toàn.'
        : 'Robot đã hoàn thành nhiệm vụ.';
    } else if (missionState === 'failed') {
      guidance.textContent = detail || 'Không thể hoàn thành nhiệm vụ. Hãy xem cảnh báo.';
    } else if (missionState === 'cancelled') {
      guidance.textContent = 'Nhiệm vụ đã dừng. Có thể chọn một điểm đến khác.';
    }
  }

  function updateSafety(active) {
    safety.className = 'health-pill ' + (active ? 'health-online' : 'health-pending');
    safety.textContent = active
      ? 'Vùng an toàn: đang áp dụng'
      : 'Vùng an toàn: chưa xác nhận';
  }

  window.addEventListener('amr-ros-connected', () => {
    updateConnection(true, false);
  });
  window.addEventListener('amr-ros-disconnected', () => {
    updateConnection(false, false);
  });
  window.addEventListener('amr-station-selected', (event) => {
    selectedStation = event.detail?.station || null;
    if (!selectedStation) {
      updateMission('idle');
      guidance.textContent = 'Chọn một điểm đến bên dưới để bắt đầu.';
      return;
    }
    updateMission('selected');
    guidance.textContent =
      'Đã chọn ' + selectedStation.name + '. Nhấn “Bắt đầu di chuyển”.';
  });
  window.addEventListener('amr-destination-state', (event) => {
    selectedStation = event.detail?.station || selectedStation;
    updateMission(event.detail?.state, event.detail?.message);
  });
  window.addEventListener('amr-nav-status', (event) => {
    const state = event.detail?.state;
    if (state === 'navigating') updateMission('navigating');
    if (state === 'failed') updateMission('failed', event.detail?.detail);
    if (state === 'cancelled' || state === 'cancelling') updateMission(state);
  });
  window.addEventListener('amr-nav-arrived', () => updateMission('arrived'));
  window.addEventListener('amr-keepout-changed', (event) => {
    updateSafety(!!event.detail?.nav2Active);
  });
  window.addEventListener('amr-pose', (event) => {
    const pose = event.detail || {};
    if (Number.isFinite(Number(pose.x)) && Number.isFinite(Number(pose.y))) {
      position.textContent =
        Number(pose.x).toFixed(2) + ', ' + Number(pose.y).toFixed(2) + ' m';
    }
  });
  window.addEventListener('amr-odom', (event) => {
    const vx = Number(event.detail?.vx);
    speed.textContent = Number.isFinite(vx) ? Math.abs(vx).toFixed(2) + ' m/s' : '--';
  });

  stopButton.addEventListener('click', () => {
    updateMission('cancelling');
    window.AmrNavigation?.cancelNavigation?.();
  });
  reconnectButton.addEventListener('click', () => {
    updateConnection(false, true);
    window.AmrRos?.connect?.();
  });

  const batteryValue = document.getElementById('val-battery');
  const batteryObserver = new MutationObserver(() => {
    const value = batteryValue.textContent.trim();
    battery.textContent = 'Pin: ' + (value || '--');
  });
  batteryObserver.observe(batteryValue, { childList: true, characterData: true });

  updateConnection(false, true);
  updateMission('idle');
  updateSafety(!!window.AmrKeepout?.isNav2Active?.());
  setTimeout(() => {
    if (!window.AmrRos?.getRos?.()) {
      window.AmrRos?.connect?.();
    }
  }, 700);
})();
