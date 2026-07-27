/**
 * map-data.js — MAP_DATA shared storage, đồng bộ theo từng map
 */

(function () {
  const MAPS_DIR = '/home/admin-pc/maps';
  const MAP_DATA_ROOT = '/home/admin-pc/MAP_DATA';

  let ready = false;
  let clients = {};
  let currentMapName = '';

  function getRos() {
    return window.AmrRos?.getRos?.() || null;
  }

  function useApi() {
    return !!window.AmrApi?.isAvailable?.() && !!window.AmrApi?.getUser?.();
  }

  function apiPath(mapName, suffix = '') {
    return `/api/maps/${encodeURIComponent(mapName)}${suffix}`;
  }

  function callService(client, request) {
    return new Promise((resolve, reject) => {
      if (!client) {
        reject(new Error('ROS services chưa sẵn sàng — bấm Connect'));
        return;
      }
      client.callService(
        new ROSLIB.ServiceRequest(request || {}),
        resolve,
        reject
      );
    });
  }

  function initClients() {
    const ros = getRos();
    if (!ros) return false;
    clients = {
      loadSetpoints: new ROSLIB.Service({
        ros,
        name: '/load_setpoints',
        serviceType: 'amr_web_interfaces/srv/LoadSetpoints',
      }),
      saveSetpoints: new ROSLIB.Service({
        ros,
        name: '/save_setpoints',
        serviceType: 'amr_web_interfaces/srv/SaveSetpoints',
      }),
      listProcesses: new ROSLIB.Service({
        ros,
        name: '/list_processes',
        serviceType: 'amr_web_interfaces/srv/ListProcesses',
      }),
      loadProcess: new ROSLIB.Service({
        ros,
        name: '/load_process',
        serviceType: 'amr_web_interfaces/srv/LoadProcess',
      }),
      saveProcess: new ROSLIB.Service({
        ros,
        name: '/save_process',
        serviceType: 'amr_web_interfaces/srv/SaveProcess',
      }),
    };
    ready = true;
    return true;
  }

  function waitUntilReady(maxMs = 6000) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      function tick() {
        if (useApi()) {
          resolve();
          return;
        }
        if (ready && clients.saveProcess) {
          resolve();
          return;
        }
        if (Date.now() - start > maxMs) {
          reject(new Error('ROS services chưa sẵn sàng — bấm Connect'));
          return;
        }
        if (!ready) initClients();
        setTimeout(tick, 150);
      }
      tick();
    });
  }

  async function getActiveMapName() {
    if (!window.AmrMapSync?.getMapStatus) return '';
    try {
      const st = await window.AmrMapSync.getMapStatus();
      return (st.map_name || '').trim();
    } catch {
      return '';
    }
  }

  function getCurrentMapName() {
    return currentMapName || '';
  }

  async function resolveMapName(mapName) {
    const explicit = (mapName || '').trim();
    if (explicit) return explicit;
    if (currentMapName) return currentMapName;
    return getActiveMapName();
  }

  async function requireMapName(mapName) {
    const name = await resolveMapName(mapName);
    if (!name) {
      throw new Error('Chưa có map — nạp map trước');
    }
    return name;
  }

  function mapYamlPath(mapName) {
    return `${MAPS_DIR}/${mapName}.yaml`;
  }

  /** Gọi sau khi nạp map — set active map trên backend + báo UI tải setpoint/process */
  async function syncForMap(mapName) {
    const name = (mapName || '').trim();
    if (!name) return;

    await waitUntilReady();

    if (window.AmrMapSync?.setActiveMapName) {
      await window.AmrMapSync.setActiveMapName(name);
    }

    if (useApi() && window.AmrApi.canWrite()) {
      try {
        await window.AmrApi.request(apiPath(name), {
          method: 'PUT',
          body: JSON.stringify({}),
        });
      } catch (error) {
        console.warn('Không đồng bộ được map vào SQLite:', error);
      }
    }

    currentMapName = name;
    window.dispatchEvent(
      new CustomEvent('amr-map-data-sync', { detail: { name } })
    );
    return name;
  }

  async function loadSetpoints(mapName) {
    await waitUntilReady();
    const name = await requireMapName(mapName);
    if (useApi()) {
      try {
        return await window.AmrApi.request(apiPath(name, '/setpoints'));
      } catch (error) {
        if (error.status === 404) return [];
        throw error;
      }
    }
    const res = await callService(clients.loadSetpoints, {
      map_name: name,
    });
    if (!res.success) throw new Error(res.message || 'load setpoints failed');
    try {
      return JSON.parse(res.json_data || '[]');
    } catch {
      return [];
    }
  }

  async function saveSetpoints(setpoints, mapName) {
    await waitUntilReady();
    const name = await requireMapName(mapName);
    if (useApi()) {
      return window.AmrApi.request(apiPath(name, '/setpoints'), {
        method: 'PUT',
        body: JSON.stringify(setpoints),
      });
    }
    const res = await callService(clients.saveSetpoints, {
      map_name: name,
      json_data: JSON.stringify(setpoints),
    });
    if (!res.success) throw new Error(res.message || 'save setpoints failed');
    return res;
  }

  async function listProcesses(mapName) {
    await waitUntilReady();
    const name = await requireMapName(mapName);
    if (useApi()) {
      try {
        return await window.AmrApi.request(apiPath(name, '/processes'));
      } catch (error) {
        if (error.status === 404) return [];
        throw error;
      }
    }
    const res = await callService(clients.listProcesses, {
      map_name: name,
    });
    if (!res.success) throw new Error(res.message || 'list processes failed');
    return (res.names || '')
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }

  async function loadProcess(processName, mapName) {
    await waitUntilReady();
    const name = await requireMapName(mapName);
    if (useApi()) {
      return window.AmrApi.request(
        apiPath(name, `/processes/${encodeURIComponent(processName)}`)
      );
    }
    const res = await callService(clients.loadProcess, {
      map_name: name,
      name: processName,
    });
    if (!res.success) throw new Error(res.message || 'load process failed');
    try {
      return JSON.parse(res.json_data || '{}');
    } catch {
      return {};
    }
  }

  async function saveProcess(processName, data, mapName) {
    await waitUntilReady();
    const name = await requireMapName(mapName);
    if (useApi()) {
      return window.AmrApi.request(
        apiPath(name, `/processes/${encodeURIComponent(processName)}`),
        {
          method: 'PUT',
          body: JSON.stringify(data),
        }
      );
    }
    const res = await callService(clients.saveProcess, {
      map_name: name,
      name: processName,
      json_data: JSON.stringify(data),
    });
    if (!res.success) throw new Error(res.message || 'save process failed');
    return res;
  }

  function initDataUpdatedSub() {
    const ros = getRos();
    if (!ros) return;
    new ROSLIB.Topic({
      ros,
      name: '/web_data_updated',
      messageType: 'std_msgs/msg/String',
    }).subscribe((msg) => {
      window.dispatchEvent(
        new CustomEvent('amr-data-updated', { detail: msg.data })
      );
    });
  }

  window.addEventListener('amr-ros-connected', () => {
    ready = false;
    currentMapName = '';
    setTimeout(async () => {
      initClients();
      initDataUpdatedSub();
      try {
        await waitUntilReady();
        const st = await getActiveMapName();
        if (st) await syncForMap(st);
      } catch {
        /* chưa có map active */
      }
    }, 400);
  });

  window.addEventListener('amr-ros-disconnected', () => {
    ready = false;
    currentMapName = '';
    clients = {};
  });

  window.AmrMapData = {
    MAPS_DIR,
    MAP_DATA_ROOT,
    mapYamlPath,
    getActiveMapName,
    getCurrentMapName,
    resolveMapName,
    requireMapName,
    waitUntilReady,
    syncForMap,
    isReady: () => ready,
    loadSetpoints,
    saveSetpoints,
    listProcesses,
    loadProcess,
    saveProcess,
  };
})();
