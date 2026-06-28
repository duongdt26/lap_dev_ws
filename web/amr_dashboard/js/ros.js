/**
 * ros.js — Quản lý kết nối WebSocket tới rosbridge
 *
 * LAN   : ws://IP:9090
 * ngrok : wss://domain/rosbridge (1 tunnel — proxy qua amr_web_server.py)
 * Mở trang: tự điền IP/host, "Chưa kết nối" — user bấm Kết nối.
 */

window.AmrRos = (function () {
  let ros = null;
  let remoteCfg = null;

  const statusEl   = document.getElementById('conn-status');
  const hostInput  = document.getElementById('ros-host');
  const btnConnect = document.getElementById('btn-connect');

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

  /** LAN: ws://host:9090 | ngrok 1 tunnel: wss://host/rosbridge */
  function buildRosUrl(hostRaw) {
    const raw = (hostRaw || 'localhost').trim();
    if (!raw) return 'ws://localhost:9090';
    if (raw.startsWith('ws://') || raw.startsWith('wss://')) return raw;

    const host = bareHost(raw);
    if (isRemoteHost(host)) {
      const path = remoteCfg?.rosbridgePath || '/rosbridge';
      return `wss://${host}${path}`;
    }
    return `ws://${host}:9090`;
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
    if (state === 'connected') {
      statusEl.textContent = 'Đã kết nối';
      statusEl.className = 'connected';
    } else if (state === 'connecting') {
      statusEl.textContent = 'Đang kết nối...';
      statusEl.className = 'connecting';
    } else {
      statusEl.textContent = 'Chưa kết nối';
      statusEl.className = 'disconnected';
    }
  }

  function connect() {
    const host = hostInput.value.trim() || 'localhost';
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
    hostInput.value = await resolveHost();
    setStatus('disconnected');
  }

  btnConnect.addEventListener('click', connect);
  init();

  return {
    getRos: () => ros,
    connect,
  };
})();
