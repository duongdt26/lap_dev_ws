/**
 * stm32.js — STM32 health, conveyor status, belt commands qua rosbridge
 *
 * Workflow setpoint (sau Nav2 goal success):
 *   LOAD   → $CMD,START,id → chờ ACK load xong → Free → Delivering
 *   UNLOAD → $CMD,STOP,id,LEFT → chờ ACK unload → Delivering → Free
 *   NONE   → bỏ qua (process.js xử lý)
 */

(function () {
  const stm32StatusEl = document.getElementById('stm32-status');
  const BELT_TIMEOUT_SEC = 60.0;
  const UNLOAD_SIDE = 'LEFT';

  let helloClient = null;
  let beltClient = null;
  let healthTopic = null;
  let belt1Topic = null;
  let belt2Topic = null;
  let stm32Alive = false;
  let workflowBeltLock = false;

  function setStm32Ui(alive, message, state) {
    if (!stm32StatusEl) return;
    if (alive) {
      const detail = state ? ` (${state})` : '';
      stm32StatusEl.textContent = `STM32: connected${detail}`;
      stm32StatusEl.className = 'conn-pill connected';
    } else if (String(message || '').includes('serial open')) {
      stm32StatusEl.textContent = 'STM32: serial open — waiting heartbeat';
      stm32StatusEl.className = 'conn-pill connecting';
    } else {
      stm32StatusEl.textContent = 'STM32: disconnected';
      stm32StatusEl.className = 'conn-pill disconnected';
    }
  }

  function mapConveyorState(msg) {
    if (workflowBeltLock) return;
    const state = msg.state || 'Free';
    if (!window.AmrStations?.setConveyorStatus) return;
    const beltNum = msg.belt_id === 2 ? 2 : 1;
    if (state === 'Running') {
      window.AmrStations.setConveyorStatus(beltNum, 'Delivering');
    } else if (state === 'Occupied') {
      window.AmrStations.setConveyorStatus(beltNum, 'Delivering');
    } else if (state === 'Estop') {
      return;
    } else {
      window.AmrStations.setConveyorStatus(beltNum, 'Free');
    }
  }

  function sendHello(clientName) {
    return new Promise((resolve, reject) => {
      if (!helloClient) {
        reject(new Error('disconnected — rosbridge not available'));
        return;
      }
      helloClient.callService(
        new ROSLIB.ServiceRequest({ client_name: clientName || 'ChuongDuong' }),
        (res) => resolve(res),
        (err) => reject(err)
      );
    });
  }

  /** Gọi /run_belt_command — backend chờ đủ UART ACK rồi mới trả success */
  function runBeltCommand(beltId, command, timeoutSec, side) {
    return new Promise((resolve, reject) => {
      if (!beltClient) {
        reject(new Error('disconnected — STM32 bridge not available'));
        return;
      }
      beltClient.callService(
        new ROSLIB.ServiceRequest({
          belt_id: beltId,
          command: command,
          side: side || '',
          timeout_sec: timeoutSec || BELT_TIMEOUT_SEC,
        }),
        (res) => {
          if (res.success) resolve(res);
          else reject(new Error(res.message || 'Belt command thất bại'));
        },
        (err) => reject(err)
      );
    });
  }

  function isBeltCmdActive(cmd) {
    return cmd && cmd !== 'none';
  }

  function applyBeltUiAfterSuccess(beltId, command) {
    if (!window.AmrStations?.setConveyorStatus) return;
    if (command === 'load') {
      window.AmrStations.setConveyorStatus(beltId, 'Delivering');
      window.dispatchEvent(new CustomEvent('amr-belt-cargo-loaded', {
        detail: { beltId },
      }));
    } else if (command === 'unload') {
      window.AmrStations.setConveyorStatus(beltId, 'Free');
      window.dispatchEvent(new CustomEvent('amr-belt-cargo-unloaded', {
        detail: { beltId, side: UNLOAD_SIDE },
      }));
    }
  }

  async function runBeltForSetpoint(beltId, command) {
    const cmd = String(command || '').toLowerCase();
    if (!isBeltCmdActive(cmd)) return null;

    const side = cmd === 'unload' ? UNLOAD_SIDE : '';
    const label = cmd === 'load' ? 'nhận hàng' : `trả hàng (${UNLOAD_SIDE})`;
    console.info(`[STM32] Belt ${beltId}: bắt đầu ${label}`);

    const res = await runBeltCommand(beltId, cmd, BELT_TIMEOUT_SEC, side);
    applyBeltUiAfterSuccess(beltId, cmd);
    console.info(`[STM32] Belt ${beltId}: ${label} xong — ${res.message || 'OK'}`);
    return res;
  }

  /**
   * Chạy lệnh băng tải theo setpoint.
   * Chờ đủ ACK từ STM32 (qua ROS service) trước khi resolve.
   * Belt 1 và 2 chạy song song nếu cả hai có lệnh.
   */
  async function runSetpointBelts(setpoint) {
    const jobs = [];
    if (isBeltCmdActive(setpoint.belt1Cmd)) {
      jobs.push(runBeltForSetpoint(1, setpoint.belt1Cmd));
    }
    if (isBeltCmdActive(setpoint.belt2Cmd)) {
      jobs.push(runBeltForSetpoint(2, setpoint.belt2Cmd));
    }
    if (!jobs.length) return [];

    workflowBeltLock = true;
    try {
      return await Promise.all(jobs);
    } finally {
      workflowBeltLock = false;
    }
  }

  function setpointNeedsBelt(setpoint) {
    return [setpoint?.belt1Cmd, setpoint?.belt2Cmd].some(isBeltCmdActive);
  }

  window.addEventListener('amr-ros-connected', () => {
    const ros = window.AmrRos.getRos();
    if (!ros) return;

    helloClient = new ROSLIB.Service({
      ros,
      name: '/stm32/hello',
      serviceType: 'amr_stm32_interfaces/srv/Stm32Hello',
    });

    beltClient = new ROSLIB.Service({
      ros,
      name: '/run_belt_command',
      serviceType: 'amr_stm32_interfaces/srv/RunBeltCommand',
    });

    healthTopic = new ROSLIB.Topic({
      ros,
      name: '/stm32/health',
      messageType: 'amr_stm32_interfaces/msg/Stm32Health',
    });
    healthTopic.subscribe((msg) => {
      stm32Alive = !!msg.alive;
      setStm32Ui(msg.alive, msg.message, msg.stm32_state);
    });

    belt1Topic = new ROSLIB.Topic({
      ros,
      name: '/conveyor/belt1/status',
      messageType: 'amr_stm32_interfaces/msg/ConveyorStatus',
    });
    belt1Topic.subscribe(mapConveyorState);

    belt2Topic = new ROSLIB.Topic({
      ros,
      name: '/conveyor/belt2/status',
      messageType: 'amr_stm32_interfaces/msg/ConveyorStatus',
    });
    belt2Topic.subscribe(mapConveyorState);

    sendHello('ChuongDuong')
      .then((res) => {
        if (res.success) {
          setStm32Ui(true, res.message, res.stm32_state);
        }
      })
      .catch(() => setStm32Ui(false, '', ''));
  });

  window.addEventListener('amr-ros-disconnected', () => {
    if (healthTopic) healthTopic.unsubscribe();
    if (belt1Topic) belt1Topic.unsubscribe();
    if (belt2Topic) belt2Topic.unsubscribe();
    helloClient = null;
    beltClient = null;
    stm32Alive = false;
    workflowBeltLock = false;
    setStm32Ui(false, '', '');
  });

  function isBeltAvailable() {
    return stm32Alive;
  }

  window.AmrStm32 = {
    sendHello,
    runBeltCommand,
    runSetpointBelts,
    runBeltForSetpoint,
    setpointNeedsBelt,
    isBeltAvailable,
    UNLOAD_SIDE,
  };
})();
