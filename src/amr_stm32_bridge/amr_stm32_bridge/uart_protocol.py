"""
uart_protocol.py — Frame UART giữa ROS2 và STM32 (protocol Version3).

Quy ước:
  - Bắt đầu bằng '$'
  - ROS2 → STM32: không thêm \\n (gửi raw frame)
  - STM32 → ROS2: có thể kết thúc bằng \\r\\n (readline vẫn đọc được)
  - Phân tách field bằng dấu phẩy ','

ROS2 → STM32:
  $HELLO,ChuongDuong,ROS2,1.0
  $CMD,START,1
  $CMD,STOP,1,LEFT
  $BUZZER,START,1
  $BUZZER,STOP,1
  $CMD,RESET_ESTOP
  $PING,42

STM32 → ROS2:
  $HELLO_ACK,STM32,OK,good job
  $ACK,CMD,START,1
  $ACK,CMD,STOP,1
  $ACK,CMD,STOP,1,LEFT
  $NACK,CMD,START,1,BUSY
  $TELEMETRY,RUNNING,10000000,1,NONE
  $PONG,42
  $EVENT,BUMPER,1,TRIGGER
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Loại bản tin ──────────────────────────────────────────────────────────
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

# ── Lệnh CMD ───────────────────────────────────────────────────────────────
CMD_START = 'START'
CMD_STOP = 'STOP'
CMD_RESET_ESTOP = 'RESET_ESTOP'

SIDE_LEFT = 'LEFT'
SIDE_RIGHT = 'RIGHT'

# ── Trạng thái STM32 ──────────────────────────────────────────────────────
STATE_IDLE = 'IDLE'
STATE_RUNNING = 'RUNNING'
STATE_ESTOP = 'ESTOP'
STATE_BOOT = 'BOOT'


def frame(*fields: str) -> str:
    """Tạo frame UART gửi xuống STM32: $field1,field2,... (không có \\n)."""
    return '$' + ','.join(str(f) for f in fields)


def normalize_side(side: str) -> str:
    """Chuẩn hoá LEFT/RIGHT; mặc định LEFT nếu không hợp lệ."""
    s = (side or '').strip().upper()
    if s == SIDE_RIGHT:
        return SIDE_RIGHT
    return SIDE_LEFT


# ── ROS2 → STM32: builders ─────────────────────────────────────────────────

def cmd_hello(client_name: str = 'ChuongDuong', source: str = 'ROS2', version: str = '1.0') -> str:
    return frame(MSG_HELLO, client_name, source, version)


def cmd_ping(seq: int) -> str:
    return frame(MSG_PING, str(seq))


def cmd_start_load(belt_id: int) -> str:
    """$CMD,START,<belt_id> — arm/load băng tải."""
    return frame(MSG_CMD, CMD_START, str(belt_id))


def cmd_unload_belt(belt_id: int, side: str) -> str:
    """$CMD,STOP,<belt_id>,LEFT|RIGHT — trả hàng."""
    return frame(MSG_CMD, CMD_STOP, str(belt_id), normalize_side(side))


def cmd_buzzer_start(belt_id: int) -> str:
    """$BUZZER,START,<belt_id> — sau $ACK,CMD,STOP,<id> (load xong)."""
    return frame(MSG_BUZZER, CMD_START, str(belt_id))


def cmd_buzzer_stop(belt_id: int) -> str:
    """$BUZZER,STOP,<belt_id> — sau $ACK,CMD,STOP,<id>,LEFT|RIGHT."""
    return frame(MSG_BUZZER, CMD_STOP, str(belt_id))


def cmd_reset_estop() -> str:
    return frame(MSG_CMD, CMD_RESET_ESTOP)


# ── STM32 → ROS2: parsed structures ───────────────────────────────────────

@dataclass
class TelemetryFrame:
    state: str
    status_bits: str
    active_belt: int
    direction: str
    estop_source: int = 0

    @property
    def belt1_has_cargo(self) -> bool:
        return len(self.status_bits) >= 1 and self.status_bits[0] == '1'

    @property
    def belt2_has_cargo(self) -> bool:
        return len(self.status_bits) >= 2 and self.status_bits[1] == '1'

    @property
    def is_estop(self) -> bool:
        return self.state == STATE_ESTOP

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
    kind: str          # 'load_started' | 'load_done' | 'unload_done' | 'reset_estop' | 'other'
    belt_id: int
    side: Optional[str] = None


def parse_line(line: str) -> Optional[ParsedFrame]:
    line = line.strip()
    if not line.startswith('$'):
        return None
    body = line[1:]
    fields = body.split(',')
    if not fields:
        return None
    return ParsedFrame(msg_type=fields[0], fields=fields, raw=line)


def parse_telemetry(parsed: ParsedFrame) -> Optional[TelemetryFrame]:
    """Parse $TELEMETRY,<state>,<8bit>,<active_belt>,NONE[,estop_source]"""
    if parsed.msg_type != MSG_TELEMETRY or len(parsed.fields) < 5:
        return None
    estop_source = 0
    if len(parsed.fields) >= 6:
        try:
            estop_source = int(parsed.fields[5])
        except ValueError:
            estop_source = 0
    try:
        active_belt = int(parsed.fields[3])
    except ValueError:
        active_belt = 0
    return TelemetryFrame(
        state=parsed.fields[1],
        status_bits=parsed.fields[2],
        active_belt=active_belt,
        direction=parsed.fields[4],
        estop_source=estop_source,
    )


def parse_hello_ack(parsed: ParsedFrame) -> Optional[str]:
    if parsed.msg_type != MSG_HELLO_ACK or len(parsed.fields) < 4:
        return None
    return parsed.fields[3]


def parse_pong_seq(parsed: ParsedFrame) -> Optional[int]:
    if parsed.msg_type != MSG_PONG or len(parsed.fields) < 2:
        return None
    try:
        return int(parsed.fields[1])
    except ValueError:
        return None


def parse_nack(parsed: ParsedFrame) -> Optional[tuple[str, int, str]]:
    """Trả (cmd, belt_id, reason) từ $NACK,CMD,START,1,BUSY"""
    if parsed.msg_type != MSG_NACK or len(parsed.fields) < 4:
        return None
    if parsed.fields[1] != MSG_CMD:
        return None
    cmd = parsed.fields[2]
    belt_id = 0
    reason_idx = 3
    if len(parsed.fields) >= 5:
        try:
            belt_id = int(parsed.fields[3])
            reason_idx = 4
        except ValueError:
            belt_id = 0
    reason = parsed.fields[reason_idx] if reason_idx < len(parsed.fields) else 'UNKNOWN'
    return cmd, belt_id, reason


def parse_ack(parsed: ParsedFrame) -> Optional[AckFrame]:
    """
    Parse ACK từ STM32:
      $ACK,CMD,START,<belt_id>
      $ACK,CMD,STOP,<belt_id>           — load xong
      $ACK,CMD,STOP,<belt_id>,LEFT|RIGHT — unload xong
      $ACK,CMD,RESET_ESTOP
    """
    if parsed.msg_type != MSG_ACK or len(parsed.fields) < 3:
        return None
    if parsed.fields[1] != MSG_CMD:
        return None

    sub = parsed.fields[2]
    if sub == CMD_RESET_ESTOP:
        return AckFrame(kind='reset_estop', belt_id=0)

    if len(parsed.fields) < 4:
        return None

    try:
        belt_id = int(parsed.fields[3])
    except ValueError:
        return None

    if sub == CMD_START:
        return AckFrame(kind='load_started', belt_id=belt_id)

    if sub == CMD_STOP:
        if len(parsed.fields) >= 5:
            side = normalize_side(parsed.fields[4])
            return AckFrame(kind='unload_done', belt_id=belt_id, side=side)
        return AckFrame(kind='load_done', belt_id=belt_id)

    return AckFrame(kind='other', belt_id=belt_id)


def ack_matches_load_started(line: str, belt_id: int) -> bool:
    parsed = parse_line(line)
    if parsed is None:
        return False
    ack = parse_ack(parsed)
    return ack is not None and ack.kind == 'load_started' and ack.belt_id == belt_id


def ack_matches_load_done(line: str, belt_id: int) -> bool:
    parsed = parse_line(line)
    if parsed is None:
        return False
    ack = parse_ack(parsed)
    return ack is not None and ack.kind == 'load_done' and ack.belt_id == belt_id


def ack_matches_unload_done(line: str, belt_id: int, side: str) -> bool:
    parsed = parse_line(line)
    if parsed is None:
        return False
    ack = parse_ack(parsed)
    expected = normalize_side(side)
    return (
        ack is not None
        and ack.kind == 'unload_done'
        and ack.belt_id == belt_id
        and ack.side == expected
    )
