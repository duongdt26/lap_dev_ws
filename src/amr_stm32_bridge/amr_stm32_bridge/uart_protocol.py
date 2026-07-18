"""
uart_protocol.py — Frame UART ROS2 ↔ STM32 (Version3 và Safe V4.1).

Quy ước:
  - Bắt đầu bằng '$', field phân tách bằng ','
  - ROS2 → STM32: kết thúc \\r\\n ở tầng gửi serial
  - STM32 → ROS2: \\r\\n hoặc \\n
  - Lệnh production: $CMD,<seq>,...

ROS2 → STM32:
  $HELLO
  $PING,<seq>
  $CMD,<seq>,READY | ENABLE | RESET | RESET_ESTOP | START,<belt> | STOP,<belt>,LEFT|RIGHT | UNLOAD,<belt>,LEFT|RIGHT
  $BUZZER,START,<belt> | $BUZZER,STOP,<belt>

STM32 → ROS2:
  $HELLO_ACK,STM32,OK,AMR_CONVEYOR_SAFE_V4
  $PONG,<seq>
  $ACK,<seq>,CMD,...
  $NACK,<seq>,CMD,...
  $TELEMETRY,<state>,<bits>,<active_belt>,NONE,<estop>,<fault>,<belt1>,<belt2>,<stop_locked>
  $EVENT,...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


PROTOCOL_VERSION = 'AMR_CONVEYOR_SAFE_V4'

MSG_HELLO = 'HELLO'
MSG_HELLO_ACK = 'HELLO_ACK'
MSG_CMD = 'CMD'
MSG_ACK = 'ACK'
MSG_NACK = 'NACK'
MSG_TELEMETRY = 'TELEMETRY'
MSG_EVENT = 'EVENT'
MSG_PING = 'PING'
MSG_PONG = 'PONG'
MSG_BUZZER = 'BUZZER'

CMD_START = 'START'
CMD_STOP = 'STOP'
CMD_UNLOAD = 'UNLOAD'
CMD_READY = 'READY'
CMD_ENABLE = 'ENABLE'
CMD_RESET = 'RESET'
CMD_RESET_ESTOP = 'RESET_ESTOP'

SIDE_LEFT = 'LEFT'
SIDE_RIGHT = 'RIGHT'
ACCEPTED = 'ACCEPTED'

STATE_IDLE = 'IDLE'
STATE_READY = 'READY'
STATE_RUNNING = 'RUNNING'
STATE_STOP_LOCK = 'STOP_LOCK'
STATE_ESTOP = 'ESTOP'
STATE_FAULT = 'FAULT'
STATE_COMM_LOST = 'COMM_LOST'
STATE_BOOT = 'BOOT'

BELT_STATE_IDLE = 'IDLE'
BELT_STATE_LOAD_ARMED = 'LOAD_ARMED'
BELT_STATE_LOADING = 'LOADING'
BELT_STATE_LOADED = 'LOADED'
BELT_STATE_UNLOADING = 'UNLOADING'
BELT_STATE_FAULT = 'FAULT'

NACK_REASONS = {
    'BUSY', 'ESTOP', 'INVALID', 'NO_CARGO', 'STOP_LOCK', 'FAULT', 'COMM_LOST',
    'NOT_READY', 'BAD_FORMAT', 'BAD_SIDE', 'NOTHING_TO_RESET', 'TOO_LONG',
}


def frame(*fields: str) -> str:
    return '$' + ','.join(str(f) for f in fields)


def normalize_side(side: str) -> str:
    s = (side or '').strip().upper()
    return SIDE_RIGHT if s == SIDE_RIGHT else SIDE_LEFT


# ── ROS2 → STM32 builders ────────────────────────────────────────────────────

def cmd_hello() -> str:
    return frame(MSG_HELLO)


def cmd_ping(seq: int) -> str:
    return frame(MSG_PING, str(seq))


def cmd_ready(seq: int) -> str:
    return frame(MSG_CMD, str(seq), CMD_READY)


def cmd_enable(seq: int) -> str:
    return frame(MSG_CMD, str(seq), CMD_ENABLE)


def cmd_reset(seq: int) -> str:
    return frame(MSG_CMD, str(seq), CMD_RESET)


def cmd_reset_estop(seq: int) -> str:
    return frame(MSG_CMD, str(seq), CMD_RESET_ESTOP)


def cmd_start_load(seq: int, belt_id: int) -> str:
    return frame(MSG_CMD, str(seq), CMD_START, str(belt_id))


def cmd_start_load_legacy(belt_id: int) -> str:
    """Protocol V3 dang chay tren STM32: khong co sequence trong CMD."""
    return frame(MSG_CMD, CMD_START, str(belt_id))


def cmd_unload_belt(seq: int, belt_id: int, side: str) -> str:
    side_norm = normalize_side(side)
    return frame(MSG_CMD, str(seq), CMD_UNLOAD, str(belt_id), side_norm)


def cmd_unload_belt_legacy(belt_id: int, side: str) -> str:
    """Protocol V3 dung STOP de tra hang."""
    return frame(MSG_CMD, CMD_STOP, str(belt_id), normalize_side(side))


def cmd_reset_estop_legacy() -> str:
    return frame(MSG_CMD, CMD_RESET_ESTOP)


def cmd_reset_legacy() -> str:
    return frame(MSG_CMD, CMD_RESET)


def cmd_buzzer_start(belt_id: int) -> str:
    return frame(MSG_BUZZER, CMD_START, str(belt_id))


def cmd_buzzer_stop(belt_id: int) -> str:
    return frame(MSG_BUZZER, CMD_STOP, str(belt_id))


# ── Parsed structures ────────────────────────────────────────────────────────

@dataclass
class TelemetryFrame:
    state: str
    status_bits: str
    active_belt: int
    direction: str
    estop_source: int = 0
    fault_code: int = 0
    belt1_state: str = BELT_STATE_IDLE
    belt2_state: str = BELT_STATE_IDLE
    stop_locked: int = 0

    @property
    def belt1_has_cargo(self) -> bool:
        return len(self.status_bits) >= 1 and self.status_bits[0] == '1'

    @property
    def belt2_has_cargo(self) -> bool:
        return len(self.status_bits) >= 2 and self.status_bits[1] == '1'

    @property
    def is_estop(self) -> bool:
        return self.state == STATE_ESTOP

    @property
    def is_stop_lock(self) -> bool:
        return self.state == STATE_STOP_LOCK or self.stop_locked == 1

    @property
    def is_fault(self) -> bool:
        return self.state == STATE_FAULT

    @property
    def is_comm_lost(self) -> bool:
        return self.state == STATE_COMM_LOST

    @property
    def is_ready(self) -> bool:
        return self.state == STATE_READY

    def belt_is_active(self, belt_id: int) -> bool:
        bit = 1 if belt_id == 1 else 2
        return (self.active_belt & bit) != 0


@dataclass
class ParsedFrame:
    msg_type: str
    fields: list[str]
    raw: str


@dataclass
class AckFrame:
    seq: int
    cmd: str
    belt_id: int = 0
    side: Optional[str] = None
    status: str = ''
    extra: list[str] = field(default_factory=list)


@dataclass
class NackFrame:
    seq: int
    cmd: str
    belt_id: int = 0
    reason: str = 'UNKNOWN'


@dataclass
class EventFrame:
    seq: int = 0
    event: str = ''
    fields: list[str] = field(default_factory=list)


def parse_line(line: str) -> Optional[ParsedFrame]:
    line = line.strip()
    if not line.startswith('$'):
        return None
    fields = line[1:].split(',')
    if not fields:
        return None
    return ParsedFrame(msg_type=fields[0], fields=fields, raw=line)


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_telemetry(parsed: ParsedFrame) -> Optional[TelemetryFrame]:
    if parsed.msg_type != MSG_TELEMETRY or len(parsed.fields) < 5:
        return None
    f = parsed.fields
    return TelemetryFrame(
        state=f[1],
        status_bits=f[2],
        active_belt=_parse_int(f[3]),
        direction=f[4],
        estop_source=_parse_int(f[5]) if len(f) >= 6 else 0,
        fault_code=_parse_int(f[6]) if len(f) >= 7 else 0,
        belt1_state=f[7] if len(f) >= 8 else BELT_STATE_IDLE,
        belt2_state=f[8] if len(f) >= 9 else BELT_STATE_IDLE,
        stop_locked=_parse_int(f[9]) if len(f) >= 10 else 0,
    )


def parse_hello_ack(parsed: ParsedFrame) -> Optional[str]:
    if parsed.msg_type != MSG_HELLO_ACK or len(parsed.fields) < 4:
        return None
    return parsed.fields[3]


def parse_pong_seq(parsed: ParsedFrame) -> Optional[int]:
    if parsed.msg_type != MSG_PONG or len(parsed.fields) < 2:
        return None
    return _parse_int(parsed.fields[1], -1)


def parse_ack(parsed: ParsedFrame) -> Optional[AckFrame]:
    """
    $ACK,CMD,START,<belt>                 (Version3: bắt đầu load)
    $ACK,CMD,STOP,<belt>                  (Version3: load xong)
    $ACK,CMD,STOP,<belt>,LEFT|RIGHT       (Version3: unload xong)
    $ACK,<seq>,CMD,START,<belt>,ACCEPTED
    $ACK,<seq>,CMD,STOP,<belt>,LEFT,ACCEPTED
    $ACK,<seq>,CMD,READY
    $ACK,<seq>,CMD,RESET,<WHAT>
    """
    if parsed.msg_type != MSG_ACK or len(parsed.fields) < 3:
        return None

    # V4.1: $ACK,<seq>,CMD,...
    # V3:   $ACK,CMD,...
    if len(parsed.fields) >= 4 and parsed.fields[2] == MSG_CMD:
        seq = _parse_int(parsed.fields[1])
        cmd_index = 3
    elif parsed.fields[1] == MSG_CMD:
        seq = 0
        cmd_index = 2
    else:
        return None

    cmd = parsed.fields[cmd_index]
    belt_id = 0
    side = None
    status = ''
    extra: list[str] = []

    if cmd in (CMD_START, CMD_STOP, CMD_UNLOAD) and len(parsed.fields) > cmd_index + 1:
        belt_id = _parse_int(parsed.fields[cmd_index + 1])
        if len(parsed.fields) > cmd_index + 2:
            tail = parsed.fields[cmd_index + 2:]
            if tail and tail[-1] == ACCEPTED:
                status = ACCEPTED
                tail = tail[:-1]
            if cmd in (CMD_STOP, CMD_UNLOAD) and tail:
                side = normalize_side(tail[0])
                extra = tail[1:]
            else:
                extra = tail
        # ACK START cua V3 co nghia lenh load da duoc nhan.
        if seq == 0 and cmd == CMD_START:
            status = ACCEPTED
    elif cmd in (CMD_RESET, CMD_RESET_ESTOP) and len(parsed.fields) > cmd_index + 1:
        extra = parsed.fields[cmd_index + 1:]
    elif cmd in (CMD_READY, CMD_ENABLE):
        status = ACCEPTED

    return AckFrame(seq=seq, cmd=cmd, belt_id=belt_id, side=side, status=status, extra=extra)


def parse_nack(parsed: ParsedFrame) -> Optional[NackFrame]:
    """Parse NACK của cả Version3 và Safe V4.1."""
    if parsed.msg_type != MSG_NACK or len(parsed.fields) < 4:
        return None

    # V4.1: $NACK,<seq>,CMD,...
    # V3:   $NACK,CMD,...
    if len(parsed.fields) >= 5 and parsed.fields[2] == MSG_CMD:
        seq = _parse_int(parsed.fields[1])
        cmd_index = 3
    elif parsed.fields[1] == MSG_CMD:
        seq = 0
        cmd_index = 2
    else:
        return None

    cmd = parsed.fields[cmd_index]
    belt_id = 0
    reason = 'UNKNOWN'

    if len(parsed.fields) > cmd_index + 1:
        if cmd in (CMD_START, CMD_STOP, CMD_UNLOAD):
            belt_id = _parse_int(parsed.fields[cmd_index + 1])
            reason = (
                parsed.fields[cmd_index + 2]
                if len(parsed.fields) > cmd_index + 2 else 'UNKNOWN')
        else:
            reason = parsed.fields[cmd_index + 1]

    return NackFrame(seq=seq, cmd=cmd, belt_id=belt_id, reason=reason)


def parse_event(parsed: ParsedFrame) -> Optional[EventFrame]:
    """
    $EVENT,READY
    $EVENT,STOP_LOCK,TRIGGER
    $EVENT,<seq>,LOAD_DETECTED,<belt>,<source>,<target>
    $EVENT,<seq>,LOAD_DONE,<belt>,<cargo_sensor>
    $EVENT,<seq>,UNLOAD_DONE,<belt>,<side>,<exit_sensor>
    $EVENT,<seq>,FAULT,<fault_name>,<belt>
    $EVENT,ESTOP,10,TRIGGER
    """
    if parsed.msg_type != MSG_EVENT or len(parsed.fields) < 2:
        return None

    f = parsed.fields
    first = f[1]

    if first.isdigit():
        seq = _parse_int(first)
        event = f[2] if len(f) >= 3 else ''
        return EventFrame(seq=seq, event=event, fields=f[3:])

    return EventFrame(seq=0, event=first, fields=f[2:])


def event_matches_load_detected(ev: EventFrame, seq: int, belt_id: int) -> bool:
    return ev.event == 'LOAD_DETECTED' and ev.seq == seq and _parse_int(ev.fields[0]) == belt_id


def event_matches_load_done(ev: EventFrame, seq: int, belt_id: int) -> bool:
    return ev.event == 'LOAD_DONE' and ev.seq == seq and _parse_int(ev.fields[0]) == belt_id


def event_matches_unload_done(ev: EventFrame, seq: int, belt_id: int, side: str) -> bool:
    if ev.event != 'UNLOAD_DONE' or ev.seq != seq:
        return False
    if _parse_int(ev.fields[0]) != belt_id:
        return False
    if not ev.fields:
        return True
    return normalize_side(ev.fields[1]) == normalize_side(side)


def ack_matches_accepted(ack: AckFrame, seq: int, cmd: str, belt_id: int = 0) -> bool:
    if ack.seq != seq or ack.cmd != cmd:
        return False
    if belt_id and ack.belt_id != belt_id:
        return False
    return ack.status == ACCEPTED or cmd in (CMD_READY, CMD_ENABLE, CMD_RESET, CMD_RESET_ESTOP)
