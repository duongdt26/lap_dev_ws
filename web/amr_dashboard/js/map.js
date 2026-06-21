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

    window.addEventListener('amr-ros-connected', () => {
    initMap();
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

  let mapCacheCanvas = null;   // offscreen: vẽ map 1 lần, không vẽ lại mỗi pose
  let dragCurrent = null;      // pixel hiện tại khi đang kéo (preview mũi tên)
  let redrawScheduled = false;
  let ctxRef = null;
  let canvasRef = null;

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
    },
    setNavGoalCallback(cb) { navGoalCallback = cb; },

    clearPlanPath() {
      planPath = [];
      scheduleRedraw();
    },
  };
  
  function initMap() {
    const ros = window.AmrRos.getRos();
    if (!ros) return;
  
    const canvas = document.getElementById('map-canvas');
    const ctx = canvas.getContext('2d');
    const statusEl = document.getElementById('map-status');


    // ── Khởi tạo offscreen canvas ──
    ctxRef = ctx;
    canvasRef = canvas;

    // ── Subscribe /map (bản đồ tĩnh từ map_server hoặc SLAM) ──
    const mapTopic = new ROSLIB.Topic({
      ros,
      name: '/map',
      messageType: 'nav_msgs/msg/OccupancyGrid',
      // map_server dùng transient local — rosbridge tự xử lý khi subscribe
    });
  
    mapTopic.subscribe((msg) => {
      mapMsg = msg;
      statusEl.textContent = `Map: ${msg.info.width}×${msg.info.height} @ ${msg.info.resolution}m/cell`;
      computeView(msg, canvas);
      rebuildMapCache();  // map đổi → vẽ lại cache
      scheduleRedraw();
    });
  
    // ── Subscribe /amcl_pose (vị trí robot trên map) ──
    const poseTopic = new ROSLIB.Topic({
      ros,
      name: '/amcl_pose',
      messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
    });
  
    poseTopic.subscribe((msg) => {
      const p = msg.pose.pose.position;
      const q = msg.pose.pose.orientation;
      robotPose = {
        x: p.x,
        y: p.y,
        yawDeg: quaternionToYawDeg(q),
      };
      if (mapMsg) scheduleRedraw();
    });

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

    // Pose từ TF (SLAM + Nav) — do nav_pose_bridge_node publish
    const robotPoseMapTopic = new ROSLIB.Topic({
      ros,
      name: '/robot_pose_map',
      messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
    });
    robotPoseMapTopic.subscribe((msg) => {
      const p = msg.pose.pose.position;
      const q = msg.pose.pose.orientation;
      robotPose = { x: p.x, y: p.y, yawDeg: quaternionToYawDeg(q) };
      scheduleRedraw();  // không vẽ ngay — tránh queue lag
    });

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
      if (!mapCacheCanvas) {
        mapCacheCanvas = document.createElement('canvas');
      }
      mapCacheCanvas.width = canvasRef.width;
      mapCacheCanvas.height = canvasRef.height;
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
  
  function drawRobot(ctx, pose, info) {
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
  
  function quaternionToYawDeg(q) {
    const siny = 2 * (q.w * q.z + q.x * q.y);
    const cosy = 1 - 2 * (q.y * q.y + q.z * q.z);
    return (Math.atan2(siny, cosy) * 180) / Math.PI;
  }