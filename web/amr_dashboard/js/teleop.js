/**
 * teleop.js — Điều khiển thủ công qua /cmd_vel_web
 *
 * Luồng:
 *   Web publish /cmd_vel_web
 *     → twist_mux (priority 80)
 *     → diff_cont/cmd_vel_unstamped
 *     → Gazebo di chuyển robot
 *
 * QUAN TRỌNG: twist_mux phải đang chạy!
 */

document.getElementById('btn-connect').addEventListener('click', () => {
    setTimeout(initTeleop, 500);
  });
  
  function initTeleop() {
    const ros = window.AmrRos.getRos();
    if (!ros) return;
  
    // Publisher: gửi lệnh vận tốc
    const cmdVelPub = new ROSLIB.Topic({
      ros,
      name: '/cmd_vel_web',          // khớp twist_mux.yaml
      messageType: 'geometry_msgs/msg/Twist',
    });
  
    const slider = document.getElementById('speed-slider');
    const speedLabel = document.getElementById('speed-label');
    slider.addEventListener('input', () => {
      speedLabel.textContent = parseFloat(slider.value).toFixed(2);
    });
  
    // Góc quay mặc định (rad/s) — có thể thêm slider riêng sau
    const ANGULAR_SPEED = 0.4;
    const PUBLISH_HZ = 10;
    let publishTimer = null; // setInterval đang chạy
    let activeCmd = null;  // Lệnh đang giữ: { linearX, angularZ} hoặc hàm 
  
    // function publishVel(linearX, angularZ) {
    //   cmdVelPub.publish(new ROSLIB.Message({
    //     linear:  { x: linearX, y: 0, z: 0 },
    //     angular: { x: 0, y: 0, z: angularZ },
    //   }));
    // }
  
    // function stop() {
    //   publishVel(0, 0);
    // }
  
    // // Giữ nút = chạy, thả nút = dừng (an toàn hơn toggle)
    // function bindHold(btnId, linearX, angularZ) {
    //   const btn = document.getElementById(btnId);
    //   btn.addEventListener('mousedown', () => publishVel(linearX, angularZ));
    //   btn.addEventListener('mouseup', stop);
    //   btn.addEventListener('mouseleave', stop);
    //   // Hỗ trợ cảm ứng trên điện thoại
    //   btn.addEventListener('touchstart', (e) => { e.preventDefault(); publishVel(linearX, angularZ); });
    //   btn.addEventListener('touchend', stop);
    // }
  
    // // const speed = () => parseFloat(slider.value);
  
    // // bindHold('btn-forward', () => speed(), 0);   // sửa lại — xem note bên dưới
    // // bindHold('btn-back',    () => -speed(), 0);
    // // bindHold('btn-left',    0, ANGULAR_SPEED);
    // // bindHold('btn-right',   0, -ANGULAR_SPEED);

    // const speed = () => parseFloat(slider.value);

    // // Tiến: đọc slider NGAY KHI nhấn chuột
    // const btnFwd = document.getElementById('btn-forward');
    // btnFwd.addEventListener('mousedown', () => publishVel(speed(), 0));
    // btnFwd.addEventListener('mouseup', stop);
    // btnFwd.addEventListener('mouseleave', stop);
    // btnFwd.addEventListener('touchstart', (e) => { e.preventDefault(); publishVel(speed(), 0); });
    // btnFwd.addEventListener('touchend', stop);

    // // Lùi: tương tự, âm tốc độ
    // const btnBack = document.getElementById('btn-back');
    // btnBack.addEventListener('mousedown', () => publishVel(-speed(), 0));
    // btnBack.addEventListener('mouseup', stop);
    // btnBack.addEventListener('mouseleave', stop);
    // btnBack.addEventListener('touchstart', (e) => { e.preventDefault(); publishVel(-speed(), 0); });
    // btnBack.addEventListener('touchend', stop);

    // // Trái/phải: tốc độ cố định → bindHold vẫn OK
    // bindHold('btn-left',  0,  ANGULAR_SPEED);
    // bindHold('btn-right', 0, -ANGULAR_SPEED);
    
    // document.getElementById('btn-stop').addEventListener('click', stop);

    function publishVel(linearX, angularZ) {
      cmdVelPub.publish(new ROSLIB.Message({
        linear:  { x: linearX, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: angularZ },
      }));
    }

    // Dừng hẳn: xóa timer + gửi 0
    function stop() {
      if (publishTimer) {
        clearInterval(publishTimer);
        publishTimer = null;
      }
      activeCmd = null;
      publishVel(0, 0);
    }

  /**
   * Bắt đầu gửi lệnh liên tục khi giữ nút.
   * getLinear / getAngular: số cố định HOẶC hàm () => số (đọc slider mỗi lần gửi).
   */
    function startHold(getLinear, getAngular) {
      stop(); // dừng lệnh cũ nếu có
      activeCmd = { getLinear, getAngular };

      const tick = () => {
        const lx = typeof getLinear === 'function' ? getLinear() : getLinear;
        const az = typeof getAngular === 'function' ? getAngular() : getAngular;
        publishVel(lx, az);
      };

      tick(); // gửi ngay lần đầu
      publishTimer = setInterval(tick, 1000 / PUBLISH_HZ);
    }

    const speed = () => parseFloat(slider.value);

    // Gắn giữ nút / thả nút — dùng chung cho chuột + cảm ứng
    function bindDirectional(btnId, getLinear, getAngular) {
      const btn = document.getElementById(btnId);
      const onStart = (e) => {
        if (e.cancelable) e.preventDefault(); // tránh scroll khi chạm trên điện thoại
        startHold(getLinear, getAngular);
      };
      const onEnd = () => stop();

      btn.addEventListener('mousedown', onStart);
      btn.addEventListener('mouseup', onEnd);
      btn.addEventListener('touchstart', onStart, { passive: false });
      btn.addEventListener('touchend', onEnd);
      btn.addEventListener('touchcancel', onEnd); // ngón trượt ra khỏi nút trên mobile
      // KHÔNG dùng mouseleave — dễ dừng nhầm khi chuột lệch nhẹ
    }

    // Tiến / lùi: đọc slider mỗi lần tick
    bindDirectional('btn-forward', () => speed(), 0);
    bindDirectional('btn-back',    () => -speed(), 0);

    // Trái / phải: cùng độ lớn, khác dấu
    bindDirectional('btn-left',  0,  ANGULAR_SPEED);
    bindDirectional('btn-right', 0, -ANGULAR_SPEED);

    document.getElementById('btn-stop').addEventListener('click', stop);

    // Thả chuột ở ngoài nút vẫn dừng (an toàn)
    window.addEventListener('mouseup', () => {
      if (publishTimer) stop();
    });

  }