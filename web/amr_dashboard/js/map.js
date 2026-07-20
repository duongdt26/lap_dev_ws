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

    window.addEventListener('amr-ros-connected', () => {
    initMap();
    });

    window.addEventListener('amr-ros-disconnected', () => {
      mapInitialized = false;
      lastMapFingerprint = '';
      currentVx = 0;
      odomReceived = false;
      lastOdomTime = 0;
      teleopMoving = false;
      mapLiveMode = true;
      mapStatusBase = '';
      setZoomControlsEnabled(false);
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
  let destinationState = 'idle';
  let destinationId = null;

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

  let currentVx = 0;
  let odomReceived = false;
  let lastOdomTime = 0;
  let teleopMoving = false;
  let mapLiveMode = true;
  let mapStatusBase = '';

  const MAP_TOPIC_QOS = {
    durability: 'volatile',
    reliability: 'reliable',
    history: 'keep_last',
    depth: 1,
  };

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
    return [
      msg.info.width,
      msg.info.height,
      msg.info.resolution,
      msg.data ? msg.data.length : 0,
    ].join(',');
  }

  function computeMapLiveMode() {
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

  function updateMapStatusHintLegacy() {
    const el = document.getElementById('map-status');
    if (!el) return;
    const base = mapMsg
      ? (mapStatusBase ||
        `Map: ${mapMsg.info.width}×${mapMsg.info.height} @ ${mapMsg.info.resolution}m/cell`)
      : 'Chưa có bản đồ - chạy localization hoặc SLAM';
    const modeHint = mapLiveMode
      ? ' · LIVE (Nav/teleop/Vx — zoom tắt)'
      : ' · Đóng băng — có thể zoom / đặt pose';
    el.textContent = base + (mapMsg ? modeHint : '');
  }

  function updateMapStatusHint() {
    const element = document.getElementById('map-status');
    if (!element) return;
    if (!mapMsg) {
      element.textContent = 'Chưa có bản đồ — kỹ thuật viên cần nạp map hoặc chạy SLAM.';
      return;
    }
    const setupMode = document.body.dataset.role === 'setup';
    const base = setupMode
      ? (mapStatusBase || 'Bản đồ đã sẵn sàng')
      : 'Bản đồ đã sẵn sàng';
    const mode = mapLiveMode
      ? (setupMode ? ' · Đang cập nhật trực tiếp' : ' · Đang theo dõi robot')
      : (setupMode ? ' · Có thể zoom / đặt pose' : '');
    element.textContent = base + mode;
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
    setNavGoalCallback(cb) { navGoalCallback = cb; },

    clearPlanPath() {
      planPath = [];
      scheduleRedraw();
    },
    resetView() { resetMapView(); },
    resetViewAfterNavGoal() { resetMapViewAfterNavGoal(); },
    invalidate() { scheduleRedraw(); },
    clientPointToWorld(clientX, clientY) {
      const canvas = canvasRef || document.getElementById('map-canvas');
      if (!canvas || !mapMsg || !view) return null;
      const rect = canvas.getBoundingClientRect();
      const px = (clientX - rect.left) * (canvas.width / rect.width);
      const py = (clientY - rect.top) * (canvas.height / rect.height);
      const point = canvasToWorld(px, py, mapMsg.info);
      return { x: point.wx, y: point.wy };
    },
    hasMap() { return !!mapMsg; },
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

  if (!odomPollStarted) {
    odomPollStarted = true;
    setInterval(() => {
      if (odomReceived) updateMapInteractionMode();
    }, 400);
  }

  function initMap() {
    if (mapInitialized) return;
    mapInitialized = true;

    const ros = window.AmrRos.getRos();
    if (!ros) {
      mapInitialized = false;
      return;
    }
  
    const canvas = document.getElementById('map-canvas');
    const ctx = canvas.getContext('2d');


    // ── Khởi tạo offscreen canvas ──
    ctxRef = ctx;
    canvasRef = canvas;

    // ── Subscribe /web/map (map_bridge đồng bộ từ /map cho nhiều client) ──
    initMapSyncClients(ros);

    const mapTopic = new ROSLIB.Topic({
      ros,
      name: '/web/map',
      messageType: 'nav_msgs/msg/OccupancyGrid',
      qos: MAP_TOPIC_QOS,
    });
  
    mapTopic.subscribe((msg) => {
      const fp = mapFingerprint(msg);
      const mapChanged = fp && fp !== lastMapFingerprint;
      if (!mapLiveMode && mapMsg && !mapChanged) return;
      if (mapChanged) lastMapFingerprint = fp;
      applyMapMessage(msg);
    });

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
  
  /** Fit toàn bộ map vào canvas, giữ tỉ lệ */
  function mapSizeKey(info) {
    return `${info.width},${info.height},${info.resolution}`;
  }

  function computeView(msg, canvas) {
    const w = msg.info.width;
    const h = msg.info.height;
    const scale = Math.min(canvas.width / w, canvas.height / h);
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
    if (!initialPosePub) return;
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
    document.getElementById('map-status').textContent =
        `Initial pose: (${x.toFixed(2)}, ${y.toFixed(2)}) yaw=${(yawRad * 180 / Math.PI).toFixed(1)}°`;
    }

    /** Vẽ map tĩnh 1 lần vào offscreen canvas */
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
      const w = info.width, h = info.height, data = mapMsg.data;
  
      c.fillStyle = '#222';
      c.fillRect(0, 0, mapCacheCanvas.width, mapCacheCanvas.height);
      for (let row = 0; row < h; row++) {
        for (let col = 0; col < w; col++) {
          const val = data[row * w + col];
          if (val === -1) c.fillStyle = '#555';
          else if (val === 0) c.fillStyle = '#eee';
          else if (val >= 50) c.fillStyle = '#111';
          else c.fillStyle = '#999';
          const mx = col, my = h - 1 - row;
          c.fillRect(
            view.offsetX + mx * view.scale,
            view.offsetY + my * view.scale,
            Math.ceil(view.scale), Math.ceil(view.scale)
          );
        }
      }
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

  function redrawLegacy(ctx, canvas) {
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
    drawMapAxes(ctx, info);

    // Layer 3: global path
    if (planPath.length > 1) {
      ctx.strokeStyle = '#60a5fa';
      ctx.lineWidth = 2;
      ctx.beginPath();
      planPath.forEach((pt, i) => {
        const { px, py } = worldToCanvas(pt.x, pt.y, info);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
      ctx.stroke();
    }

    // Layer 4: preview mũi tên khi đang kéo (giống RViz)
    if (poseDragStart && dragCurrent) {
      drawDragArrow(ctx, poseDragStart, dragCurrent, poseMode ? '#facc15' : '#f97316');
    }

    // Layer 5: robot
    if (robotPose) {
      drawRobot(ctx, robotPose, info);
    }
  }

  /** Trục X (đỏ) Y (xanh) tại tâm bản đồ */
  function redraw(ctx, canvas) {
    if (!mapMsg || !view) return;
    const info = mapMsg.info;

    if (mapCacheCanvas) {
      ctx.drawImage(mapCacheCanvas, 0, 0);
    } else {
      ctx.fillStyle = '#222';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    if (layerEnabled('map-layer-keepout')) drawKeepoutZones(ctx, info);
    if (document.body.dataset.role === 'setup') drawMapAxes(ctx, info);

    if (layerEnabled('map-layer-route') && planPath.length > 1) {
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.strokeStyle = 'rgba(255,255,255,0.8)';
      ctx.lineWidth = 8;
      traceWorldPath(ctx, planPath, info);
      ctx.stroke();
      ctx.strokeStyle = '#2563eb';
      ctx.lineWidth = 4;
      traceWorldPath(ctx, planPath, info);
      ctx.stroke();
    }

    if (layerEnabled('map-layer-stations')) drawStations(ctx, info);

    if (poseDragStart && dragCurrent) {
      drawDragArrow(
        ctx,
        poseDragStart,
        dragCurrent,
        poseMode ? '#facc15' : '#f97316'
      );
    }

    if (robotPose) drawRobot(ctx, robotPose, info);
  }

  function layerEnabled(id) {
    const input = document.getElementById(id);
    return !input || input.checked;
  }

  function traceWorldPath(ctx, points, info) {
    ctx.beginPath();
    points.forEach((point, index) => {
      const pixel = worldToCanvas(point.x, point.y, info);
      if (index === 0) ctx.moveTo(pixel.px, pixel.py);
      else ctx.lineTo(pixel.px, pixel.py);
    });
  }

  function drawPolygon(ctx, points, info, options) {
    if (!points || !points.length) return;
    const pixels = points.map((point) => worldToCanvas(point.x, point.y, info));
    ctx.save();
    ctx.beginPath();
    pixels.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.px, point.py);
      else ctx.lineTo(point.px, point.py);
    });
    if (options.close && pixels.length > 2) ctx.closePath();
    if (options.fill) {
      ctx.fillStyle = options.fill;
      ctx.fill();
    }
    ctx.strokeStyle = options.stroke;
    ctx.lineWidth = options.lineWidth || 2;
    ctx.setLineDash(options.dash || []);
    ctx.stroke();
    ctx.setLineDash([]);
    pixels.forEach((point) => {
      ctx.fillStyle = options.pointColor || options.stroke;
      ctx.beginPath();
      ctx.arc(point.px, point.py, 4, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.restore();
  }

  function drawKeepoutZones(ctx, info) {
    const zones = window.AmrKeepout?.getZones?.() || [];
    zones.forEach((zone) => {
      drawPolygon(ctx, zone.points, info, {
        close: true,
        fill: zone.enabled === false
          ? 'rgba(148,163,184,0.16)'
          : 'rgba(239,68,68,0.28)',
        stroke: zone.enabled === false ? '#94a3b8' : '#ef4444',
        lineWidth: 3,
        dash: zone.enabled === false ? [7, 5] : [],
      });
      if (zone.points.length) {
        const anchor = worldToCanvas(zone.points[0].x, zone.points[0].y, info);
        drawMapLabel(ctx, anchor.px, anchor.py - 13, zone.name, '#991b1b');
      }
    });

    const draft = window.AmrKeepout?.getDraft?.() || [];
    if (draft.length) {
      drawPolygon(ctx, draft, info, {
        close: false,
        fill: null,
        stroke: '#f59e0b',
        lineWidth: 3,
        dash: [8, 5],
        pointColor: '#fbbf24',
      });
    }
  }

  function drawMapLabel(ctx, x, y, text, background) {
    if (!text) return;
    ctx.save();
    ctx.font = '600 12px system-ui, sans-serif';
    const width = ctx.measureText(text).width + 14;
    const left = x - width / 2;
    ctx.fillStyle = background;
    ctx.beginPath();
    if (typeof ctx.roundRect === 'function') {
      ctx.roundRect(left, y - 18, width, 22, 6);
    } else {
      ctx.rect(left, y - 18, width, 22);
    }
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, x, y - 7);
    ctx.restore();
  }

  function drawStations(ctx, info) {
    const stations = window.AmrStations?.getSetpoints?.() || [];
    const selectedId = window.AmrStations?.getSelectedId?.() || destinationId;
    stations.forEach((station) => {
      const pixel = worldToCanvas(Number(station.x), Number(station.y), info);
      const selected = station.id === selectedId;
      const arrived = selected && destinationState === 'arrived';
      const failed = selected && destinationState === 'failed';
      const color = arrived
        ? '#16a34a'
        : failed
          ? '#dc2626'
          : selected
            ? '#f59e0b'
            : '#2563eb';
      ctx.save();
      if (selected) {
        ctx.fillStyle = color + '33';
        ctx.beginPath();
        ctx.arc(pixel.px, pixel.py, 18, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = color;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(pixel.px, pixel.py, selected ? 9 : 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      if (arrived) {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(pixel.px - 4, pixel.py);
        ctx.lineTo(pixel.px - 1, pixel.py + 3);
        ctx.lineTo(pixel.px + 5, pixel.py - 4);
        ctx.stroke();
      }
      ctx.restore();
      drawMapLabel(ctx, pixel.px, pixel.py - 16, station.name, color);
    });
  }

  function drawMapAxes(ctx, info) {
    const cx = info.origin.position.x + (info.width * info.resolution) / 2;
    const cy = info.origin.position.y + (info.height * info.resolution) / 2;
    const len = Math.max(info.resolution * 10, 0.5); // ~10 cell hoặc 0.5m
    const c0 = worldToCanvas(cx, cy, info);
    const cX = worldToCanvas(cx + len, cy, info);
    const cY = worldToCanvas(cx, cy + len, info);

    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(c0.px, c0.py); ctx.lineTo(cX.px, cX.py);
    ctx.strokeStyle = '#ef4444'; ctx.stroke(); // +X
    ctx.beginPath(); ctx.moveTo(c0.px, c0.py); ctx.lineTo(cY.px, cY.py);
    ctx.strokeStyle = '#22c55e'; ctx.stroke(); // +Y

    ctx.fillStyle = '#94a3b8';
    ctx.beginPath(); ctx.arc(c0.px, c0.py, 3, 0, Math.PI * 2); ctx.fill(); // chấm tâm
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
  
  function drawRobotLegacy(ctx, pose, info) {
    const { px, py } = worldToCanvas(pose.x, pose.y, info);
    const yawRad = (pose.yawDeg * Math.PI) / 180;
    const size = Math.max(8, view.scale * 3);
  
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(-yawRad); // canvas Y ngược ROS → dấu âm
  
    ctx.fillStyle = '#22c55e';
    ctx.beginPath();
    ctx.moveTo(size, 0);
    ctx.lineTo(-size * 0.6, size * 0.5);
    ctx.lineTo(-size * 0.6, -size * 0.5);
    ctx.closePath();
    ctx.fill();
  
    ctx.restore();
  }
  
  function drawRobot(ctx, pose, info) {
    const pixel = worldToCanvas(pose.x, pose.y, info);
    const yawRad = (pose.yawDeg * Math.PI) / 180;
    const size = Math.max(11, Math.min(17, view.scale * 3));

    ctx.save();
    ctx.translate(pixel.px, pixel.py);
    ctx.fillStyle = 'rgba(34,197,94,0.2)';
    ctx.beginPath();
    ctx.arc(0, 0, size + 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#16a34a';
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(0, 0, size, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.rotate(-yawRad);
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(size - 3, 0);
    ctx.lineTo(-3, 6);
    ctx.lineTo(-3, -6);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    drawMapLabel(ctx, pixel.px, pixel.py - size - 12, 'AMR-01', '#166534');
  }

  function quaternionToYawDeg(q) {
    const siny = 2 * (q.w * q.z + q.x * q.y);
    const cosy = 1 - 2 * (q.y * q.y + q.z * q.z);
    return (Math.atan2(siny, cosy) * 180) / Math.PI;
  }

  window.addEventListener('amr-station-selected', (event) => {
    destinationId = event.detail?.id || null;
    destinationState = destinationId ? 'selected' : 'idle';
    scheduleRedraw();
  });

  window.addEventListener('amr-destination-state', (event) => {
    destinationState = event.detail?.state || 'idle';
    destinationId = event.detail?.station?.id || destinationId;
    scheduleRedraw();
  });

  window.addEventListener('amr-nav-status', (event) => {
    const state = event.detail?.state;
    if (state === 'navigating') destinationState = 'navigating';
    if (state === 'failed') destinationState = 'failed';
    if (state === 'cancelled' || state === 'cancelling') {
      destinationState = 'selected';
    }
    scheduleRedraw();
  });

  window.addEventListener('amr-nav-arrived', () => {
    destinationState = 'arrived';
    scheduleRedraw();
  });

  window.addEventListener('amr-setpoints-changed', scheduleRedraw);
  window.addEventListener('amr-keepout-changed', scheduleRedraw);
  window.addEventListener('amr-role-changed', () => {
    updateMapStatusHint();
    scheduleRedraw();
  });

  document
    .querySelectorAll('#map-layer-route, #map-layer-stations, #map-layer-keepout')
    .forEach((input) => input.addEventListener('change', scheduleRedraw));
