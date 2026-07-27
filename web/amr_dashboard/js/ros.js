/**
 * ros.js — Quản lý kết nối WebSocket tới rosbridge
 *
 * LAN   : ws://IP:9091
 * ngrok : wss://domain/rosbridge (1 tunnel — proxy qua amr_web_server.py)
 * Mở trang: tự resolve host và tự kết nối.
 */

window.AmrRos = (function () {
  let ros = null;
  let remoteCfg = null;

  const statusEl   = document.getElementById('conn-status');
  const hostInput  = document.getElementById('ros-host');

  function isRemoteHost(hostname) {
    if (!hostname) return false;
    return hostname.includes('ngrok') ||
           hostname.includes('loca.lt') ||
           hostname.includes('trycloudflare.com');
  }

  function bareHost(hostRaw) {
    return (hostRaw || '')
      .trim()
      .replace(/^https?:\/\//, '')
      .split('/')[0]
      .split(':')[0];
  }

  /** LAN: ws://host:9091 | ngrok 1 tunnel: wss://host/rosbridge */
  function buildRosUrl(hostRaw) {
    const raw = (hostRaw || 'localhost').trim();
    if (!raw) return 'ws://localhost:9091';
    if (raw.startsWith('ws://') || raw.startsWith('wss://')) return raw;

    const host = bareHost(raw);
    if (isRemoteHost(host)) {
      const path = remoteCfg?.rosbridgePath || '/rosbridge';
      return `wss://${host}${path}`;
    }
    return `ws://${host}:9091`;
  }

  async function fetchRemoteConfig() {
    try {
      const res = await fetch(`config.json?_=${Date.now()}`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async function resolveHost() {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get('ros_host') || params.get('ros');
    if (fromQuery) return bareHost(fromQuery);

    const pageHost = window.location.hostname;

    if (isRemoteHost(pageHost)) {
      if (remoteCfg?.rosbridgeHost) {
        return bareHost(remoteCfg.rosbridgeHost);
      }
      return pageHost;
    }

    const saved = localStorage.getItem('ros-host');
    if (saved && !isRemoteHost(saved)) return bareHost(saved);

    if (pageHost && pageHost !== 'localhost' && pageHost !== '127.0.0.1') {
      return pageHost;
    }
    return 'localhost';
  }

  function setStatus(state) {
    if (!statusEl) return;
    if (state === 'connected') {
      statusEl.textContent = 'System: connected';
      statusEl.className = 'conn-pill connected';
    } else if (state === 'connecting') {
      statusEl.textContent = 'System: connecting…';
      statusEl.className = 'conn-pill connecting';
    } else {
      statusEl.textContent = 'System: disconnected';
      statusEl.className = 'conn-pill disconnected';
    }
  }

  function connect(hostOverride) {
    const host = (hostOverride || hostInput?.value || 'localhost').trim() || 'localhost';
    if (hostInput) hostInput.value = host;
    const url  = buildRosUrl(host);

    setStatus('connecting');

    if (ros) {
      ros.close();
    }

    ros = new ROSLIB.Ros({ url });

    ros.on('connection', () => {
      console.log('rosbridge connected:', url);
      localStorage.setItem('ros-host', host);
      setStatus('connected');
      window.dispatchEvent(new CustomEvent('amr-ros-connected'));
    });

    ros.on('error', (err) => {
      console.error('rosbridge error:', err);
      setStatus('disconnected');
      window.dispatchEvent(new CustomEvent('amr-ros-disconnected'));
    });

    ros.on('close', () => {
      console.log('rosbridge closed');
      setStatus('disconnected');
      window.dispatchEvent(new CustomEvent('amr-ros-disconnected'));
    });
  }

  async function init() {
    remoteCfg = await fetchRemoteConfig();
    const host = await resolveHost();
    if (hostInput) hostInput.value = host;
    connect(host);
  }

  // Mỗi lần auth sẵn sàng (lần đầu hoặc đăng nhập lại sau logout) đều reconnect.
  // Không dùng { once: true } — nếu không, logout→login sẽ không bao giờ gọi init() lại.
  window.addEventListener('amr-auth-ready', init);

  return {
    getRos: () => ros,
    connect,
    disconnect: () => {
      if (ros) {
        ros.close();
        ros = null;
      }
      setStatus('disconnected');
      window.dispatchEvent(new CustomEvent('amr-ros-disconnected'));
    },
  };
})();
