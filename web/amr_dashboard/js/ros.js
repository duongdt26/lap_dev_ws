/**
 * ros.js — Quản lý kết nối WebSocket tới rosbridge
 *
 * rosbridge chuyển message JSON ↔ ROS2 topic/service/action
 * Mọi file JS khác dùng window.AmrRos để publish/subscribe
 */

window.AmrRos = (function () {
    let ros = null;
  
    // Phần tử UI
    const statusEl  = document.getElementById('conn-status');
    const hostInput = document.getElementById('ros-host');
    const btnConnect = document.getElementById('btn-connect');
  
    function setStatus(connected) {
      if (connected) {
        statusEl.textContent = 'Đã kết nối';
        statusEl.className = 'connected';
      } else {
        statusEl.textContent = 'Chưa kết nối';
        statusEl.className = 'disconnected';
      }
    }
  
    function connect() {
      const host = hostInput.value.trim() || 'localhost';
      const url  = `ws://${host}:9090`;
  
      // Đóng kết nối cũ nếu có
      if (ros) {
        ros.close();
      }
  
      ros = new ROSLIB.Ros({ url });
  
      ros.on('connection', () => {
        console.log('rosbridge connected:', url);
        setStatus(true);
        window.dispatchEvent(new CustomEvent('amr-ros-connected'));
      });
  
      ros.on('error', (err) => {
        console.error('rosbridge error:', err);
        setStatus(false);
      });
  
      ros.on('close', () => {
        console.log('rosbridge closed');
        setStatus(false);
      });
    }
  
    btnConnect.addEventListener('click', connect);
  
    // API dùng chung cho các file khác
    return {
      getRos: () => ros,
      connect,
    };
  })();