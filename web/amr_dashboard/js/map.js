/**
 * map.js — Vẽ /map lên canvas + icon robot từ /amcl_pose
 *
 * Cần: localization_launch (map_server) HOẶC slam_toolbox đang publish /map
 * 
 * Pose: /amcl_pose (localization) HOẶC TF map→base_footprint (SLAM)
 * 
 *  * Initial pose: /initialpose (khi bật chế độ trên web)
 */

// document.getElementById('btn-connect').addEventListener('click', () => {
//     setTimeout(initMap, 500);
//   });
  

    let canvasListenersAttached = false;
    let mapInitialized = false;
    let odomPollStarted = false;
    let webMapTopic = null;
    let sourceMapTopic = null;
    let sourceMapFallbackTimer = null;

    window.addEventListener('amr-ros-connected', () => {
      initMap();
    });

    window.addEventListener('amr-ros-disconnected', () => {
      stopMapSubscriptions();
      mapInitialized = false;
      lastMapFingerprint = '';
      currentVx = 0;
      odomReceived = false;
      lastOdomTime = 0;
      teleopMoving = false;
      mapLiveMode = true;
      mapStatusBase = '';
      mapMsg = null;
      setZoomControlsEnabled(false);
      updateMapStatusHint();
    });

    window.addEventListener('amr-auth-user', () => {
      if (shouldStreamMap()) {
        mapInitialized = false;
        ensureMapInitialized();
      } else {
        // Auth có thể sẵn sàng trước rosbridge; chỉ đánh dấu initialized sau
        // khi initMap đã tạo các service client dùng cho Station/Process.
        disableMapForOperator(false);
      }
    });

    window.addEventListener('amr-theme-changed', () => {
      if (mapMsg && view) {
        rebuildMapCache();
        scheduleRedraw();
      }
    });

    window.addEventListener('amr-setpoints-changed', () => {
      scheduleRedraw();
    });

    window.addEventListener('amr-map-data-sync', () => {
      updateMapStatusHint();
    });

    window.addEventListener('amr-map-loaded', () => {
      updateMapStatusHint();
    });

    window.addEventListener('amr-slam-scan', (e) => {
      const enabled = !!e.detail?.enabled;
      updateMapInteractionMode();
      updateMapTitle();
      updateMapStatusHint();
      // SLAM ON/OFF đều cần bỏ fingerprint + sync — OFF: map_server vừa publish map tĩnh.
      lastMapFingerprint = '';
      lastMapSizeKey = null;
      userViewLocked = false;
      if (enabled) {
        robotPose = null;
        mapLiveMode = true;
        const status = document.getElementById('map-status');
        if (status) status.textContent = 'Đang chờ map từ slam_toolbox…';
      } else {
        mapLiveMode = false;
        const status = document.getElementById('map-status');
        if (status) status.textContent = 'Đang nạp map localization…';
      }
      const sync = () => {
        window.AmrMapSync?.forceMapResync?.().catch(() => {});
      };
      sync();
      setTimeout(sync, 800);
      setTimeout(sync, 2500);
      setTimeout(sync, 6000);
      const mapName = e.detail?.mapName;
      if (!enabled && mapName && window.AmrLocalization?.notifyMapLoaded) {
        setTimeout(() => {
          window.AmrLocalization.notifyMapLoaded(mapName).catch(() => {});
        }, 1200);
      }
    });

    // Cùng nguồn pose với HUD (telemetry /robot_pose_map) — tránh canvas đứng khi rosbridge trễ.
    window.addEventListener('amr-pose', (e) => {
      const d = e.detail;
      if (!d || d.x == null || d.y == null) return;
      const yaw = d.yawDeg != null ? d.yawDeg : d.yaw;
      if (yaw == null) return;
      if (
        robotPose
        && robotPose.x === d.x
        && robotPose.y === d.y
        && robotPose.yawDeg === yaw
      ) {
        return;
      }
      robotPose = { x: d.x, y: d.y, yawDeg: yaw };
      scheduleRedraw();
    });

  // Trạng thái dùng chung khi vẽ
  let mapMsg = null;       // bản tin /map mới nhất
  let robotPose = null;    // { x, y, yawDeg } từ AMCL
  let view = null;         // scale + offset để fit canvas

  let poseMode = false;
  let poseDragStart = null;   // pixel {px, py} khi mousedown
  let initialPosePub = null;
  
  let planPath = [];        // mảng {x,y} tọa độ world từ /plan
  let navMode = false;
  let navGoalCallback = null;
  let keepoutMode = false;
  let keepoutZones = [];
  let keepoutDraft = [];

  let mapCacheCanvas = null;   // offscreen: vẽ map 1 lần, không vẽ lại mỗi pose
  let dragCurrent = null;      // pixel hiện tại khi đang kéo (preview mũi tên)
  let redrawScheduled = false;
  let ctxRef = null;
  let canvasRef = null;
  let baseView = null;         // view fit ban đầu (reset)
  let lastMapSizeKey = null;   // width×height×resolution — không gồm origin (SLAM đổi origin liên tục)
  let userViewLocked = false;  // user đã zoom/pan → không auto-fit lại
  let mapCacheRebuildQueued = false;

  const ZOOM_FACTOR = 1.25;
  const PAN_STEP = 40;
  const MIN_SCALE = 0.2;
  const MAX_SCALE = 20;
  const VX_STOP = 0.02;
  const ODOM_STALE_MS = 600;
  const MAP_THROTTLE_MS = 1000;
  const SOURCE_MAP_FALLBACK_MS = 3000;

  let currentVx = 0;
  let odomReceived = false;
  let lastOdomTime = 0;
  let teleopMoving = false;
  let mapLiveMode = true;
  let mapStatusBase = '';

  const MAP_TOPIC_QOS = {
    durability: 'transient_local',
    reliability: 'reliable',
    history: 'keep_last',
    depth: 1,
  };

  // /map của map_server / slam_toolbox là transient-local.
  const SOURCE_MAP_TOPIC_QOS = {
    durability: 'transient_local',
    reliability: 'reliable',
    history: 'keep_last',
    depth: 1,
  };

  function shouldStreamMap() {
    // Operator cần theo dõi live map ở cả sim và robot thật giống Setter.
    return true;
  }

  function stopMapSubscriptions() {
    if (sourceMapFallbackTimer) {
      clearTimeout(sourceMapFallbackTimer);
      sourceMapFallbackTimer = null;
    }
    for (const topic of [webMapTopic, sourceMapTopic]) {
      if (!topic) continue;
      try { topic.unsubscribe(); } catch (_) { /* socket có thể đã đóng */ }
    }
    webMapTopic = null;
    sourceMapTopic = null;
  }

  function disableMapForOperator(initialized = false) {
    stopMapSubscriptions();
    mapInitialized = initialized;
    mapMsg = null;
    mapCacheCanvas = null;
    view = null;
    lastMapFingerprint = '';
    lastMapSizeKey = null;
    const title = document.getElementById('map-area-title');
    if (title) title.textContent = 'OPERATOR · MAP STREAM OFF';
    const canvas = document.getElementById('map-canvas');
    const ctx = canvas?.getContext('2d');
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  let getMapStatusClient = null;
  let requestMapSyncClient = null;
  let setActiveMapClient = null;

  function initMapSyncClients(ros) {
    getMapStatusClient = new ROSLIB.Service({
      ros,
      name: '/get_map_status',
      serviceType: 'amr_web_interfaces/srv/GetMapStatus',
    });
    requestMapSyncClient = new ROSLIB.Service({
      ros,
      name: '/request_map_sync',
      serviceType: 'std_srvs/srv/Trigger',
    });
    setActiveMapClient = new ROSLIB.Service({
      ros,
      name: '/set_active_map',
      serviceType: 'amr_web_interfaces/srv/SetActiveMap',
    });
  }

  function requestMapSync() {
    return new Promise((resolve, reject) => {
      if (!requestMapSyncClient) {
        reject(new Error('not connected'));
        return;
      }
      requestMapSyncClient.callService(
        new ROSLIB.ServiceRequest({}),
        (res) => (res.success ? resolve(res) : reject(new Error(res.message || 'sync failed'))),
        reject
      );
    });
  }

  function getMapStatus() {
    return new Promise((resolve, reject) => {
      if (!getMapStatusClient) {
        reject(new Error('not connected'));
        return;
      }
      getMapStatusClient.callService(
        new ROSLIB.ServiceRequest({}),
        resolve,
        reject
      );
    });
  }

  function setActiveMapName(name) {
    return new Promise((resolve, reject) => {
      if (!setActiveMapClient) {
        reject(new Error('not connected'));
        return;
      }
      setActiveMapClient.callService(
        new ROSLIB.ServiceRequest({ map_name: name }),
        (res) => (res.success ? resolve(res) : reject(new Error(res.message || 'set active map failed'))),
        reject
      );
    });
  }

  function syncMapFromBridge() {
    return getMapStatus()
      .then((status) => {
        if (status.loaded) {
          return requestMapSync().then(() => status);
        }
        return status;
      })
      .catch((err) => {
        console.warn('map sync:', err);
        return null;
      });
  }

  window.AmrMapSync = {
    requestMapSync,
    getMapStatus,
    setActiveMapName,
    syncMapFromBridge,
    forceMapResync: requestMapSync,
  };

  let lastMapFingerprint = '';

  function mapFingerprint(msg) {
    if (!msg || !msg.info) return '';
    const stamp = msg.info.map_load_time || {};
    const headerStamp = msg.header?.stamp || {};
    const origin = msg.info.origin?.position || {};
    return [
      msg.info.width,
      msg.info.height,
      msg.info.resolution,
      origin.x,
      origin.y,
      stamp.sec,
      stamp.nanosec,
      headerStamp.sec,
      headerStamp.nanosec,
      msg.data ? msg.data.length : 0,
    ].join(',');
  }

  function isSlamScanning() {
    return !!window.AmrSlam?.isScanOn?.();
  }

  function computeMapLiveMode() {
    // SLAM ON: luôn live để map web cập nhật khi khung map không phình thêm.
    if (isSlamScanning()) return true;
    if (navMode || teleopMoving) return true;
    if (!odomReceived) return false;
    const stale = Date.now() - lastOdomTime > ODOM_STALE_MS;
    if (stale) return false;
    return Math.abs(currentVx) > VX_STOP;
  }

  function setZoomControlsEnabled(enabled) {
    const panel = document.querySelector('.map-view-controls');
    if (panel) panel.classList.toggle('map-controls-disabled', !enabled);
  }

  function getSelectedMapName() {
    return (window.AmrMapData?.getCurrentMapName?.() || '').trim();
  }

  function updateMapTitle() {
    const titleEl = document.getElementById('map-area-title');
    if (!titleEl) return;
    const scanning = !!window.AmrSlam?.isScanOn?.();
    const name = getSelectedMapName();
    if (scanning) {
      titleEl.textContent = name ? `MAP: ${name} · SCANNING` : 'MAP: SCANNING (SLAM)';
      titleEl.classList.add('map-scanning');
    } else {
      titleEl.textContent = name ? `MAP: ${name}` : 'MAP: —';
      titleEl.classList.remove('map-scanning');
    }
  }

  function updateMapStatusHint() {
    const el = document.getElementById('map-status');
    if (!el) return;
    updateMapTitle();
    const name = getSelectedMapName();
    if (!mapMsg && !name) {
      el.textContent = 'Chưa có bản đồ - chạy localization hoặc SLAM';
      return;
    }
    const base = name
      ? `Map: ${name}`
      : (mapStatusBase ||
        (mapMsg
          ? `Map: ${mapMsg.info.width}×${mapMsg.info.height} @ ${mapMsg.info.resolution}m/cell`
          : 'Map: —'));
    const modeHint = mapMsg
      ? (isSlamScanning()
        ? ' · LIVE SLAM'
        : (mapLiveMode
          ? ' · LIVE (Nav/teleop/Vx — zoom tắt)'
          : ' · Đóng băng — có thể zoom / đặt pose'))
      : '';
    el.textContent = base + modeHint;
  }

  function updateMapInteractionMode() {
    const live = computeMapLiveMode();
    if (live !== mapLiveMode) {
      mapLiveMode = live;
      if (live) userViewLocked = false;
    }
    setZoomControlsEnabled(!mapLiveMode);
    updateMapStatusHint();
  }

  function onOdomSample(vx) {
    currentVx = vx;
    odomReceived = true;
    lastOdomTime = Date.now();
    updateMapInteractionMode();
  }

  function applyMapMessage(msg) {
    if (!canvasRef) return;
    const isFirstMap = mapMsg === null;
    const fp = mapFingerprint(msg);
    if (fp) lastMapFingerprint = fp;
    mapMsg = msg;
    mapStatusBase = `Map: ${msg.info.width}×${msg.info.height} @ ${msg.info.resolution}m/cell`;
    const sizeKey = mapSizeKey(msg.info);
    const sizeChanged = sizeKey !== lastMapSizeKey;

    if (!view) {
      computeView(msg, canvasRef);
      lastMapSizeKey = sizeKey;
    } else if (sizeChanged && !userViewLocked) {
      computeView(msg, canvasRef);
      lastMapSizeKey = sizeKey;
    } else {
      view.mapW = msg.info.width;
      view.mapH = msg.info.height;
      if (sizeChanged) lastMapSizeKey = sizeKey;
    }

    queueMapCacheRebuild();
    updateMapStatusHint();
    if (isFirstMap) {
      window.dispatchEvent(new CustomEvent('amr-map-ready'));
    }
  }

  window.addEventListener('amr-odom', (e) => {
    onOdomSample(e.detail.vx);
  });

  window.addEventListener('amr-teleop-motion', (e) => {
    teleopMoving = !!e.detail.moving;
    updateMapInteractionMode();
  });

  // API công khai — tạo sớm để localization/navigation gọi được ngay sau khi connect
  window.AmrMap = {
    setPoseMode(enabled) {
      poseMode = enabled;
      const canvas = document.getElementById('map-canvas');
      canvas.classList.toggle('pose-mode', enabled);
      if (enabled) canvas.classList.remove('nav-mode');
    },
    setNavMode(enabled) {
      navMode = enabled;
      const canvas = document.getElementById('map-canvas');
      canvas.classList.toggle('nav-mode', enabled);
      if (enabled) canvas.classList.remove('pose-mode');
      updateMapInteractionMode();
    },
    setKeepoutMode(enabled) {
      keepoutMode = !!enabled;
      const canvas = document.getElementById('map-canvas');
      canvas.classList.toggle('keepout-mode', keepoutMode);
      if (keepoutMode) {
        poseMode = false;
        navMode = false;
        canvas.classList.remove('pose-mode', 'nav-mode');
      }
      updateMapInteractionMode();
    },
    setKeepoutZones(zones) {
      keepoutZones = Array.isArray(zones) ? zones : [];
      scheduleRedraw();
    },
    setKeepoutDraft(points) {
      keepoutDraft = Array.isArray(points) ? points : [];
      scheduleRedraw();
    },
    clientToWorld(clientX, clientY) {
      const canvas = canvasRef || document.getElementById('map-canvas');
      if (!canvas || !mapMsg || !view) return null;
      const rect = canvas.getBoundingClientRect();
      const px = (clientX - rect.left) * (canvas.width / rect.width);
      const py = (clientY - rect.top) * (canvas.height / rect.height);
      const point = canvasToWorld(px, py, mapMsg.info);
      return { x: point.wx, y: point.wy };
    },
    canEditKeepout() {
      return !!mapMsg && !!view;
    },
    setNavGoalCallback(cb) { navGoalCallback = cb; },

    clearPlanPath() {
      planPath = [];
      scheduleRedraw();
    },
    resetView() { resetMapView(); },
    resetViewAfterNavGoal() { resetMapViewAfterNavGoal(); },
    hasMap() { return mapMsg !== null; },
    publishInitialPose(x, y, yawRad) {
      return publishInitialPose(Number(x) || 0, Number(y) || 0, Number(yawRad) || 0);
    },
  };

  function applyViewChange() {
    if (!mapMsg || !view) return;
    rebuildMapCache();
    scheduleRedraw();
  }

  function queueMapCacheRebuild() {
    if (mapCacheRebuildQueued) return;
    mapCacheRebuildQueued = true;
    requestAnimationFrame(() => {
      mapCacheRebuildQueued = false;
      if (!mapMsg || !view) return;
      rebuildMapCache();
      scheduleRedraw();
    });
  }

  function zoomAt(factor, cx, cy) {
    if (mapLiveMode) return;
    const canvas = canvasRef || document.getElementById('map-canvas');
    if (!view || !canvas) return;
    const newScale = Math.max(MIN_SCALE, Math.min(view.scale * factor, MAX_SCALE));
    if (Math.abs(newScale - view.scale) < 1e-6) return;
    view.offsetX = cx - (cx - view.offsetX) * (newScale / view.scale);
    view.offsetY = cy - (cy - view.offsetY) * (newScale / view.scale);
    view.scale = newScale;
    userViewLocked = true;
    applyViewChange();
  }

  function panMap(dx, dy) {
    if (mapLiveMode || !view) return;
    view.offsetX += dx;
    view.offsetY += dy;
    userViewLocked = true;
    applyViewChange();
  }

  function resetMapView(force = false) {
    if (!mapMsg || !canvasRef) return;
    if (!force && mapLiveMode) return;
    computeView(mapMsg, canvasRef);
    userViewLocked = false;
    applyViewChange();
  }

  function resetMapViewAfterNavGoal() {
    requestAnimationFrame(() => resetMapView(true));
  }

  let viewControlsAttached = false;

  function initViewControls() {
    if (viewControlsAttached) return;
    viewControlsAttached = true;

    const canvas = document.getElementById('map-canvas');
    canvasRef = canvas;

    document.getElementById('map-zoom-in').addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      zoomAt(ZOOM_FACTOR, canvas.width / 2, canvas.height / 2);
    });
    document.getElementById('map-zoom-out').addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      zoomAt(1 / ZOOM_FACTOR, canvas.width / 2, canvas.height / 2);
    });
    document.getElementById('map-pan-up').addEventListener('click', () => panMap(0, PAN_STEP));
    document.getElementById('map-pan-down').addEventListener('click', () => panMap(0, -PAN_STEP));
    document.getElementById('map-pan-left').addEventListener('click', () => panMap(PAN_STEP, 0));
    document.getElementById('map-pan-right').addEventListener('click', () => panMap(-PAN_STEP, 0));
    document.getElementById('map-reset-view').addEventListener('click', resetMapView);

    canvas.addEventListener('wheel', (e) => {
      if (!view || mapLiveMode) return;
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const cx = (e.clientX - rect.left) * scaleX;
      const cy = (e.clientY - rect.top) * scaleY;
      zoomAt(e.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR, cx, cy);
    }, { passive: false });
  }

  initViewControls();
  setZoomControlsEnabled(false);
  initCanvasResizeObserver();
  // Fit khung sớm (trước khi có map) để Live Map đã to sẵn
  requestAnimationFrame(() => resizeCanvasToContainer(false));
  window.addEventListener('load', () => {
    resizeCanvasToContainer(false);
    updateMapStatusHint();
  });
  updateMapStatusHint();

  if (!odomPollStarted) {
    odomPollStarted = true;
    setInterval(() => {
      if (odomReceived) updateMapInteractionMode();
    }, 400);
  }

  function initMap() {
    if (mapInitialized) return;

    const ros = window.AmrRos.getRos();
    if (!ros) {
      return;
    }

    // Giữ nhánh này để tương thích nếu sau này có chế độ tắt map theo cấu hình.
    if (!shouldStreamMap()) {
      initMapSyncClients(ros);
      disableMapForOperator(true);
      return;
    }

    const canvas = document.getElementById('map-canvas');
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) {
      console.warn('map init: chưa có canvas/context');
      return;
    }


    // ── Khởi tạo offscreen canvas ──
    ctxRef = ctx;
    canvasRef = canvas;

    // ── Subscribe /web/map (map_bridge đồng bộ từ /map cho nhiều client) ──
    try {
      initMapSyncClients(ros);

      function handleMapMessage(msg) {
        const fp = mapFingerprint(msg);
        const mapChanged = fp && fp !== lastMapFingerprint;
        // Cached republish giữ nguyên timestamp; bỏ qua ở cả SLAM để không
        // raster hóa lại hàng trăm nghìn ô cho cùng một bản tin.
        if (mapMsg && fp && !mapChanged) return;
        if (mapChanged) lastMapFingerprint = fp;
        applyMapMessage(msg);
      }

      webMapTopic = new ROSLIB.Topic({
        ros,
        name: '/web/map',
        messageType: 'nav_msgs/msg/OccupancyGrid',
        qos: MAP_TOPIC_QOS,
        throttle_rate: MAP_THROTTLE_MS,
        queue_length: 1,
      });
      webMapTopic.subscribe((msg) => {
        // Nếu bridge xuất hiện sau fallback thì quay lại đúng một nguồn map.
        if (sourceMapTopic) {
          try { sourceMapTopic.unsubscribe(); } catch (_) {}
          sourceMapTopic = null;
        }
        handleMapMessage(msg);
      });

      // Chỉ dùng /map trực tiếp khi map_bridge thực sự không trả dữ liệu.
      // Trước đây subscribe đồng thời cả hai topic làm băng thông tăng gấp đôi.
      sourceMapFallbackTimer = setTimeout(() => {
        sourceMapFallbackTimer = null;
        if (mapMsg || !shouldStreamMap() || !ros.isConnected) return;
        sourceMapTopic = new ROSLIB.Topic({
          ros,
          name: '/map',
          messageType: 'nav_msgs/msg/OccupancyGrid',
          qos: SOURCE_MAP_TOPIC_QOS,
          throttle_rate: MAP_THROTTLE_MS,
          queue_length: 1,
        });
        sourceMapTopic.subscribe(handleMapMessage);
      }, SOURCE_MAP_FALLBACK_MS);

      // Chỉ khóa init sau khi hai subscription map đã được gửi thành công.
      mapInitialized = true;
    } catch (err) {
      mapInitialized = false;
      console.error('map init failed:', err);
      const status = document.getElementById('map-status');
      if (status) status.textContent = `Lỗi khởi tạo map: ${err.message || err}`;
      return;
    }

    // Resize chỉ là phần hiển thị; lỗi ở đây không được chặn subscription map.
    try {
      resizeCanvasToContainer(true);
    } catch (err) {
      console.warn('map canvas resize:', err);
    }

    setTimeout(() => syncMapFromBridge(), 400);

    const odomTopic = new ROSLIB.Topic({
      ros,
      name: '/odometry/filtered',
      messageType: 'nav_msgs/msg/Odometry',
    });
    odomTopic.subscribe((msg) => {
      onOdomSample(msg.twist.twist.linear.x);
    });

    updateMapInteractionMode();
  
    // ── Subscribe /plan (đường đi Nav2) ──
    const planTopic = new ROSLIB.Topic({
      ros,
      name: '/plan',
      messageType: 'nav_msgs/msg/Path',
    });
    planTopic.subscribe((msg) => {
      planPath = msg.poses.map(p => ({ x: p.pose.position.x, y: p.pose.position.y }));
      if (mapMsg) scheduleRedraw();
    });

    // Nav2 đôi khi publish plan ở topic khác
    const planTopic2 = new ROSLIB.Topic({
      ros,
      name: '/received_global_plan',
      messageType: 'nav_msgs/msg/Path',
    });
    planTopic2.subscribe((msg) => {
      if (msg.poses && msg.poses.length > 0) {
        planPath = msg.poses.map(p => ({ x: p.pose.position.x, y: p.pose.position.y }));
        if (mapMsg) scheduleRedraw();
      }
    });

    // Bridge publish topic rỗng khi /cancel_nav được gọi
    const planClearTopic = new ROSLIB.Topic({
      ros,
      name: '/web_plan_clear',
      messageType: 'nav_msgs/msg/Path',
    });
    planClearTopic.subscribe(() => {
      planPath = [];
      scheduleRedraw();
    });

    // ── 3. Vị trí robot khi SLAM (không có AMCL) — dùng TF ──
    // const tfClient = new ROSLIB.TFClient({
    //     ros,
    //     fixedFrame: 'map',
    //     angularThres: 0.01,
    //     transThres: 0.01,
    //     });
    
        // tfClient.subscribe('base_footprint', (tf) => {
        // robotPose = {
        //     x: tf.translation.x,
        //     y: tf.translation.y,
        //     yawDeg: quaternionToYawDeg(tf.rotation),
        // };
        // if (mapMsg) redraw(ctx, canvas);
        // });

            // Vị trí robot khi SLAM (không có /amcl_pose) — dùng TF map → base_footprint
    // const tfClient = new ROSLIB.TFClient({
    //   ros,
    //   fixedFrame: 'map',
    //   angularThres: 0.01,
    //   transThres: 0.01,
    // });

    // Pose từ TF (SLAM / AMCL / Nav) — nav_pose_bridge_node publish /robot_pose_map
    const robotPoseMapTopic = new ROSLIB.Topic({
      ros,
      name: '/robot_pose_map',
      messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
    });
    robotPoseMapTopic.subscribe((msg) => {
      applyRobotPoseMsg(msg);
    });

    const amclPoseTopic = new ROSLIB.Topic({
      ros,
      name: '/amcl_pose',
      messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
    });
    amclPoseTopic.subscribe((msg) => {
      if (msg.header.frame_id && msg.header.frame_id !== 'map') return;
      applyRobotPoseMsg(msg);
    });

    // slam_toolbox publish /pose (PoseStamped) — backup khi TF/AMCL chưa sẵn.
    const slamPoseTopic = new ROSLIB.Topic({
      ros,
      name: '/pose',
      messageType: 'geometry_msgs/msg/PoseStamped',
    });
    slamPoseTopic.subscribe((msg) => {
      if (!isSlamScanning()) return;
      if (msg.header?.frame_id && msg.header.frame_id !== 'map') return;
      const p = msg.pose?.position;
      const q = msg.pose?.orientation;
      if (!p || !q) return;
      const yawDeg = quaternionToYawDeg(q);
      robotPose = { x: p.x, y: p.y, yawDeg };
      window.__amrPose = { x: p.x, y: p.y, yawDeg };
      window.dispatchEvent(new CustomEvent('amr-pose', { detail: window.__amrPose }));
      scheduleRedraw();
    });

    function applyRobotPoseMsg(msg) {
      const p = msg.pose.pose.position;
      const q = msg.pose.pose.orientation;
      const yawDeg = quaternionToYawDeg(q);
      robotPose = { x: p.x, y: p.y, yawDeg };
      window.__amrPose = { x: p.x, y: p.y, yawDeg };
      window.dispatchEvent(new CustomEvent('amr-pose', { detail: window.__amrPose }));
      scheduleRedraw();
    }

    // tfClient.subscribe('base_footprint', (tf) => {
    //   robotPose = {
    //     x: tf.translation.x,
    //     y: tf.translation.y,
    //     yawDeg: quaternionToYawDeg(tf.rotation),
    //   };
    //   if (mapMsg) redraw(ctx, canvas);
    // });

    // ── 4. Publish initial pose (AMCL) ──
    initialPosePub = new ROSLIB.Topic({
        ros,
        name: '/initialpose',
        messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
      });

      if (!canvasListenersAttached) {
        canvasListenersAttached = true;

      
  
        // Click + kéo trên canvas để đặt vị trí + hướng
        canvas.addEventListener('mousedown', (e) => {
          // if (!poseMode || !mapMsg || !view) return;
          if ((!poseMode && !navMode) || !mapMsg || !view) return;
          const rect = canvas.getBoundingClientRect();
          const scaleX = canvas.width / rect.width;
          const scaleY = canvas.height / rect.height;
          poseDragStart = {
            px: (e.clientX - rect.left) * scaleX,
            py: (e.clientY - rect.top) * scaleY,
          };
        });


        canvas.addEventListener('mousemove', (e) => {
          if ((!poseMode && !navMode) || !poseDragStart || !mapMsg || !view) return;
          const rect = canvas.getBoundingClientRect();
          const scaleX = canvas.width / rect.width;
          const scaleY = canvas.height / rect.height;
          dragCurrent = {
            px: (e.clientX - rect.left) * scaleX,
            py: (e.clientY - rect.top) * scaleY,
          };
          scheduleRedraw();
        });
    
        canvas.addEventListener('mouseup', (e) => {
          // if (!poseMode || !poseDragStart || !mapMsg || !view) return;
          if ((!poseMode && !navMode) || !poseDragStart || !mapMsg || !view) return;
          const rect = canvas.getBoundingClientRect();
          const scaleX = canvas.width / rect.width;
          const scaleY = canvas.height / rect.height;
          const endPx = (e.clientX - rect.left) * scaleX;
          const endPy = (e.clientY - rect.top) * scaleY;
    
          const startWorld = canvasToWorld(poseDragStart.px, poseDragStart.py, mapMsg.info);
          const endWorld = canvasToWorld(endPx, endPy, mapMsg.info);
    
          let yaw = Math.atan2(
            endWorld.wy - startWorld.wy,
            endWorld.wx - startWorld.wx
          );
          // Kéo quá ngắn → mặc định hướng 0
          const dragDist = Math.hypot(endPx - poseDragStart.px, endPy - poseDragStart.py);
          if (dragDist < 5) yaw = 0;
    
          // publishInitialPose(startWorld.wx, startWorld.wy, yaw);
          if (navMode && navGoalCallback) {
            navGoalCallback(startWorld.wx, startWorld.wy, yaw);
            resetMapViewAfterNavGoal();
          } else {
            publishInitialPose(startWorld.wx, startWorld.wy, yaw);
          }
          dragCurrent = null;
          poseDragStart = null;
        });

        canvas.addEventListener('touchstart', (e) => {
          if ((!poseMode && !navMode) || !mapMsg || !view) return;
          e.preventDefault();
          const t = e.touches[0];
          const rect = canvas.getBoundingClientRect();
          const scaleX = canvas.width / rect.width;
          const scaleY = canvas.height / rect.height;
          poseDragStart = {
            px: (t.clientX - rect.left) * scaleX,
            py: (t.clientY - rect.top) * scaleY,
          };
        }, { passive: false });

        // canvas.addEventListener('touchend', (e) => {
        //   if (!poseMode || !poseDragStart || !mapMsg || !view) return;
        //   const t = e.changedTouches[0];
        //   const rect = canvas.getBoundingClientRect();
        //   const scaleX = canvas.width / rect.width;
        //   const scaleY = canvas.height / rect.height;
        //   const endPx = (t.clientX - rect.left) * scaleX;
        //   const endPy = (t.clientY - rect.top) * scaleY;
        //   const startWorld = canvasToWorld(poseDragStart.px, poseDragStart.py, mapMsg.info);
        //   const endWorld = canvasToWorld(endPx, endPy, mapMsg.info);
        //   let yaw = Math.atan2(endWorld.wy - startWorld.wy, endWorld.wx - startWorld.wx);
        //   const dragDist = Math.hypot(endPx - poseDragStart.px, endPy - poseDragStart.py);
        //   if (dragDist < 5) yaw = 0;
        //   publishInitialPose(startWorld.wx, startWorld.wy, yaw);
        //   poseDragStart = null;
        // });

        canvas.addEventListener('touchend', (e) => {
          if ((!poseMode && !navMode) || !poseDragStart || !mapMsg || !view) return;
          e.preventDefault();
          const t = e.changedTouches[0];
          const rect = canvas.getBoundingClientRect();
          const scaleX = canvas.width / rect.width;
          const scaleY = canvas.height / rect.height;
          const endPx = (t.clientX - rect.left) * scaleX;
          const endPy = (t.clientY - rect.top) * scaleY;
          const startWorld = canvasToWorld(poseDragStart.px, poseDragStart.py, mapMsg.info);
          const endWorld = canvasToWorld(endPx, endPy, mapMsg.info);
          let yaw = Math.atan2(endWorld.wy - startWorld.wy, endWorld.wx - startWorld.wx);
          const dragDist = Math.hypot(endPx - poseDragStart.px, endPy - poseDragStart.py);
          if (dragDist < 5) yaw = 0;
          if (navMode && navGoalCallback) {
            navGoalCallback(startWorld.wx, startWorld.wy, yaw);
            resetMapViewAfterNavGoal();
          } else {
            publishInitialPose(startWorld.wx, startWorld.wy, yaw);
          }
          poseDragStart = null;
        }, { passive: false });

          }
      
        // API cho localization.js bật/tắt chế độ initial pose
        // window.AmrMap = {
        //   setPoseMode(enabled) { poseMode = enabled; canvas.classList.toggle('pose-mode', enabled); },
        //   setNavMode(enabled)  { navMode  = enabled; canvas.classList.toggle('nav-mode',  enabled); },
        //   setNavGoalCallback(cb) { navGoalCallback = cb; },
        // };

          // API cho localization.js bật/tắt chế độ
        // btnPoseMode.addEventListener('click', () => {
        //     poseMode = !poseMode;
        //     btnPoseMode.textContent = `Đặt vị trí ban đầu: ${poseMode ? 'BẬT' : 'TẮT'}`;
        //     btnPoseMode.classList.toggle('active', poseMode);
        
        //     // Đợi map.js tạo AmrMap (sau ~500ms khi connect)
        //     function applyPoseMode() {
        //       if (window.AmrMap) {
        //         window.AmrMap.setPoseMode(poseMode);
        //       } else {
        //         setTimeout(applyPoseMode, 200);
        //       }
        //     }
        //     applyPoseMode();
        // });
  }

  // Tránh mất sự kiện amr-ros-connected khi rosbridge kết nối trong lúc các
  // file script khác còn đang tải. Nếu init trước đó lỗi, tự thử lại mỗi giây.
  function ensureMapInitialized() {
    const ros = window.AmrRos?.getRos?.();
    if (!mapInitialized && ros?.isConnected) initMap();
  }

  setInterval(ensureMapInitialized, 1000);
  window.addEventListener('load', ensureMapInitialized);
  
  /** Fit toàn bộ map vào canvas, giữ tỉ lệ */
  function mapSizeKey(info) {
    return `${info.width},${info.height},${info.resolution}`;
  }

  function computeView(msg, canvas) {
    const w = msg.info.width;
    const h = msg.info.height;
    // Fill canvas as much as possible (tiny margin so edges aren't clipped)
    const pad = 4;
    const availW = Math.max(1, canvas.width - pad * 2);
    const availH = Math.max(1, canvas.height - pad * 2);
    const scale = Math.min(availW / w, availH / h);
    const drawW = w * scale;
    const drawH = h * scale;
    view = {
      scale,
      offsetX: (canvas.width - drawW) / 2,
      offsetY: (canvas.height - drawH) / 2,
      mapW: w,
      mapH: h,
    };
    baseView = { ...view };
  }

  /** Canvas pixel size = khung Live Map → map trắng to hơn, ít viền đen */
  function resizeCanvasToContainer(forceRefit) {
    const wrap = document.querySelector('.map-canvas-wrap');
    const canvas = canvasRef || document.getElementById('map-canvas');
    if (!wrap || !canvas) return false;

    const rect = wrap.getBoundingClientRect();
    const nextW = Math.max(320, Math.floor(rect.width));
    const nextH = Math.max(240, Math.floor(rect.height));
    if (nextW < 40 || nextH < 40) return false;

    const changed = canvas.width !== nextW || canvas.height !== nextH;
    if (!changed && !forceRefit) return false;

    if (changed) {
      canvas.width = nextW;
      canvas.height = nextH;
    }

    canvasRef = canvas;
    if (mapMsg) {
      if (!userViewLocked || forceRefit) {
        computeView(mapMsg, canvas);
        userViewLocked = false;
      }
      rebuildMapCache();
      scheduleRedraw();
    }
    return changed;
  }

  let resizeObserverAttached = false;
  function initCanvasResizeObserver() {
    if (resizeObserverAttached) return;
    resizeObserverAttached = true;
    const wrap = document.querySelector('.map-canvas-wrap');
    if (!wrap || typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', () => resizeCanvasToContainer(false));
      return;
    }
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => resizeCanvasToContainer(false));
    });
    ro.observe(wrap);
  }
  
  /** Tọa độ ROS map (mét) → pixel trên canvas */
  function worldToCanvas(wx, wy, info) {
    const res = info.resolution;
    const ox = info.origin.position.x;
    const oy = info.origin.position.y;
    // Ô map (pixel map): từ góc origin
    const mx = (wx - ox) / res;
    const my = (wy - oy) / res;
    // OccupancyGrid: trục Y map hướng lên; canvas Y hướng xuống → lật Y
    const px = view.offsetX + mx * view.scale;
    const py = view.offsetY + (view.mapH - my) * view.scale;
    return { px, py };
  }
  
  /** Pixel canvas → tọa độ ROS map (mét) — ngược worldToCanvas */
  function canvasToWorld(px, py, info) {
    const mx = (px - view.offsetX) / view.scale;
    const my = (py - view.offsetY) / view.scale;
    const mapY = view.mapH - my;
    return {
        wx: mx * info.resolution + info.origin.position.x,
        wy: mapY * info.resolution + info.origin.position.y,
    };
    }

    function yawToQuaternion(yaw) {
    const hz = yaw / 2;
    return { x: 0, y: 0, z: Math.sin(hz), w: Math.cos(hz) };
    }

    function publishInitialPose(x, y, yawRad) {
    if (!initialPosePub) {
      const ros = window.AmrRos?.getRos?.();
      if (!ros) return false;
      initialPosePub = new ROSLIB.Topic({
        ros,
        name: '/initialpose',
        messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
      });
    }
    const q = yawToQuaternion(yawRad);
    initialPosePub.publish(new ROSLIB.Message({
        // header: { frame_id: 'map' },
        header: {
            stamp: { sec: 0, nanosec: 0 },
            frame_id: 'map',
          },
        pose: {
        pose: {
            position: { x, y, z: 0 },
            orientation: q,
        },
        // Covariance gần giống RViz mặc định (x, y, yaw)
        covariance: [
            0.25, 0, 0, 0, 0, 0,
            0, 0.25, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0.0685,
        ],
        },
    }));
    const statusEl = document.getElementById('map-status');
    if (statusEl) {
      statusEl.textContent =
        `Initial pose: (${x.toFixed(2)}, ${y.toFixed(2)}) yaw=${(yawRad * 180 / Math.PI).toFixed(1)}°`;
    }
    return true;
    }

    /** Palette map — chỉ vẽ local, không đụng băng thông ROS */
    function getMapPalette() {
      const light = document.documentElement.getAttribute('data-theme') === 'light';
      if (light) {
        return {
          bg: [226, 232, 240, 255],       // ngoài map
          unknown: [186, 198, 212, 255],  // chưa quét
          free: [248, 250, 252, 255],     // trống
          occupied: [30, 41, 59, 255],    // tường / vật cản
          softOcc: [100, 116, 139, 255],  // chiếm dụng thấp
        };
      }
      return {
        bg: [14, 20, 28, 255],
        unknown: [42, 52, 66, 255],
        free: [232, 238, 245, 255],
        occupied: [15, 23, 36, 255],
        softOcc: [90, 105, 125, 255],
      };
    }

    function writeRgba(buf, i, rgba) {
      buf[i] = rgba[0];
      buf[i + 1] = rgba[1];
      buf[i + 2] = rgba[2];
      buf[i + 3] = rgba[3];
    }

    /** Vẽ map tĩnh 1 lần vào offscreen canvas (ImageData — nhanh hơn fillRect từng ô) */
    function rebuildMapCache() {
      if (!mapMsg || !view) return;
      const canvas = canvasRef || document.getElementById('map-canvas');
      if (!canvas) return;
      if (!mapCacheCanvas) {
        mapCacheCanvas = document.createElement('canvas');
      }
      mapCacheCanvas.width = canvas.width;
      mapCacheCanvas.height = canvas.height;
      const c = mapCacheCanvas.getContext('2d');
      const info = mapMsg.info;
      const w = info.width;
      const h = info.height;
      const data = mapMsg.data;
      const pal = getMapPalette();

      // Nền ngoài vùng map
      c.fillStyle = `rgba(${pal.bg[0]},${pal.bg[1]},${pal.bg[2]},1)`;
      c.fillRect(0, 0, mapCacheCanvas.width, mapCacheCanvas.height);

      // Raster map ở độ phân giải gốc → scale 1 lần (mượt + nhanh)
      const tile = document.createElement('canvas');
      tile.width = w;
      tile.height = h;
      const tctx = tile.getContext('2d');
      const img = tctx.createImageData(w, h);
      const px = img.data;

      for (let row = 0; row < h; row++) {
        const srcRow = row * w;
        // OccupancyGrid: row 0 = dưới → lật lên canvas
        const dstRow = (h - 1 - row) * w;
        for (let col = 0; col < w; col++) {
          const val = data[srcRow + col];
          const i = (dstRow + col) * 4;
          if (val < 0) writeRgba(px, i, pal.unknown);
          else if (val === 0) writeRgba(px, i, pal.free);
          else if (val >= 50) writeRgba(px, i, pal.occupied);
          else writeRgba(px, i, pal.softOcc);
        }
      }
      tctx.putImageData(img, 0, 0);

      const drawW = w * view.scale;
      const drawH = h * view.scale;
      c.imageSmoothingEnabled = view.scale < 1;
      c.drawImage(tile, view.offsetX, view.offsetY, drawW, drawH);

      // Viền nhẹ quanh bản đồ cho tách nền
      c.strokeStyle = document.documentElement.getAttribute('data-theme') === 'light'
        ? 'rgba(13, 148, 136, 0.35)'
        : 'rgba(45, 212, 191, 0.28)';
      c.lineWidth = 1;
      c.strokeRect(
        Math.floor(view.offsetX) + 0.5,
        Math.floor(view.offsetY) + 0.5,
        Math.ceil(drawW),
        Math.ceil(drawH)
      );
    }
  
    /** Gom nhiều message pose liên tiếp → chỉ vẽ 1 frame (real-time, không lag queue) */
    function scheduleRedraw() {
      if (redrawScheduled || !ctxRef) return;
      redrawScheduled = true;
      requestAnimationFrame(() => {
        redrawScheduled = false;
        redraw(ctxRef, canvasRef);
      });
    }

  /** Vẽ map và robot */
  // function redraw(ctx, canvas) {
  //   if (!mapMsg || !view) return;
  
  //   const info = mapMsg.info;
  //   const w = info.width;
  //   const h = info.height;
  //   const data = mapMsg.data;
  
  //   ctx.fillStyle = '#222';
  //   ctx.fillRect(0, 0, canvas.width, canvas.height);
  
  //   // Vẽ từng ô occupancy
  //   for (let row = 0; row < h; row++) {
  //     for (let col = 0; col < w; col++) {
  //       const val = data[row * w + col];
  //       if (val === -1) ctx.fillStyle = '#555';       // chưa biết
  //       else if (val === 0) ctx.fillStyle = '#eee';   // trống
  //       else if (val >= 50) ctx.fillStyle = '#111';   // vật cản
  //       else ctx.fillStyle = '#999';                  // vùng xám
  
  //       // row 0 = hàng dưới trong ROS → lật lên canvas
  //       const mx = col;
  //       const my = h - 1 - row;
  //       const x = view.offsetX + mx * view.scale;
  //       const y = view.offsetY + my * view.scale;
  //       ctx.fillRect(x, y, Math.ceil(view.scale), Math.ceil(view.scale));
  //     }
  //   }
  
  //   // Vẽ đường path Nav2
  //   if (planPath.length > 1) {
  //     ctx.strokeStyle = '#60a5fa';
  //     ctx.lineWidth = 2;
  //     ctx.beginPath();
  //     planPath.forEach((pt, i) => {
  //       const { px, py } = worldToCanvas(pt.x, pt.y, info);
  //       if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  //     });
  //     ctx.stroke();
  //   }

  //   // Vẽ robot (tam giác hướng theo yaw)
  //   if (robotPose) {
  //     drawRobot(ctx, robotPose, info);
  //   }
  // }

  function redraw(ctx, canvas) {
    if (!mapMsg || !view) return;
    const info = mapMsg.info;

    // Layer 1: map tĩnh (cache)
    if (mapCacheCanvas) {
      ctx.drawImage(mapCacheCanvas, 0, 0);
    } else {
      ctx.fillStyle = '#222';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    // Layer 2: trục XY tại tâm bản đồ (tham chiếu hướng)
    drawKeepoutZones(ctx, info);

    // Layer 2: trục XY tại tâm bản đồ (tham chiếu hướng)
    drawMapAxes(ctx, info);

    // Layer 3: setpoint + tên điểm
    drawSetpoints(ctx, info);

    // Layer 4: global path (to, rõ)
    if (planPath.length > 1) {
      drawPlanPath(ctx, info);
    }

    // Layer 5: preview mũi tên khi đang kéo (giống RViz)
    if (poseDragStart && dragCurrent) {
      drawDragArrow(ctx, poseDragStart, dragCurrent, poseMode ? '#facc15' : '#f97316');
    }

    // Layer 6: robot
    if (robotPose) {
      drawRobot(ctx, robotPose, info);
    }
  }

  function drawKeepoutPolygon(ctx, info, points, draft = false, label = '') {
    if (!Array.isArray(points) || points.length === 0) return;
    const canvasPoints = points
      .filter((point) => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)))
      .map((point) => worldToCanvas(Number(point.x), Number(point.y), info));
    if (!canvasPoints.length) return;

    ctx.save();
    ctx.beginPath();
    canvasPoints.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.px, point.py);
      else ctx.lineTo(point.px, point.py);
    });
    if (!draft && canvasPoints.length >= 3) ctx.closePath();
    if (!draft && canvasPoints.length >= 3) {
      ctx.fillStyle = 'rgba(239, 68, 68, 0.30)';
      ctx.fill();
    }
    ctx.strokeStyle = draft ? '#facc15' : '#ef4444';
    ctx.lineWidth = draft ? 2 : 2.5;
    ctx.setLineDash(draft ? [7, 5] : []);
    ctx.stroke();
    ctx.setLineDash([]);

    canvasPoints.forEach((point, index) => {
      ctx.beginPath();
      ctx.arc(point.px, point.py, draft ? 4 : 3, 0, Math.PI * 2);
      ctx.fillStyle = draft && index === 0 ? '#22c55e' : (draft ? '#facc15' : '#ef4444');
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    const name = String(label || '').trim();
    if (name && canvasPoints.length >= 1) {
      const cx = canvasPoints.reduce((sum, p) => sum + p.px, 0) / canvasPoints.length;
      const cy = canvasPoints.reduce((sum, p) => sum + p.py, 0) / canvasPoints.length;
      ctx.font = '600 11px "DM Sans", "Segoe UI", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.lineWidth = 3;
      ctx.strokeStyle = 'rgba(17, 24, 39, 0.8)';
      ctx.strokeText(name, cx, cy);
      ctx.fillStyle = draft ? '#fef08a' : '#fecaca';
      ctx.fillText(name, cx, cy);
    }
    ctx.restore();
  }

  function drawKeepoutZones(ctx, info) {
    keepoutZones.forEach((zone) => {
      if (zone?.enabled === false) return;
      drawKeepoutPolygon(ctx, info, zone?.points || [], false, zone?.name || '');
    });
    drawKeepoutPolygon(ctx, info, keepoutDraft, true, '');
  }

  function setpointStyle(pt, selected) {
    const t = String(pt?.pointType || 'normal').toLowerCase();
    if (t === 'home') {
      return {
        fill: selected ? '#c084fc' : '#a855f7',
        stroke: '#f3e8ff',
        ring: 'rgba(168, 85, 247, 0.45)',
        badge: 'Home',
      };
    }
    if (t === 'approach') {
      return {
        fill: selected ? '#fb923c' : '#f97316',
        stroke: '#fff7ed',
        ring: 'rgba(249, 115, 22, 0.45)',
        badge: 'Approach',
      };
    }
    return {
      fill: selected ? '#2dd4bf' : '#14b8a6',
      stroke: '#ecfdf5',
      ring: 'rgba(45, 212, 191, 0.45)',
      badge: 'Station',
    };
  }

  function roundRectPath(ctx, x, y, w, h, radius) {
    const r = Math.min(radius, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawSetpoints(ctx, info) {
    const list = window.AmrStations?.getSetpoints?.() || [];
    if (!list.length) return;
    const selectedId = window.AmrStations?.getSelectedId?.() || null;

    list.forEach((pt) => {
      if (pt == null || !Number.isFinite(Number(pt.x)) || !Number.isFinite(Number(pt.y))) return;
      const { px, py } = worldToCanvas(Number(pt.x), Number(pt.y), info);
      const selected = pt.id === selectedId;
      const style = setpointStyle(pt, selected);
      const r = selected ? 9 : 7;
      const yawRad = (Number(pt.yawDeg) || 0) * Math.PI / 180;
      const dirX = Math.cos(-yawRad);
      const dirY = Math.sin(-yawRad);

      // Halo ngoài — dễ thấy trên map
      ctx.beginPath();
      ctx.arc(px, py, r + (selected ? 5 : 3.5), 0, Math.PI * 2);
      ctx.fillStyle = style.ring;
      ctx.fill();

      // Thân marker
      ctx.beginPath();
      ctx.arc(px, py, r, 0, Math.PI * 2);
      ctx.fillStyle = style.fill;
      ctx.fill();
      ctx.lineWidth = selected ? 2.5 : 2;
      ctx.strokeStyle = '#0f172a';
      ctx.stroke();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = style.stroke;
      ctx.stroke();

      // Mũi tên hướng yaw
      const tip = r + 14;
      const tipX = px + dirX * tip;
      const tipY = py + dirY * tip;
      const back = r + 2;
      const side = 5.5;
      const bx = px + dirX * back;
      const by = py + dirY * back;
      const lx = bx - dirY * side;
      const ly = by + dirX * side;
      const rx = bx + dirY * side;
      const ry = by - dirX * side;
      ctx.beginPath();
      ctx.moveTo(tipX, tipY);
      ctx.lineTo(lx, ly);
      ctx.lineTo(rx, ry);
      ctx.closePath();
      ctx.fillStyle = style.fill;
      ctx.fill();
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 1.2;
      ctx.stroke();

      // Trên map chỉ hiển thị tên điểm; loại điểm đã được phân biệt bằng màu marker.
      const title = String(pt.name || '').trim() || 'Station';
      const fontSize = selected ? 12 : 11;
      ctx.font = `600 ${fontSize}px "DM Sans", "Segoe UI", sans-serif`;
      const textW = ctx.measureText(title).width;
      const padX = 8;
      const padY = 5;
      const boxW = textW + padX * 2;
      const boxH = fontSize + padY * 2;
      const boxX = px + r + 10;
      const boxY = py - boxH / 2;

      ctx.save();
      roundRectPath(ctx, boxX, boxY, boxW, boxH, 6);
      ctx.fillStyle = selected ? 'rgba(15, 23, 42, 0.92)' : 'rgba(15, 23, 42, 0.82)';
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = style.fill;
      ctx.stroke();

      ctx.fillStyle = style.fill;
      ctx.fillRect(boxX, boxY + 3, 3, boxH - 6);

      ctx.fillStyle = '#f8fafc';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(title, boxX + padX + 2, boxY + boxH / 2);
      ctx.restore();
    });
  }

  function drawPlanPath(ctx, info) {
    const pts = planPath.map((pt) => worldToCanvas(pt.x, pt.y, info));
    if (pts.length < 2) return;

    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    // Một đường đơn giản, đủ dày để nhìn
    ctx.beginPath();
    pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.px, p.py) : ctx.lineTo(p.px, p.py)));
    ctx.strokeStyle = '#2563eb';
    ctx.lineWidth = 3;
    ctx.stroke();

    // Điểm cuối goal
    const end = pts[pts.length - 1];
    ctx.beginPath();
    ctx.arc(end.px, end.py, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#ea580c';
    ctx.fill();
    ctx.strokeStyle = '#111827';
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  /** Trục X (đỏ) Y (xanh) tại tâm bản đồ — tham chiếu map, KHÔNG phải robot */
  function drawMapAxes(ctx, info) {
    const cx = info.origin.position.x + (info.width * info.resolution) / 2;
    const cy = info.origin.position.y + (info.height * info.resolution) / 2;
    const len = Math.max(info.resolution * 10, 0.5); // ~10 cell hoặc 0.5m
    const c0 = worldToCanvas(cx, cy, info);
    const cX = worldToCanvas(cx + len, cy, info);
    const cY = worldToCanvas(cx, cy + len, info);

    // Mờ hơn khi SLAM để không che icon robot tại gốc (0,0).
    ctx.save();
    ctx.globalAlpha = isSlamScanning() ? 0.35 : 1;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(c0.px, c0.py); ctx.lineTo(cX.px, cX.py);
    ctx.strokeStyle = '#ef4444'; ctx.stroke(); // +X
    ctx.beginPath(); ctx.moveTo(c0.px, c0.py); ctx.lineTo(cY.px, cY.py);
    ctx.strokeStyle = '#22c55e'; ctx.stroke(); // +Y

    ctx.fillStyle = '#94a3b8';
    ctx.beginPath(); ctx.arc(c0.px, c0.py, 3, 0, Math.PI * 2); ctx.fill(); // chấm tâm
    ctx.restore();
  }

  /** Mũi tên từ điểm click → điểm kéo */
  function drawDragArrow(ctx, start, end, color) {
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(start.px, start.py);
    ctx.lineTo(end.px, end.py);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(start.px, start.py, 5, 0, Math.PI * 2);
    ctx.fill();
    // đầu mũi tên nhỏ
    const ang = Math.atan2(end.py - start.py, end.px - start.px);
    const hs = 10;
    ctx.beginPath();
    ctx.moveTo(end.px, end.py);
    ctx.lineTo(end.px - hs * Math.cos(ang - 0.4), end.py - hs * Math.sin(ang - 0.4));
    ctx.lineTo(end.px - hs * Math.cos(ang + 0.4), end.py - hs * Math.sin(ang + 0.4));
    ctx.closePath();
    ctx.fill();
  }
  
  function drawRobot(ctx, pose, info) {
    const { px, py } = worldToCanvas(pose.x, pose.y, info);
    const yawRad = (pose.yawDeg * Math.PI) / 180;
    // Lớn + màu cyan để phân biệt với trục map (đỏ/xanh lá) tại tâm.
    const size = Math.max(16, view.scale * 4.5);

    ctx.save();
    ctx.translate(px, py);

    // Halo để dễ thấy trên nền scan trắng/xám
    ctx.beginPath();
    ctx.arc(0, 0, size * 1.15, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(14, 165, 233, 0.35)';
    ctx.fill();
    ctx.strokeStyle = '#038';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.rotate(-yawRad);
    ctx.fillStyle = '#0ea5e9';
    ctx.strokeStyle = '#f8fafc';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(size, 0);
    ctx.lineTo(-size * 0.65, size * 0.6);
    ctx.lineTo(-size * 0.65, -size * 0.6);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    ctx.restore();
  }
  
  function quaternionToYawDeg(q) {
    const siny = 2 * (q.w * q.z + q.x * q.y);
    const cosy = 1 - 2 * (q.y * q.y + q.z * q.z);
    return (Math.atan2(siny, cosy) * 180) / Math.PI;
  }
