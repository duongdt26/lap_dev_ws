#!/usr/bin/env python3
"""
stm32_conveyor_bridge_node.py — Cầu nối UART STM32 ↔ ROS2 (Version3/Safe V4.1).

Link state: DISCONNECTED → HELLO_SENT → ONLINE ↔ COMM_LOST
Safety: ưu tiên ESTOP / STOP_LOCK / FAULT / COMM_LOST trước lệnh băng tải.
Conveyor action theo seq: COMMAND_SENT → ACCEPTED → LOAD_DETECTED → LOAD_DONE / UNLOAD_DONE.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
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
    ACCEPTED,
    BELT_STATE_LOADED,
    BELT_STATE_LOADING,
    BELT_STATE_UNLOADING,
    PROTOCOL_VERSION,
    STATE_COMM_LOST,
    STATE_ESTOP,
    STATE_FAULT,
    STATE_IDLE,
    STATE_READY,
    STATE_RUNNING,
    STATE_STOP_LOCK,
    AckFrame,
    EventFrame,
    TelemetryFrame,
    ack_matches_accepted,
    cmd_buzzer_start,
    cmd_buzzer_stop,
    cmd_hello,
    cmd_ping,
    cmd_ready,
    cmd_reset,
    cmd_reset_legacy,
    cmd_reset_estop,
    cmd_reset_estop_legacy,
    cmd_estop,
    cmd_estop_legacy,
    cmd_start_load,
    cmd_start_load_legacy,
    cmd_unload_belt,
    cmd_unload_belt_legacy,
    normalize_side,
    parse_ack,
    parse_event,
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


class LinkState(str, Enum):
    DISCONNECTED = 'DISCONNECTED'
    HELLO_SENT = 'HELLO_SENT'
    ONLINE = 'ONLINE'
    COMM_LOST = 'COMM_LOST'


class SafetyState(str, Enum):
    NORMAL = 'NORMAL'
    STOP_LOCK = 'STOP_LOCK'
    ESTOP = 'ESTOP'
    FAULT = 'FAULT'
    COMM_LOST = 'COMM_LOST'


class ActionPhase(str, Enum):
    NONE = 'NONE'
    COMMAND_SENT = 'COMMAND_SENT'
    ACCEPTED = 'ACCEPTED'
    LOAD_DETECTED = 'LOAD_DETECTED'
    LOAD_DONE = 'LOAD_DONE'
    UNLOAD_DONE = 'UNLOAD_DONE'
    FAILED = 'FAILED'
    TIMEOUT = 'TIMEOUT'


@dataclass
class PendingCommand:
    seq: int
    cmd: str
    belt_id: int = 0
    side: str = ''
    phase: ActionPhase = ActionPhase.COMMAND_SENT
    error: str = ''


class Stm32ConveyorBridgeNode(Node):
    def __init__(self):
        super().__init__('stm32_conveyor_bridge_node')
        self._cb_group = ReentrantCallbackGroup()

        self.declare_parameter('port', '/dev/ttyUSB0')
        self.declare_parameter('baudrate', 256000)
        self.declare_parameter('simulate', False)
        self.declare_parameter('ping_interval_sec', 0.5)
        self.declare_parameter('pong_timeout_sec', 2.0)
        self.declare_parameter('belt_action_timeout_sec', 60.0)
        self.declare_parameter('auto_ready', True)
        self.declare_parameter('protocol_mode', 'legacy_v3')

        self._port = self.get_parameter('port').value
        self._baud = int(self.get_parameter('baudrate').value)
        self._simulate = bool(self.get_parameter('simulate').value)
        self._ping_interval = float(self.get_parameter('ping_interval_sec').value)
        self._pong_timeout = float(self.get_parameter('pong_timeout_sec').value)
        self._belt_timeout = float(self.get_parameter('belt_action_timeout_sec').value)
        self._auto_ready = bool(self.get_parameter('auto_ready').value)
        requested_protocol = str(self.get_parameter('protocol_mode').value).strip().lower()
        if requested_protocol not in ('auto', 'legacy_v3', 'v4_1'):
            self.get_logger().warn(
                f'protocol_mode={requested_protocol!r} không hợp lệ; dùng legacy_v3')
            requested_protocol = 'legacy_v3'
        self._requested_protocol = requested_protocol
        self._active_protocol: Optional[str] = (
            None if requested_protocol == 'auto' else requested_protocol)

        self._ser = None
        self._serial_open = False
        self._lock = threading.Lock()
        self._cmd_seq = 100
        self._ping_seq = 0

        self._link_state = LinkState.DISCONNECTED
        self._safety_state = SafetyState.NORMAL
        self._stm32_state = STATE_IDLE
        self._ros_ready_sent = False
        self._last_telemetry: Optional[TelemetryFrame] = None
        self._last_hello_msg = ''
        self._alive = False
        self._last_rx_time = 0.0
        self._last_pong_time = 0.0
        self._pending: dict[int, PendingCommand] = {}
        self._pending_lines: list[str] = []
        self._line_event = threading.Event()

        self._health_pub = self.create_publisher(Stm32Health, '/stm32/health', 10)
        self._belt1_pub = self.create_publisher(ConveyorStatus, '/conveyor/belt1/status', 10)
        self._belt2_pub = self.create_publisher(ConveyorStatus, '/conveyor/belt2/status', 10)

        self.create_service(
            Stm32Hello, '/stm32/hello', self._hello_srv_cb, callback_group=self._cb_group)
        self.create_service(
            ResetEstop, '/stm32/estop', self._estop_srv_cb,
            callback_group=self._cb_group)
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
        self.get_logger().info(
            f'stm32_conveyor_bridge_node — mode={mode}, '
            f'protocol_mode={self._requested_protocol}')
        self._send_hello()

    # ── Sequence / state helpers ──────────────────────────────────────────

    def _next_cmd_seq(self) -> int:
        self._cmd_seq += 1
        return self._cmd_seq

    def _uses_legacy_protocol(self) -> bool:
        return self._active_protocol == 'legacy_v3'

    def _find_legacy_pending(self, belt_id: int = 0) -> Optional[PendingCommand]:
        """Version3 không echo seq, nên ghép ACK với lệnh nội bộ đang chờ."""
        terminal = {
            ActionPhase.LOAD_DONE,
            ActionPhase.UNLOAD_DONE,
            ActionPhase.FAILED,
            ActionPhase.TIMEOUT,
        }
        for pending in reversed(list(self._pending.values())):
            if pending.phase in terminal:
                continue
            if belt_id and pending.belt_id not in (0, belt_id):
                continue
            return pending
        return None

    def _find_legacy_pending_cmd(self, cmd: str) -> Optional[PendingCommand]:
        terminal = {
            ActionPhase.LOAD_DONE,
            ActionPhase.UNLOAD_DONE,
            ActionPhase.FAILED,
            ActionPhase.TIMEOUT,
        }
        for pending in reversed(list(self._pending.values())):
            if pending.phase in terminal:
                continue
            if pending.cmd == cmd:
                return pending
        return None

    def _can_run_conveyor(self) -> tuple[bool, str]:
        if self._link_state != LinkState.ONLINE:
            return False, f'Link chưa ONLINE ({self._link_state.value})'
        if self._safety_state == SafetyState.ESTOP:
            return False, 'Đang ESTOP'
        if self._safety_state == SafetyState.STOP_LOCK:
            return False, 'Đang STOP_LOCK'
        if self._safety_state == SafetyState.FAULT:
            return False, 'Đang FAULT'
        if self._safety_state == SafetyState.COMM_LOST:
            return False, 'Đang COMM_LOST'
        if self._stm32_state in (STATE_ESTOP, STATE_STOP_LOCK, STATE_FAULT, STATE_COMM_LOST):
            return False, f'STM32 state={self._stm32_state}'
        if self._stm32_state not in (STATE_READY, STATE_IDLE, STATE_RUNNING):
            return False, f'STM32 chưa READY ({self._stm32_state})'
        return True, ''

    def _update_safety_from_telemetry(self, telem: TelemetryFrame) -> None:
        if telem.is_estop:
            self._safety_state = SafetyState.ESTOP
        elif telem.is_comm_lost:
            self._safety_state = SafetyState.COMM_LOST
            self._link_state = LinkState.COMM_LOST
        elif telem.is_fault:
            self._safety_state = SafetyState.FAULT
        elif telem.is_stop_lock:
            self._safety_state = SafetyState.STOP_LOCK
        elif self._safety_state != SafetyState.ESTOP:
            self._safety_state = SafetyState.NORMAL

    def _trigger_nav_cancel(self, reason: str) -> None:
        self.get_logger().error(f'Safety trigger: {reason}')
        if self._cancel_nav_cli.wait_for_service(timeout_sec=0.5):
            self._cancel_nav_cli.call_async(Trigger.Request())

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
        is_ping = frame.startswith('$PING,')
        if not is_ping:
            self.get_logger().info(f'UART TX → {frame}')

        if self._simulate:
            self._simulate_response(frame)
            return

        if self._ser is None or not self._ser.is_open:
            if not is_ping:
                self.get_logger().warn(f'UART TX bỏ qua (chưa kết nối): {frame}')
            return

        with self._lock:
            self._ser.write((frame + '\r\n').encode('utf-8'))

    def _send_hello(self) -> None:
        self._link_state = LinkState.HELLO_SENT
        self._send_uart(cmd_hello())

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
                self._link_state = LinkState.ONLINE
                self.get_logger().info(f'STM32 HELLO_ACK: {msg}')
                if self._requested_protocol == 'auto':
                    detected = (
                        'v4_1' if PROTOCOL_VERSION in msg.upper() else 'legacy_v3')
                    if detected != self._active_protocol:
                        self._active_protocol = detected
                        self.get_logger().warn(
                            f'Tự nhận diện UART protocol={detected} từ HELLO_ACK={msg!r}')
                if self._auto_ready:
                    # Không chờ ACK ngay trong callback đọc UART, nếu không ACK
                    # READY sẽ nằm trong serial buffer cho tới khi timeout.
                    threading.Thread(
                        target=self._ensure_ready, daemon=True).start()

        elif parsed.msg_type == 'PONG':
            seq = parse_pong_seq(parsed)
            if seq is not None and seq >= 0:
                self._last_pong_time = time.monotonic()
                if self._link_state == LinkState.COMM_LOST:
                    self._link_state = LinkState.ONLINE
                    self.get_logger().info('UART link phục hồi sau COMM_LOST')

        elif parsed.msg_type == 'TELEMETRY':
            telem = parse_telemetry(parsed)
            if telem:
                self._on_telemetry(telem)

        elif parsed.msg_type == 'ACK':
            ack = parse_ack(parsed)
            if ack:
                self._on_ack(ack)

        elif parsed.msg_type == 'NACK':
            nack = parse_nack(parsed)
            if nack:
                self._on_nack(nack)

        elif parsed.msg_type == 'EVENT':
            ev = parse_event(parsed)
            if ev:
                self._on_event(ev)

    def _on_telemetry(self, telem: TelemetryFrame) -> None:
        self._last_telemetry = telem
        self._stm32_state = telem.state
        self._update_safety_from_telemetry(telem)
        if telem.is_estop:
            self._trigger_nav_cancel('TELEMETRY ESTOP')

    def _on_ack(self, ack: AckFrame) -> None:
        self.get_logger().info(
            f'STM32 ACK: seq={ack.seq} cmd={ack.cmd} belt={ack.belt_id} status={ack.status}')
        pending = self._pending.get(ack.seq)
        if pending is None and ack.seq == 0 and self._uses_legacy_protocol():
            pending = self._find_legacy_pending_cmd(ack.cmd)
            if pending is None:
                pending = self._find_legacy_pending(ack.belt_id)
        if pending is None:
            return

        if self._uses_legacy_protocol():
            if pending.cmd == 'START':
                if ack.cmd == 'START':
                    pending.phase = ActionPhase.ACCEPTED
                elif ack.cmd == 'STOP':
                    pending.phase = ActionPhase.LOAD_DONE
            elif pending.cmd == 'UNLOAD' and ack.cmd in ('STOP', 'UNLOAD'):
                if ack.belt_id != pending.belt_id or ack.side != pending.side:
                    self.get_logger().warn(
                        f'Bỏ qua ACK unload không khớp: chờ belt={pending.belt_id} '
                        f'side={pending.side}, nhận belt={ack.belt_id} side={ack.side}')
                    return
                pending.phase = ActionPhase.UNLOAD_DONE
            elif pending.cmd in ('READY', 'ENABLE', 'RESET', 'RESET_ESTOP', 'ESTOP') and (
                    ack.cmd == pending.cmd):
                pending.phase = ActionPhase.ACCEPTED
            return
        if ack.cmd in ('READY', 'ENABLE'):
            self._ros_ready_sent = True
            pending.phase = ActionPhase.ACCEPTED
        elif ack.cmd in ('RESET', 'RESET_ESTOP', 'ESTOP'):
            pending.phase = ActionPhase.ACCEPTED
        elif ack.status == ACCEPTED:
            pending.phase = ActionPhase.ACCEPTED

    def _on_nack(self, nack) -> None:
        self.get_logger().warn(
            f'STM32 NACK: seq={nack.seq} cmd={nack.cmd} belt={nack.belt_id} reason={nack.reason}')
        pending = self._pending.get(nack.seq)
        if pending is None and nack.seq == 0 and self._uses_legacy_protocol():
            pending = self._find_legacy_pending(nack.belt_id)
        if pending:
            pending.phase = ActionPhase.FAILED
            pending.error = nack.reason

    def _on_event(self, ev: EventFrame) -> None:
        self.get_logger().info(f'STM32 EVENT: seq={ev.seq} event={ev.event} fields={ev.fields}')

        if ev.event == 'ESTOP':
            self._safety_state = SafetyState.ESTOP
            self._stm32_state = STATE_ESTOP
            self._trigger_nav_cancel(f'EVENT ESTOP {ev.fields}')
        elif ev.event == 'BUMPER':
            self._safety_state = SafetyState.ESTOP
            self._trigger_nav_cancel(f'EVENT BUMPER {ev.fields}')
        elif ev.event == 'STOP_LOCK' and ev.fields and ev.fields[0] == 'TRIGGER':
            self._safety_state = SafetyState.STOP_LOCK
            self._stm32_state = STATE_STOP_LOCK
        elif ev.event == 'STOP_LOCK' and ev.fields and ev.fields[0] == 'CLEAR':
            if self._safety_state == SafetyState.STOP_LOCK:
                self._safety_state = SafetyState.NORMAL
        elif ev.event == 'COMM_LOST':
            self._safety_state = SafetyState.COMM_LOST
            self._link_state = LinkState.COMM_LOST
            self._stm32_state = STATE_COMM_LOST
        elif ev.event == 'READY':
            self._stm32_state = STATE_READY
            self._ros_ready_sent = True
        elif ev.event == 'FAULT':
            self._safety_state = SafetyState.FAULT
            self._stm32_state = STATE_FAULT

        pending = self._pending.get(ev.seq)
        if pending is None:
            return

        if ev.event == 'LOAD_DETECTED':
            pending.phase = ActionPhase.LOAD_DETECTED
        elif ev.event == 'LOAD_DONE':
            pending.phase = ActionPhase.LOAD_DONE
        elif ev.event == 'UNLOAD_DONE':
            pending.phase = ActionPhase.UNLOAD_DONE
        elif ev.event == 'FAULT':
            pending.phase = ActionPhase.FAILED
            pending.error = ev.fields[0] if ev.fields else 'FAULT'

    # ── Simulate STM32 Version3 / V4.1 ───────────────────────────────────

    def _simulate_append_later(self, lines: list[str], delay_sec: float) -> None:
        def _worker():
            time.sleep(delay_sec)
            for ln in lines:
                self._handle_uart_line(ln)
        threading.Thread(target=_worker, daemon=True).start()

    def _simulate_response(self, frame: str) -> None:
        frame = frame.strip()
        parts = frame.lstrip('$').split(',')

        if parts[0] == 'HELLO':
            hello_version = (
                'good job' if self._requested_protocol == 'legacy_v3'
                else PROTOCOL_VERSION)
            self._handle_uart_line(f'$HELLO_ACK,STM32,OK,{hello_version}')

        elif parts[0] == 'PING' and len(parts) >= 2:
            self._handle_uart_line(f'$PONG,{parts[1]}')

        elif parts[0] == 'CMD' and self._uses_legacy_protocol() and len(parts) >= 2:
            sub = parts[1]

            if sub == 'START' and len(parts) >= 3:
                belt_id = parts[2]
                self._simulate_append_later([
                    f'$ACK,CMD,START,{belt_id}',
                    f'$TELEMETRY,RUNNING,10000000,{belt_id},NONE',
                ], 0.2)
                self._simulate_append_later([
                    f'$ACK,CMD,STOP,{belt_id}',
                    '$TELEMETRY,IDLE,10000000,0,NONE',
                ], 1.0)

            elif sub == 'STOP' and len(parts) >= 4:
                belt_id = parts[2]
                side = normalize_side(parts[3])
                self._simulate_append_later([
                    f'$ACK,CMD,STOP,{belt_id},{side}',
                    '$TELEMETRY,IDLE,00000000,0,NONE',
                ], 0.6)

            elif sub in ('RESET', 'RESET_ESTOP', 'ESTOP'):
                self._handle_uart_line(f'$ACK,CMD,{sub}')
                if sub == 'ESTOP':
                    self._handle_uart_line(
                        '$TELEMETRY,ESTOP,00000000,0,NONE,1,0,IDLE,IDLE,0')
                else:
                    self._handle_uart_line('$TELEMETRY,IDLE,00000000,0,NONE')

        elif parts[0] == 'CMD' and len(parts) >= 3:
            seq = parts[1]
            sub = parts[2]

            if sub in ('READY', 'ENABLE'):
                self._handle_uart_line(f'$ACK,{seq},CMD,{sub}')
                self._handle_uart_line('$EVENT,READY')

            elif sub in ('RESET', 'RESET_ESTOP', 'ESTOP'):
                what = 'STOP_LOCK' if sub == 'RESET' else 'ESTOP'
                self._handle_uart_line(f'$ACK,{seq},CMD,{sub},{what}')
                if sub == 'ESTOP':
                    self._handle_uart_line(
                        '$TELEMETRY,ESTOP,00000000,0,NONE,1,0,IDLE,IDLE,0')
                else:
                    self._handle_uart_line(f'$EVENT,RESET,{what}')

            elif sub == 'START' and len(parts) >= 4:
                belt_id = parts[3]
                self._handle_uart_line(f'$ACK,{seq},CMD,START,{belt_id},ACCEPTED')
                self._simulate_append_later([
                    f'$EVENT,{seq},LOAD_DETECTED,{belt_id},1,3',
                    f'$TELEMETRY,RUNNING,10000000,{belt_id},NONE,0,0,LOADING,IDLE,0',
                ], 0.4)
                self._simulate_append_later([
                    f'$EVENT,{seq},LOAD_DONE,{belt_id},3',
                    f'$TELEMETRY,READY,10000000,0,NONE,0,0,LOADED,IDLE,0',
                ], 1.5)

            elif sub in ('STOP', 'UNLOAD') and len(parts) >= 5:
                belt_id = parts[3]
                side = normalize_side(parts[4])
                self._handle_uart_line(f'$ACK,{seq},CMD,STOP,{belt_id},{side},ACCEPTED')
                self._simulate_append_later([
                    f'$EVENT,{seq},UNLOAD_DONE,{belt_id},{side},1',
                    f'$TELEMETRY,READY,00000000,0,NONE,0,0,IDLE,IDLE,0',
                ], 1.0)

        elif parts[0] == 'BUZZER':
            pass

    # ── Command helpers ───────────────────────────────────────────────────

    def _ensure_ready(self, timeout_sec: float = 2.0) -> tuple[bool, str]:
        if self._active_protocol is None:
            return False, 'Chưa nhận HELLO_ACK để xác định UART protocol'

        # STM32 Version3 không có bước READY; IDLE + link/safety hợp lệ là đủ.
        if self._uses_legacy_protocol():
            ok, reason = self._can_run_conveyor()
            if ok:
                self._ros_ready_sent = True
                return True, 'Version3 ready (không gửi CMD READY)'
            return False, reason

        if self._ros_ready_sent and self._stm32_state in (STATE_READY, STATE_IDLE, STATE_RUNNING):
            return True, 'already ready'

        ok, reason = self._can_run_conveyor()
        if not ok and self._safety_state not in (SafetyState.NORMAL,):
            if self._safety_state in (SafetyState.ESTOP, SafetyState.STOP_LOCK, SafetyState.FAULT):
                return False, reason

        seq = self._next_cmd_seq()
        self._pending[seq] = PendingCommand(seq=seq, cmd='READY')
        self._send_uart(cmd_ready(seq))

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            pending = self._pending.get(seq)
            if pending and pending.phase == ActionPhase.ACCEPTED:
                self._ros_ready_sent = True
                return True, 'READY ok'
            if pending and pending.phase == ActionPhase.FAILED:
                return False, pending.error
            time.sleep(0.05)

        return False, 'Timeout chờ READY'

    def _send_estop(self, timeout_sec: float = 2.0) -> tuple[bool, str]:
        seq = self._next_cmd_seq()
        self._pending[seq] = PendingCommand(seq=seq, cmd='ESTOP')
        frame = cmd_estop_legacy() if self._uses_legacy_protocol() else cmd_estop(seq)
        self._send_uart(frame)
        self.get_logger().warn(f'Gửi STM32 ESTOP: {frame}')

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            pending = self._pending.get(seq)
            if pending and pending.phase == ActionPhase.ACCEPTED:
                self._safety_state = SafetyState.ESTOP
                self._stm32_state = STATE_ESTOP
                self._ros_ready_sent = False
                self._trigger_nav_cancel('CMD ESTOP')
                return True, 'ESTOP ok'
            if pending and pending.phase == ActionPhase.FAILED:
                return False, pending.error
            time.sleep(0.05)

        # Vẫn coi là đã yêu cầu dừng khẩn cấp dù timeout ACK
        self._safety_state = SafetyState.ESTOP
        self._stm32_state = STATE_ESTOP
        self._trigger_nav_cancel('CMD ESTOP (timeout ACK)')
        return False, 'Timeout chờ ACK ESTOP'

    def _send_reset(self, estop_only: bool = False, timeout_sec: float = 2.0) -> tuple[bool, str]:
        seq = self._next_cmd_seq()
        cmd_name = 'RESET_ESTOP' if estop_only else 'RESET'
        self._pending[seq] = PendingCommand(seq=seq, cmd=cmd_name)
        if self._uses_legacy_protocol():
            frame = cmd_reset_estop_legacy() if estop_only else cmd_reset_legacy()
        else:
            frame = cmd_reset_estop(seq) if estop_only else cmd_reset(seq)
        self._send_uart(frame)

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            pending = self._pending.get(seq)
            if pending and pending.phase == ActionPhase.ACCEPTED:
                if self._safety_state == SafetyState.ESTOP:
                    self._safety_state = SafetyState.NORMAL
                elif self._safety_state == SafetyState.STOP_LOCK:
                    self._safety_state = SafetyState.NORMAL
                self._ros_ready_sent = False
                return True, 'RESET ok'
            if pending and pending.phase == ActionPhase.FAILED:
                return False, pending.error
            time.sleep(0.05)

        return False, 'Timeout chờ RESET'

    def _wait_for_pending(
        self,
        seq: int,
        timeout_sec: float,
        phase_check: Callable[[PendingCommand], bool],
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self._safety_state in (SafetyState.ESTOP, SafetyState.STOP_LOCK, SafetyState.FAULT, SafetyState.COMM_LOST):
                return False, f'Dừng do safety={self._safety_state.value}'

            pending = self._pending.get(seq)
            if pending:
                if pending.phase == ActionPhase.FAILED:
                    return False, pending.error or 'FAILED'
                if pending.phase == ActionPhase.TIMEOUT:
                    return False, 'TIMEOUT'
                if phase_check(pending):
                    return True, pending.phase.value

            self._line_event.wait(timeout=0.05)
            self._line_event.clear()

        return False, 'TIMEOUT'

    def _run_belt_load_sync(self, belt_id: int, timeout_sec: float) -> tuple[bool, str]:
        ready_ok, ready_msg = self._ensure_ready()
        if not ready_ok:
            return False, ready_msg

        can, reason = self._can_run_conveyor()
        if not can:
            return False, reason

        seq = self._next_cmd_seq()
        self._pending[seq] = PendingCommand(seq=seq, cmd='START', belt_id=belt_id)
        frame = (
            cmd_start_load_legacy(belt_id) if self._uses_legacy_protocol()
            else cmd_start_load(seq, belt_id))
        legacy_deadline = (
            time.monotonic() + timeout_sec
            if self._uses_legacy_protocol() else None)
        self._send_uart(frame)

        ack_timeout = 15.0
        if legacy_deadline is not None:
            ack_timeout = min(
                ack_timeout, max(0.0, legacy_deadline - time.monotonic()))
        ok, msg = self._wait_for_pending(
            seq, ack_timeout, lambda p: p.phase in (
                ActionPhase.ACCEPTED,
                ActionPhase.LOAD_DETECTED,
                ActionPhase.LOAD_DONE,
            ))
        if not ok:
            if msg == 'TIMEOUT':
                return False, f'Timeout ACK START belt {belt_id}'
            return False, msg

        completion_timeout = timeout_sec
        if legacy_deadline is not None:
            completion_timeout = max(
                0.0, legacy_deadline - time.monotonic())

        ok, msg = self._wait_for_pending(
            seq, completion_timeout,
            lambda p: p.phase in (ActionPhase.LOAD_DETECTED, ActionPhase.LOAD_DONE))
        if not ok:
            if msg == 'TIMEOUT':
                return False, (
                    f'Timeout BT{belt_id} sau {timeout_sec:.1f}s '
                    f'tu luc gui CMD START')
            return False, msg

        if self._pending[seq].phase == ActionPhase.LOAD_DETECTED:
            done_timeout = timeout_sec
            if legacy_deadline is not None:
                done_timeout = max(
                    0.0, legacy_deadline - time.monotonic())
            ok, msg = self._wait_for_pending(
                seq, done_timeout, lambda p: p.phase == ActionPhase.LOAD_DONE)
            if not ok:
                if msg == 'TIMEOUT':
                    return False, (
                        f'Timeout BT{belt_id} sau {timeout_sec:.1f}s '
                        f'tu luc gui CMD START')
                return False, msg

        self._send_uart(cmd_buzzer_start(belt_id))
        return True, f'Belt {belt_id} load thành công (seq={seq})'

    def _run_belt_unload_sync(
        self, belt_id: int, side: str, timeout_sec: float,
    ) -> tuple[bool, str]:
        side_norm = normalize_side(side)
        ready_ok, ready_msg = self._ensure_ready()
        if not ready_ok:
            return False, ready_msg

        can, reason = self._can_run_conveyor()
        if not can:
            return False, reason

        seq = self._next_cmd_seq()
        self._pending[seq] = PendingCommand(seq=seq, cmd='UNLOAD', belt_id=belt_id, side=side_norm)
        frame = (
            cmd_unload_belt_legacy(belt_id, side_norm) if self._uses_legacy_protocol()
            else cmd_unload_belt(seq, belt_id, side_norm))
        legacy_deadline = (
            time.monotonic() + timeout_sec
            if self._uses_legacy_protocol() else None)
        self._send_uart(frame)

        ack_timeout = 5.0
        if legacy_deadline is not None:
            ack_timeout = min(
                ack_timeout, max(0.0, legacy_deadline - time.monotonic()))
        ok, msg = self._wait_for_pending(
            seq, ack_timeout, lambda p: p.phase in (
                ActionPhase.ACCEPTED,
                ActionPhase.UNLOAD_DONE,
            ))
        if not ok:
            if msg == 'TIMEOUT':
                return False, f'Timeout ACK UNLOAD belt {belt_id}'
            return False, msg

        completion_timeout = timeout_sec
        if legacy_deadline is not None:
            completion_timeout = max(
                0.0, legacy_deadline - time.monotonic())

        ok, msg = self._wait_for_pending(
            seq, completion_timeout,
            lambda p: p.phase == ActionPhase.UNLOAD_DONE)
        if not ok:
            if msg == 'TIMEOUT':
                return False, (
                    f'Timeout BT{belt_id} sau {timeout_sec:.1f}s '
                    f'tu luc gui lenh UART')
            return False, msg

        self._send_uart(cmd_buzzer_stop(belt_id))
        return True, f'Belt {belt_id} unload {side_norm} thành công (seq={seq})'

    def _run_belt_sync(
        self, belt_id: int, command: str, side: str, timeout_sec: float,
    ) -> tuple[bool, str]:
        cmd = command.lower()
        if cmd == 'load':
            return self._run_belt_load_sync(belt_id, timeout_sec)
        if cmd == 'unload':
            return self._run_belt_unload_sync(belt_id, side, timeout_sec)
        return False, f'Lệnh không hợp lệ: {command}'

    # ── Timers ────────────────────────────────────────────────────────────

    def _ping_timer_cb(self) -> None:
        if self._safety_state == SafetyState.ESTOP:
            return

        self._ping_seq += 1
        self._send_uart(cmd_ping(self._ping_seq))

        if self._last_pong_time > 0:
            age = time.monotonic() - self._last_pong_time
            if age > self._pong_timeout:
                self._alive = False
                self._link_state = LinkState.COMM_LOST
                self._safety_state = SafetyState.COMM_LOST
                self.get_logger().warn(f'STM32 mất heartbeat ({age:.1f}s) → COMM_LOST')
        elif self._last_rx_time > 0:
            age = time.monotonic() - self._last_rx_time
            if age > self._pong_timeout:
                self._alive = False
                self.get_logger().warn(f'STM32 không có RX mới ({age:.1f}s)')

    def _publish_status_cb(self) -> None:
        health = Stm32Health()
        health.alive = self._alive and self._link_state == LinkState.ONLINE
        if health.alive:
            health.message = self._last_hello_msg or 'heartbeat ok'
        elif self._link_state == LinkState.COMM_LOST:
            health.message = 'COMM_LOST'
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

        if self._safety_state == SafetyState.ESTOP or self._stm32_state == STATE_ESTOP:
            msg.state = 'Estop'
            return msg
        if self._safety_state == SafetyState.STOP_LOCK:
            msg.state = 'StopLock'
            return msg
        if self._safety_state in (SafetyState.FAULT, SafetyState.COMM_LOST):
            msg.state = self._safety_state.value
            return msg

        if telem is None:
            return msg

        belt_state = telem.belt1_state if belt_id == 1 else telem.belt2_state
        msg.has_cargo = telem.belt1_has_cargo if belt_id == 1 else telem.belt2_has_cargo

        if belt_state == BELT_STATE_LOADING or belt_state == BELT_STATE_UNLOADING:
            msg.state = 'Running'
        elif belt_state == BELT_STATE_LOADED or msg.has_cargo:
            msg.state = 'Occupied'
            msg.sensor_end = True
        elif telem.belt_is_active(belt_id):
            msg.state = 'Running'
        else:
            msg.state = 'Free'

        return msg

    # ── Services / Action ─────────────────────────────────────────────────

    def _hello_srv_cb(self, request: Stm32Hello.Request, response: Stm32Hello.Response):
        del request
        self._send_hello()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if self._link_state == LinkState.ONLINE:
                response.success = True
                response.message = self._last_hello_msg or PROTOCOL_VERSION
                response.stm32_state = self._stm32_state
                return response
            time.sleep(0.05)
        response.success = False
        response.message = 'Timeout chờ HELLO_ACK'
        response.stm32_state = self._stm32_state
        return response

    def _estop_srv_cb(self, request: ResetEstop.Request, response: ResetEstop.Response):
        del request
        ok, msg = self._send_estop()
        response.success = ok
        response.message = msg
        response.stm32_state = self._stm32_state
        return response

    def _reset_estop_srv_cb(self, request: ResetEstop.Request, response: ResetEstop.Response):
        del request
        ok, msg = self._send_reset(estop_only=True)
        if ok:
            ready_ok, _ = self._ensure_ready()
            response.success = ok
            response.message = msg + ('; READY ok' if ready_ok else '; READY pending')
            response.stm32_state = self._stm32_state
        else:
            response.success = False
            response.message = msg
            response.stm32_state = self._stm32_state
        return response

    def _run_belt_srv_cb(self, request: RunBeltCommand.Request, response: RunBeltCommand.Response):
        timeout = request.timeout_sec if request.timeout_sec > 0 else self._belt_timeout
        side = getattr(request, 'side', '') or ''
        self.get_logger().info(
            f'ROS service /run_belt_command: belt={request.belt_id}, '
            f'command={request.command}, side={side or "-"}, '
            f'timeout={timeout:.1f}s, '
            f'protocol={self._active_protocol or "chưa xác định"}')
        ok, msg = self._run_belt_sync(request.belt_id, request.command, side, timeout)
        log = self.get_logger().info if ok else self.get_logger().error
        log(f'Kết quả belt {request.belt_id}: success={ok}, message={msg}')
        response.success = ok
        response.message = msg
        return response

    def _goal_cb(self, goal_request):
        can, _ = self._can_run_conveyor()
        if not can and self._safety_state == SafetyState.ESTOP:
            return GoalResponse.REJECT
        if goal_request.belt_id not in (1, 2):
            return GoalResponse.REJECT
        if goal_request.command.lower() not in ('load', 'unload'):
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_cb(self, goal_handle):
        self.get_logger().warn(
            f'Hủy action belt {goal_handle.request.belt_id} — V4.1 không gửi STOP UART khi cancel')
        return CancelResponse.ACCEPT

    async def _execute_belt_action(self, goal_handle):
        req = goal_handle.request
        feedback = BeltLoadUnload.Feedback()
        feedback.stm32_state = STATE_RUNNING
        feedback.progress = 0.1
        feedback.status_message = 'Đang gửi lệnh UART V4.1...'
        goal_handle.publish_feedback(feedback)

        ok, msg = self._run_belt_sync(
            req.belt_id, req.command, getattr(req, 'side', '') or '',
            req.timeout_sec if req.timeout_sec > 0 else self._belt_timeout,
        )

        result = BeltLoadUnload.Result()
        result.success = ok
        result.message = msg
        result.final_state = self._stm32_state

        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
            result.success = False
            result.message = 'Action bị huỷ'
            return result

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
