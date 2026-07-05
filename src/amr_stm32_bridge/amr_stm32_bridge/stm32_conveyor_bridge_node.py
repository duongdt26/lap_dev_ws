#!/usr/bin/env python3
"""
stm32_conveyor_bridge_node.py — Cầu nối UART STM32 ↔ ROS2 (protocol Version3).

Load:
  ROS2 → $CMD,START,<id>
  STM32 → $ACK,CMD,START,<id>        (phát hiện hàng)
  STM32 → $ACK,CMD,STOP,<id>         (load xong)
  ROS2 → $BUZZER,START,<id>

Unload:
  ROS2 → $CMD,STOP,<id>,LEFT|RIGHT
  STM32 → $ACK,CMD,STOP,<id>,LEFT|RIGHT
  ROS2 → $BUZZER,STOP,<id>
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_srvs.srv import Trigger

from amr_stm32_interfaces.action import BeltLoadUnload
from amr_stm32_interfaces.msg import ConveyorStatus, Stm32Health
from amr_stm32_interfaces.srv import ResetEstop, RunBeltCommand, Stm32Hello

from amr_stm32_bridge.uart_protocol import (
    STATE_ESTOP,
    STATE_IDLE,
    STATE_RUNNING,
    TelemetryFrame,
    ack_matches_load_done,
    ack_matches_load_started,
    ack_matches_unload_done,
    cmd_buzzer_start,
    cmd_buzzer_stop,
    cmd_hello,
    cmd_ping,
    cmd_reset_estop,
    cmd_start_load,
    cmd_unload_belt,
    normalize_side,
    parse_ack,
    parse_hello_ack,
    parse_line,
    parse_nack,
    parse_pong_seq,
    parse_telemetry,
)

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None


class Stm32ConveyorBridgeNode(Node):
    def __init__(self):
        super().__init__('stm32_conveyor_bridge_node')
        self._cb_group = ReentrantCallbackGroup()

        self.declare_parameter('port', '/dev/ttyUSB0')
        self.declare_parameter('baudrate', 256000)
        self.declare_parameter('simulate', False)
        self.declare_parameter('hello_client_name', 'ChuongDuong')
        self.declare_parameter('ping_interval_sec', 1.0)
        self.declare_parameter('pong_timeout_sec', 3.0)
        self.declare_parameter('belt_action_timeout_sec', 60.0)

        self._port = self.get_parameter('port').value
        self._baud = self.get_parameter('baudrate').value
        self._simulate = self.get_parameter('simulate').value
        self._hello_name = self.get_parameter('hello_client_name').value
        self._ping_interval = float(self.get_parameter('ping_interval_sec').value)
        self._pong_timeout = float(self.get_parameter('pong_timeout_sec').value)
        self._belt_timeout = float(self.get_parameter('belt_action_timeout_sec').value)

        self._ser = None
        self._serial_open = False
        self._lock = threading.Lock()
        self._estop_latched = False
        self._stm32_state = STATE_IDLE
        self._last_telemetry: Optional[TelemetryFrame] = None
        self._last_hello_msg = ''
        self._alive = False
        self._last_rx_time = 0.0
        self._last_pong_time = 0.0
        self._ping_seq = 0
        self._pending_lines: list[str] = []
        self._line_event = threading.Event()

        self._health_pub = self.create_publisher(Stm32Health, '/stm32/health', 10)
        self._belt1_pub = self.create_publisher(ConveyorStatus, '/conveyor/belt1/status', 10)
        self._belt2_pub = self.create_publisher(ConveyorStatus, '/conveyor/belt2/status', 10)

        self.create_service(
            Stm32Hello, '/stm32/hello', self._hello_srv_cb, callback_group=self._cb_group)
        self.create_service(
            ResetEstop, '/stm32/reset_estop', self._reset_estop_srv_cb,
            callback_group=self._cb_group)
        self.create_service(
            RunBeltCommand, '/run_belt_command', self._run_belt_srv_cb,
            callback_group=self._cb_group)

        self._action_server = ActionServer(
            self,
            BeltLoadUnload,
            '/belt_load_unload',
            execute_callback=self._execute_belt_action,
            goal_callback=self._goal_cb,
            cancel_callback=self._cancel_cb,
            callback_group=self._cb_group,
        )

        self._cancel_nav_cli = self.create_client(Trigger, '/cancel_nav')

        self._open_serial()
        self.create_timer(self._ping_interval, self._ping_timer_cb)
        self.create_timer(0.005, self._read_serial_cb)
        self.create_timer(0.2, self._publish_status_cb)

        mode = 'SIMULATE' if self._simulate else f'UART {self._port}@{self._baud}'
        self.get_logger().info(f'stm32_conveyor_bridge_node — mode={mode}')
        self.get_logger().info('Protocol Version3: START/STOP+side, BUZZER on ACK')
        self._send_uart(cmd_hello(self._hello_name))

    # ── Serial I/O ────────────────────────────────────────────────────────

    def _open_serial(self) -> None:
        if self._simulate:
            self.get_logger().warn('simulate=true — không mở cổng serial thật')
            self._serial_open = True
            return
        if serial is None:
            self.get_logger().error('Thiếu pyserial — pip install pyserial')
            return
        try:
            self._ser = serial.Serial(self._port, self._baud, timeout=0.05)
            try:
                self._ser.setDTR(False)
                self._ser.setRTS(False)
            except Exception:
                pass
            self.get_logger().info(f'Đã mở serial {self._port} baud={self._baud}')
            self._serial_open = True
        except Exception as exc:
            self.get_logger().error(f'Không mở được serial {self._port}: {exc}')
            self._ser = None
            self._serial_open = False

    def _send_uart(self, frame: str) -> None:
        cmd_preview = frame.strip()
        is_ping = cmd_preview.startswith('$PING,') or cmd_preview == '$PING'
        if not is_ping:
            self.get_logger().info(f'UART TX → {cmd_preview}')

        if self._simulate:
            self._simulate_response(frame)
            return

        if self._ser is None or not self._ser.is_open:
            if not is_ping:
                self.get_logger().warn(f'UART TX bỏ qua (chưa kết nối): {cmd_preview}')
            return

        with self._lock:
            self._ser.write((frame + '\r\n').encode('utf-8'))

    def _read_serial_cb(self) -> None:
        if self._simulate:
            return
        if self._ser is None or not self._ser.is_open:
            return
        try:
            while self._ser.in_waiting > 0:
                raw = self._ser.readline()
                if not raw:
                    break
                line = raw.decode('utf-8', errors='ignore').strip()
                if line:
                    self._handle_uart_line(line)
        except Exception as exc:
            self.get_logger().error(f'UART read lỗi: {exc}')

    def _handle_uart_line(self, line: str) -> None:
        self.get_logger().info(f'UART RX ← {line}')
        parsed = parse_line(line)
        if parsed is None:
            self.get_logger().warn(f'UART RX bỏ qua frame không hợp lệ: {line}')
            return

        self._alive = True
        self._last_rx_time = time.monotonic()
        self._pending_lines.append(line)
        self._line_event.set()

        if parsed.msg_type == 'HELLO_ACK':
            msg = parse_hello_ack(parsed)
            if msg:
                self._last_hello_msg = msg
                self._alive = True
                self.get_logger().info(f'STM32 HELLO_ACK: {msg}')

        elif parsed.msg_type == 'PONG':
            seq = parse_pong_seq(parsed)
            if seq is not None:
                self._last_pong_time = time.monotonic()
                self.get_logger().info(f'STM32 PONG: seq={seq}')

        elif parsed.msg_type == 'TELEMETRY':
            telem = parse_telemetry(parsed)
            if telem:
                self._on_telemetry(telem)

        elif parsed.msg_type == 'ACK':
            ack = parse_ack(parsed)
            if ack:
                self.get_logger().info(
                    f'STM32 ACK: kind={ack.kind} belt={ack.belt_id} side={ack.side}')

        elif parsed.msg_type == 'EVENT' and len(parsed.fields) >= 4:
            if parsed.fields[1] == 'BUMPER' and parsed.fields[3] == 'TRIGGER':
                bumper_id = parsed.fields[2]
                self.get_logger().warn(f'EVENT BUMPER trigger id={bumper_id}')
                self._trigger_estop(f'Bumper {bumper_id}')

        elif parsed.msg_type == 'NACK':
            nack = parse_nack(parsed)
            if nack:
                cmd, belt_id, reason = nack
                self.get_logger().warn(f'STM32 NACK: cmd={cmd} belt={belt_id} reason={reason}')
            else:
                self.get_logger().warn(f'STM32 NACK: {line}')

    def _on_telemetry(self, telem: TelemetryFrame) -> None:
        self._last_telemetry = telem
        self._stm32_state = telem.state
        if telem.is_estop:
            self._trigger_estop('TELEMETRY ESTOP')

    # ── Simulate STM32 ─────────────────────────────────────────────────────

    def _simulate_append_later(self, lines: list[str], delay_sec: float) -> None:
        def _worker():
            time.sleep(delay_sec)
            for ln in lines:
                self._pending_lines.append(ln)
            self._line_event.set()

        threading.Thread(target=_worker, daemon=True).start()

    def _simulate_response(self, frame: str) -> None:
        frame = frame.strip()
        parts = frame.lstrip('$').split(',')

        if parts[0] == 'HELLO':
            self._pending_lines.append('$HELLO_ACK,STM32,OK,good job')
            self._last_hello_msg = 'good job'
            self._alive = True
            self._stm32_state = STATE_IDLE
            self._line_event.set()

        elif parts[0] == 'PING':
            self._pending_lines.append(f'$PONG,{parts[1]}')
            self._last_pong_time = time.monotonic()
            self._alive = True
            self._line_event.set()

        elif parts[0] == 'CMD' and len(parts) >= 2:
            sub = parts[1]

            if sub == 'START' and len(parts) >= 3:
                belt_id = int(parts[2])
                self._stm32_state = STATE_RUNNING
                self._estop_latched = False
                cargo_bit = '1' if belt_id == 1 else '0'
                cargo_bit2 = '0' if belt_id == 1 else '1'
                bits_running = f'{cargo_bit}{cargo_bit2}000000'
                bits_idle = f'{cargo_bit}{cargo_bit2}000000'
                self._simulate_append_later(
                    [
                        f'$ACK,CMD,START,{belt_id}',
                        f'$TELEMETRY,RUNNING,{bits_running},{belt_id},NONE',
                    ],
                    0.3,
                )
                self._simulate_append_later(
                    [
                        f'$ACK,CMD,STOP,{belt_id}',
                        f'$TELEMETRY,IDLE,{bits_idle},0,NONE',
                    ],
                    1.8,
                )
                self._stm32_state = STATE_IDLE

            elif sub == 'STOP' and len(parts) >= 4:
                belt_id = int(parts[2])
                side = normalize_side(parts[3])
                self._stm32_state = STATE_RUNNING
                self._simulate_append_later(
                    [
                        f'$ACK,CMD,STOP,{belt_id},{side}',
                        '$TELEMETRY,IDLE,00000000,0,NONE',
                    ],
                    0.8,
                )
                self._stm32_state = STATE_IDLE

            elif sub == 'RESET_ESTOP':
                self._estop_latched = False
                self._stm32_state = STATE_IDLE
                self._pending_lines.append('$ACK,CMD,RESET_ESTOP')
                self._pending_lines.append('$TELEMETRY,IDLE,00000000,0,NONE')
                self._line_event.set()

        elif parts[0] == 'BUZZER':
            pass

    def _wait_for_line(
        self,
        timeout_sec: float,
        predicate: Callable[[str], bool],
        belt_id: int = 0,
    ) -> tuple[Optional[str], Optional[str]]:
        """Chờ dòng UART thỏa predicate. Trả (line, nack_reason)."""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self._estop_latched:
                return None, 'E-Stop — dừng belt'

            for line in list(self._pending_lines):
                parsed = parse_line(line)
                if parsed and parsed.msg_type == 'NACK':
                    nack = parse_nack(parsed)
                    if nack:
                        cmd, nack_belt, reason = nack
                        if belt_id == 0 or nack_belt in (0, belt_id):
                            self._pending_lines.remove(line)
                            return None, f'NACK {cmd}: {reason}'

                if predicate(line):
                    self._pending_lines.remove(line)
                    return line, None

            self._line_event.wait(timeout=0.05)
            self._line_event.clear()

        return None, None

    # ── E-Stop ────────────────────────────────────────────────────────────

    def _trigger_estop(self, reason: str) -> None:
        if self._estop_latched:
            return
        self._estop_latched = True
        self._stm32_state = STATE_ESTOP
        self.get_logger().error(f'E-STOP latched: {reason}')
        if self._cancel_nav_cli.wait_for_service(timeout_sec=0.5):
            self._cancel_nav_cli.call_async(Trigger.Request())

    # ── Timers ────────────────────────────────────────────────────────────

    def _ping_timer_cb(self) -> None:
        if self._estop_latched:
            return
        self._ping_seq += 1
        self._send_uart(cmd_ping(self._ping_seq))

        if self._last_pong_time > 0:
            age = time.monotonic() - self._last_pong_time
            if age > self._pong_timeout:
                self._alive = False
                self.get_logger().warn(f'STM32 mất heartbeat ({age:.1f}s)')
        elif self._last_rx_time > 0:
            age = time.monotonic() - self._last_rx_time
            if age > self._pong_timeout:
                self._alive = False
                self.get_logger().warn(f'STM32 không có RX mới ({age:.1f}s)')

    def _publish_status_cb(self) -> None:
        health = Stm32Health()
        health.alive = self._alive
        if self._alive:
            health.message = self._last_hello_msg or 'heartbeat ok'
        elif self._serial_open:
            health.message = 'serial open, waiting heartbeat'
        else:
            health.message = 'offline'
        health.stm32_state = self._stm32_state
        health.last_pong = self.get_clock().now().to_msg()
        self._health_pub.publish(health)

        telem = self._last_telemetry
        self._belt1_pub.publish(self._make_belt_status(1, telem))
        self._belt2_pub.publish(self._make_belt_status(2, telem))

    def _make_belt_status(self, belt_id: int, telem: Optional[TelemetryFrame]) -> ConveyorStatus:
        msg = ConveyorStatus()
        msg.belt_id = belt_id
        msg.direction = 'NONE'
        msg.sensor_end = False
        msg.has_cargo = False
        msg.state = 'Free'

        if self._estop_latched or self._stm32_state == STATE_ESTOP:
            msg.state = 'Estop'
            return msg

        if telem is None:
            return msg

        msg.has_cargo = telem.belt1_has_cargo if belt_id == 1 else telem.belt2_has_cargo

        if telem.state == STATE_RUNNING and telem.belt_is_active(belt_id):
            msg.state = 'Running'
        elif msg.has_cargo:
            msg.state = 'Occupied'
            msg.sensor_end = True
        else:
            msg.state = 'Free'

        return msg

    # ── Belt commands ─────────────────────────────────────────────────────

    def _run_belt_load_sync(self, belt_id: int, timeout_sec: float) -> tuple[bool, str]:
        self._pending_lines.clear()
        self._send_uart(cmd_start_load(belt_id))

        line, err = self._wait_for_line(
            timeout_sec,
            lambda ln: ack_matches_load_started(ln, belt_id),
            belt_id=belt_id,
        )
        if err:
            return False, err
        if line is None:
            return False, f'Timeout chờ $ACK,CMD,START,{belt_id}'

        self.get_logger().info(f'Belt {belt_id}: hàng phát hiện, đang load...')

        remaining = max(1.0, timeout_sec - 1.0)
        line, err = self._wait_for_line(
            remaining,
            lambda ln: ack_matches_load_done(ln, belt_id),
            belt_id=belt_id,
        )
        if err:
            return False, err
        if line is None:
            return False, f'Timeout chờ $ACK,CMD,STOP,{belt_id} (load xong)'

        self._send_uart(cmd_buzzer_start(belt_id))
        return True, f'Belt {belt_id} load thành công'

    def _run_belt_unload_sync(
        self, belt_id: int, side: str, timeout_sec: float,
    ) -> tuple[bool, str]:
        side_norm = normalize_side(side)
        self._pending_lines.clear()
        self._send_uart(cmd_unload_belt(belt_id, side_norm))

        line, err = self._wait_for_line(
            timeout_sec,
            lambda ln: ack_matches_unload_done(ln, belt_id, side_norm),
            belt_id=belt_id,
        )
        if err:
            return False, err
        if line is None:
            return False, f'Timeout chờ $ACK,CMD,STOP,{belt_id},{side_norm}'

        self._send_uart(cmd_buzzer_stop(belt_id))
        return True, f'Belt {belt_id} unload {side_norm} thành công'

    def _run_belt_sync(
        self,
        belt_id: int,
        command: str,
        side: str,
        timeout_sec: float,
    ) -> tuple[bool, str]:
        cmd = command.lower()
        if cmd == 'load':
            return self._run_belt_load_sync(belt_id, timeout_sec)
        if cmd == 'unload':
            return self._run_belt_unload_sync(belt_id, side, timeout_sec)
        return False, f'Lệnh không hợp lệ: {command}'

    # ── Services ──────────────────────────────────────────────────────────

    def _hello_srv_cb(self, request: Stm32Hello.Request, response: Stm32Hello.Response):
        name = request.client_name or self._hello_name
        self._send_uart(cmd_hello(name))
        line, _ = self._wait_for_line(2.0, lambda ln: ln.startswith('$HELLO_ACK'))
        if line:
            parsed = parse_line(line)
            msg = parse_hello_ack(parsed) if parsed else None
            response.success = True
            response.message = msg or 'OK'
            response.stm32_state = self._stm32_state
        else:
            response.success = False
            response.message = 'Timeout chờ HELLO_ACK'
            response.stm32_state = self._stm32_state
        return response

    def _reset_estop_srv_cb(self, request: ResetEstop.Request, response: ResetEstop.Response):
        del request
        self._send_uart(cmd_reset_estop())
        line, _ = self._wait_for_line(2.0, lambda ln: 'RESET_ESTOP' in ln)
        if line or self._simulate:
            self._estop_latched = False
            self._stm32_state = STATE_IDLE
            response.success = True
            response.message = 'Đã reset E-Stop'
            response.stm32_state = STATE_IDLE
        else:
            response.success = False
            response.message = 'Timeout reset E-Stop'
            response.stm32_state = self._stm32_state
        return response

    def _run_belt_srv_cb(self, request: RunBeltCommand.Request, response: RunBeltCommand.Response):
        timeout = request.timeout_sec if request.timeout_sec > 0 else self._belt_timeout
        side = getattr(request, 'side', '') or ''
        ok, msg = self._run_belt_sync(request.belt_id, request.command, side, timeout)
        response.success = ok
        response.message = msg
        return response

    # ── Action Server ─────────────────────────────────────────────────────

    def _goal_cb(self, goal_request):
        if self._estop_latched:
            return GoalResponse.REJECT
        if goal_request.belt_id not in (1, 2):
            return GoalResponse.REJECT
        if goal_request.command.lower() not in ('load', 'unload'):
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_cb(self, goal_handle):
        self.get_logger().warn(
            f'Hủy action belt {goal_handle.request.belt_id} — không gửi lệnh UART (protocol V3)')
        return CancelResponse.ACCEPT

    async def _execute_belt_action(self, goal_handle):
        req = goal_handle.request
        belt_id = req.belt_id
        command = req.command.lower()
        side = getattr(req, 'side', '') or ''
        timeout_sec = req.timeout_sec if req.timeout_sec > 0 else self._belt_timeout

        feedback = BeltLoadUnload.Feedback()
        feedback.stm32_state = STATE_RUNNING
        feedback.progress = 0.1
        feedback.status_message = 'Đang gửi lệnh UART...'
        goal_handle.publish_feedback(feedback)

        ok, msg = self._run_belt_sync(belt_id, command, side, timeout_sec)

        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
            result = BeltLoadUnload.Result()
            result.success = False
            result.message = 'Action bị huỷ'
            result.final_state = self._stm32_state
            return result

        result = BeltLoadUnload.Result()
        result.success = ok
        result.message = msg
        result.final_state = self._stm32_state
        if ok:
            goal_handle.succeed()
        else:
            goal_handle.abort()
        return result


def main():
    rclpy.init()
    node = Stm32ConveyorBridgeNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
