/**
 * slam.js — SLAM ON/OFF + lưu map (/save_map_named)
 *
 * MiniPC có thể chạy slam_toolbox sẵn dưới nền.
 * - SLAM: ON  → bỏ pause slam_toolbox (quét map) + tạm pause Nav2
 * - SLAM: OFF → pause slam_toolbox (không quét) + resume Nav2
 */

(function () {
  let slamUiReady = false;
  let slamScanOn = false;
  let busy = false;
  let navLifecycleClient = null;
  let slamPauseClient = null;

  // nav2_msgs/srv/ManageLifecycleNodes
  const NAV_CMD_PAUSE = 1;
  const NAV_CMD_RESUME = 2;

  const btnScan = document.getElementById('btn-slam-scan');
  const btnNavMode = document.getElementById('btn-nav-mode');
  const slamStatusEl = document.getElementById('slam-status');

  function setSlamStatus(msg, color = '') {
    if (!slamStatusEl) return;
    slamStatusEl.textContent = msg || '';
    slamStatusEl.style.color = color || '';
  }

  function callNavLifecycle(command) {
    if (!navLifecycleClient) {
      return Promise.reject(new Error('Chưa kết nối lifecycle_manager_navigation'));
    }
    return new Promise((resolve, reject) => {
      navLifecycleClient.callService(
        new ROSLIB.ServiceRequest({ command }),
        (result) => {
          if (result?.success) resolve(result);
          else reject(new Error('ManageLifecycleNodes thất bại'));
        },
        (err) => reject(err || new Error('Lỗi ManageLifecycleNodes'))
      );
    });
  }

  /** slam_toolbox Pause là toggle; status=true nghĩa là đang pause nhận scan. */
  function toggleSlamPauseOnce() {
    if (!slamPauseClient) {
      return Promise.reject(new Error('Chưa kết nối /slam_toolbox/pause_new_measurements'));
    }
    return new Promise((resolve, reject) => {
      slamPauseClient.callService(
        new ROSLIB.ServiceRequest({}),
        (result) => resolve(!!result?.status),
        (err) => reject(err || new Error('Lỗi pause_new_measurements'))
      );
    });
  }

  /**
   * Đưa slam_toolbox về trạng thái paused mong muốn.
   * wantPaused=true  → SLAM tạm tắt (không quét)
   * wantPaused=false → SLAM đang quét
   */
  async function setSlamPaused(wantPaused) {
    let paused = await toggleSlamPauseOnce();
    if (paused === wantPaused) return paused;
    paused = await toggleSlamPauseOnce();
    if (paused !== wantPaused) {
      throw new Error(`Không đặt được SLAM ${wantPaused ? 'pause' : 'active'}`);
    }
    return paused;
  }

  function updateScanButton() {
    if (!btnScan) return;
    btnScan.textContent = `SLAM: ${slamScanOn ? 'ON' : 'OFF'}`;
    btnScan.classList.toggle('active', slamScanOn);
    btnScan.disabled = busy;
  }

  function notifyScanChanged() {
    window.dispatchEvent(new CustomEvent('amr-slam-scan', { detail: { enabled: slamScanOn } }));
  }

  async function setScanMode(enabled) {
    const next = !!enabled;
    if (next === slamScanOn || busy) return;
    busy = true;
    updateScanButton();

    try {
      // API mode manager owns the real process transition. ROSLIB remains as
      // compatibility fallback while the migration is in progress.
      if (window.AmrApi?.isAvailable?.()) {
        setSlamStatus(next ? 'Đang dừng Nav2/localization và khởi động SLAM...' : 'Đang dừng SLAM và khởi động lại localization/Nav2...', '#facc15');
        const result = await window.AmrApi.request('/api/slam/mode', {
          method: 'POST',
          body: JSON.stringify({
            enabled: next,
            mapName: next ? null : (document.getElementById('map-name-input')?.value.trim() || null),
          }),
        });
        slamScanOn = result.mode === 'slam';
        notifyScanChanged();
        if (btnNavMode) {
          btnNavMode.disabled = slamScanOn;
          if (slamScanOn) btnNavMode.title = 'Tắt SLAM trước khi bật Nav';
          else btnNavMode.removeAttribute('title');
        }
        setSlamStatus(slamScanOn ? 'Success · SLAM ON · Nav2/localization đã dừng' : 'Success · NORMAL · localization/Nav2 đã chạy', '#4ade80');
        return;
      }
      if (next) {
        setSlamStatus('Đang bật SLAM · tạm tắt Nav2...', '#facc15');
        window.AmrNavigation?.setNavMode?.(false);
        window.AmrNavigation?.cancelNavigationAsync?.().catch(() => {});
        if (btnNavMode) {
          btnNavMode.disabled = true;
          btnNavMode.title = 'Tắt SLAM trước khi bật Nav';
        }

        setSlamStatus('Đang kích hoạt slam_toolbox (quét map)...', '#facc15');
        await setSlamPaused(false);

        setSlamStatus('Đang tạm tắt Nav2...', '#facc15');
        await callNavLifecycle(NAV_CMD_PAUSE).catch((err) => {
          console.warn('Pause Nav2:', err);
        });

        slamScanOn = true;
        notifyScanChanged();
        setSlamStatus('Success · SLAM ON · map đang được quét · Nav2 tạm tắt', '#4ade80');
      } else {
        setSlamStatus('Đang tắt SLAM · mở lại Nav2...', '#facc15');

        setSlamStatus('Đang pause slam_toolbox...', '#facc15');
        await setSlamPaused(true);

        setSlamStatus('Đang bật lại Nav2...', '#facc15');
        await callNavLifecycle(NAV_CMD_RESUME).catch((err) => {
          console.warn('Resume Nav2:', err);
        });

        if (btnNavMode) {
          btnNavMode.disabled = false;
          btnNavMode.removeAttribute('title');
        }

        slamScanOn = false;
        notifyScanChanged();
        setSlamStatus('Success · SLAM OFF · Nav2 đã sẵn sàng', '#4ade80');
      }
    } catch (err) {
      console.warn('setScanMode:', err);
      setSlamStatus(
        `Lỗi: ${err.message || err} · kiểm tra slam_toolbox / Nav2 trên miniPC`,
        '#f87171'
      );
    } finally {
      busy = false;
      updateScanButton();
    }
  }

  const slamConfirmModal = document.getElementById('slam-confirm-modal');
  const slamConfirmTitle = document.getElementById('slam-confirm-title');
  const slamConfirmMsg = document.getElementById('slam-confirm-msg');
  const slamConfirmOk = document.getElementById('btn-slam-confirm-ok');
  const slamConfirmCancel = document.getElementById('btn-slam-confirm-cancel');
  let pendingSlamTarget = null;

  function openSlamConfirm(nextOn) {
    if (busy || nextOn === slamScanOn) return;
    pendingSlamTarget = nextOn;
    if (slamConfirmTitle) {
      slamConfirmTitle.textContent = nextOn ? 'Turn SLAM ON?' : 'Turn SLAM OFF?';
    }
    if (slamConfirmMsg) {
      slamConfirmMsg.textContent = nextOn
        ? 'Bật SLAM để quét map. Nav2 sẽ tạm tắt vì hai chế độ không chạy cùng lúc.'
        : 'Tắt SLAM (pause quét map) và bật lại Nav2 để điều hướng.';
    }
    if (slamConfirmOk) {
      slamConfirmOk.textContent = nextOn ? 'Turn ON' : 'Turn OFF';
      slamConfirmOk.classList.toggle('btn-danger', !nextOn);
    }
    slamConfirmModal?.classList.remove('hidden');
    slamConfirmModal?.setAttribute('aria-hidden', 'false');
  }

  function closeSlamConfirm() {
    pendingSlamTarget = null;
    slamConfirmModal?.classList.add('hidden');
    slamConfirmModal?.setAttribute('aria-hidden', 'true');
  }

  btnScan?.addEventListener('click', () => openSlamConfirm(!slamScanOn));
  slamConfirmCancel?.addEventListener('click', closeSlamConfirm);
  slamConfirmOk?.addEventListener('click', () => {
    const target = pendingSlamTarget;
    closeSlamConfirm();
    if (target == null) return;
    setScanMode(target);
  });
  slamConfirmModal?.addEventListener('click', (e) => {
    if (e.target === slamConfirmModal) closeSlamConfirm();
  });

  function initClients() {
    if (slamUiReady) return;
    slamUiReady = true;
    const ros = window.AmrRos?.getRos?.();
    if (!ros) return;

    navLifecycleClient = new ROSLIB.Service({
      ros,
      name: '/lifecycle_manager_navigation/manage_nodes',
      serviceType: 'nav2_msgs/srv/ManageLifecycleNodes',
    });

    slamPauseClient = new ROSLIB.Service({
      ros,
      name: '/slam_toolbox/pause_new_measurements',
      serviceType: 'slam_toolbox/srv/Pause',
    });

    setSlamStatus('Đang đồng bộ SLAM OFF (pause nền)...', '#facc15');
    // Mặc định: SLAM chạy nền nhưng pause; Nav2 dùng bình thường.
    setSlamPaused(true)
      .then(() => {
        slamScanOn = false;
        updateScanButton();
        notifyScanChanged();
        setSlamStatus('SLAM: OFF · Nav2 sẵn sàng', '#94a3b8');
      })
      .catch((err) => {
        console.warn('Không pause được slam_toolbox lúc khởi tạo:', err);
        setSlamStatus(
          'Chưa kết nối slam_toolbox — vẫn bật/tắt được trên web khi node sẵn sàng',
          '#f87171'
        );
      });

    const statusEl = document.getElementById('save-map-status');
    const nameInput = document.getElementById('map-name-input');
    const btnSave = document.getElementById('btn-save-map');
    if (!btnSave || !statusEl || !nameInput) return;

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
          statusEl.textContent = result.success
            ? `Đã lưu map: ${mapName}`
            : result.message;
          statusEl.style.color = result.success ? '#4ade80' : '#f87171';
          if (!result.success) return;

          const selectAfterRefresh = () => {
            const mapSelect = document.getElementById('map-select');
            if (!mapSelect) return;
            const opt = Array.from(mapSelect.options).find((o) => o.value === mapName);
            if (opt) mapSelect.value = mapName;
          };

          if (window.AmrLocalization?.refreshMapList) {
            window.AmrLocalization.refreshMapList({ silent: true });
            let tries = 0;
            const timer = setInterval(() => {
              tries += 1;
              const mapSelect = document.getElementById('map-select');
              const found = mapSelect && Array.from(mapSelect.options).some((o) => o.value === mapName);
              if (found || tries >= 20) {
                clearInterval(timer);
                selectAfterRefresh();
              }
            }, 150);
          }

          if (window.AmrMapData?.syncForMap) {
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

  window.addEventListener('amr-ros-connected', initClients);
  window.addEventListener('amr-auth-ready', async () => {
    if (!window.AmrApi?.isAvailable?.()) return;
    try {
      const state = await window.AmrApi.request('/api/slam/status');
      slamScanOn = state.mode === 'slam';
      updateScanButton();
      notifyScanChanged();
      setSlamStatus(slamScanOn ? 'SLAM: ON · Nav2/localization đã dừng' : 'NORMAL · Nav2/localization sẵn sàng', '#94a3b8');
    } catch (err) {
      console.warn('Không đọc được trạng thái SLAM:', err);
    }
  });

  window.AmrSlam = {
    isScanOn: () => slamScanOn,
    setScanMode,
  };
})();
