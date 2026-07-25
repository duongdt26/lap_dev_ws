/**
 * line-follow.js — handoff tu Nav2 sang node bam line tu tai Approach Station.
 * Giao tiep JSON co request_id de Auto Route cho dung ket qua cua tung lan chay.
 */

(function () {
  const REQUEST_TIMEOUT_MS = 5 * 60 * 1000;
  let commandTopic = null;
  let statusTopic = null;
  const pending = new Map();

  function publish(command) {
    if (!commandTopic) throw new Error('Line follower chưa kết nối rosbridge');
    commandTopic.publish(new ROSLIB.Message({ data: JSON.stringify(command) }));
  }

  function normalizeApproachCommands(setpoint) {
    const workflow = String(setpoint?.pointType || '').toLowerCase() === 'home'
      ? 'home'
      : 'approach';
    if (workflow === 'home') {
      return { belt1: 'none', belt2: 'none', workflow };
    }
    const belt1 = String(setpoint?.belt1Cmd || 'none').toLowerCase();
    const belt2 = String(setpoint?.belt2Cmd || 'none').toLowerCase();
    const valid = (command) => ['none', 'load', 'unload'].includes(command);
    if (!valid(belt1) || !valid(belt2)) {
      throw new Error('Lệnh băng tải Approach Station không hợp lệ');
    }
    if (belt1 === 'none' && belt2 === 'none') {
      throw new Error('Approach Station phải chọn ít nhất một băng tải');
    }
    return { belt1, belt2, workflow };
  }

  function start(setpoint) {
    let belts;
    try {
      belts = normalizeApproachCommands(setpoint);
    } catch (err) {
      return Promise.reject(err);
    }
    if (!commandTopic) {
      return Promise.reject(new Error('Line follower chưa kết nối rosbridge'));
    }

    const targetX = Number(setpoint?.x);
    const targetY = Number(setpoint?.y);
    const targetYawDeg = Number(setpoint?.yawDeg);
    if (![targetX, targetY, targetYawDeg].every(Number.isFinite)) {
      return Promise.reject(new Error('Approach Station thiếu x, y hoặc yaw'));
    }

    const requestId = `line_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(requestId);
        try {
          publish({ command: 'cancel', request_id: requestId });
        } catch (_) {
          // Rosbridge da mat ket noi.
        }
        reject(new Error('Timeout chờ line follower hoàn thành'));
      }, REQUEST_TIMEOUT_MS);

      pending.set(requestId, { resolve, reject, timer });
      publish({
        command: 'start',
        request_id: requestId,
        workflow: belts.workflow,
        belt1_command: belts.belt1,
        belt2_command: belts.belt2,
        target_x: targetX,
        target_y: targetY,
        target_yaw: (targetYawDeg * Math.PI) / 180,
      });
    });
  }

  function cancel() {
    pending.forEach((job, requestId) => {
      try {
        publish({ command: 'cancel', request_id: requestId });
      } catch (_) {
        // Rosbridge da mat ket noi.
      }
      clearTimeout(job.timer);
      job.reject(new Error('Line follower cancelled'));
    });
    pending.clear();
  }

  function onStatusMessage(msg) {
    let status;
    try {
      status = JSON.parse(msg.data);
    } catch (err) {
      console.warn('[LINE] Status JSON không hợp lệ', err, msg.data);
      return;
    }
    window.dispatchEvent(new CustomEvent('amr-line-status', { detail: status }));
    if (!status.final || !status.request_id) return;

    const job = pending.get(status.request_id);
    if (!job) return;
    pending.delete(status.request_id);
    clearTimeout(job.timer);
    if (status.success) {
      const expectedMarker = status.workflow === 'home' ? 1 : 3;
      if (Number(status.marker) !== expectedMarker) {
        job.reject(new Error(
          `Từ chối success sớm tại marker ${status.marker}; cần marker ${expectedMarker}`
        ));
        return;
      }
      job.resolve(status);
    } else {
      job.reject(new Error(status.message || 'Line follower thất bại'));
    }
  }

  window.addEventListener('amr-ros-connected', () => {
    const ros = window.AmrRos.getRos();
    if (!ros) return;
    commandTopic = new ROSLIB.Topic({
      ros,
      name: '/magnetic_line/command',
      messageType: 'std_msgs/msg/String',
    });
    statusTopic = new ROSLIB.Topic({
      ros,
      name: '/magnetic_line/status',
      messageType: 'std_msgs/msg/String',
    });
    statusTopic.subscribe(onStatusMessage);
  });

  window.addEventListener('amr-ros-disconnected', () => {
    if (statusTopic) statusTopic.unsubscribe();
    commandTopic = null;
    statusTopic = null;
    pending.forEach((job) => {
      clearTimeout(job.timer);
      job.reject(new Error('Mất kết nối rosbridge khi đang chạy line follower'));
    });
    pending.clear();
  });

  window.AmrMagneticLine = { start, cancel, normalizeApproachCommands };
})();
