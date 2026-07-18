"""Pure control and Modbus helpers adapted from ``cambientu_V3.py``.

This module deliberately does not write to the motor driver.  It only reads the
two magnetic sensors and converts the original motor-RPM targets to a ROS Twist.
``ros2_control`` remains the only owner of the motor-driver serial port.
"""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


# Sensor calibration and PD values preserved from cambientu_V3.py.
FRONT_SENSOR_OFFSET_SIGN = -1.0
REAR_SENSOR_OFFSET_SIGN = -1.0
STEERING_OUTPUT_SIGN = +1.0

MIN_RUNNING_RPM = 110
MAX_RUNNING_RPM = 380
LEADING_ONLY_RPM = 240
DUAL_TRACKING_RPM = 300
TRAILING_RECOVERY_RPM = 160
NO_SENSOR_RECOVERY_RPM = 130
SEARCH_SPIN_RPM = 130
MARKER_CLEAR_RPM = 150

LEADING_ONLY_MIN_RPM = 170
DUAL_TRACKING_MIN_RPM = 180
ADAPTIVE_SPEED_FULL_RPM_ERROR_MM = 5.0
ADAPTIVE_SPEED_MIN_RPM_ERROR_MM = 30.0
HEADING_SPEED_PENALTY_RPM_PER_MM = 1.5
MAX_HEADING_SPEED_PENALTY_RPM = 60.0

KP_RPM_PER_MM = 1.50
KD_RPM_PER_MM_PER_S = 0.08
MAX_D_TERM_RPM = 12.0
MAX_CORRECTION_RPM = 70.0
ERROR_DEADBAND_MM = 1.0
ERROR_FILTER_ALPHA = 0.50
POSITION_GAIN = 1.0
HEADING_GAIN = 0.55
TRAILING_RECOVERY_GAIN = 0.65
RECOVERY_CORRECTION_DECAY = 0.78
RECOVERY_MAX_CORRECTION_RPM = 15.0

HORIZONTAL_MARKER_MIN_ACTIVE_POINTS = 9
HORIZONTAL_MARKER_MIN_SPAN_POINTS = 10
HORIZONTAL_MARKER_FALLBACK_SELECTED_POINTS = 10
HORIZONTAL_MARKER_FALLBACK_CONFIRM_SAMPLES = 2


class ModbusError(RuntimeError):
    pass


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def add_crc(data: bytes) -> bytes:
    return data + struct.pack('<H', crc16_modbus(data))


def check_crc(frame: bytes) -> None:
    if len(frame) < 3:
        raise ModbusError('Phan hoi Modbus qua ngan')
    received = struct.unpack('<H', frame[-2:])[0]
    expected = crc16_modbus(frame[:-2])
    if received != expected:
        raise ModbusError(
            f'Sai CRC: doi 0x{expected:04X}, nhan 0x{received:04X}')


def read_exact(serial_port, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = serial_port.read(count - len(data))
        if not chunk:
            raise ModbusError(f'Timeout Modbus: nhan {len(data)}/{count} byte')
        data.extend(chunk)
    return bytes(data)


def read_input_registers(
    serial_port, slave_id: int, start_address: int, count: int, bus_gap_sec: float,
) -> list[int]:
    request = add_crc(struct.pack('>BBHH', slave_id, 0x04, start_address, count))
    serial_port.reset_input_buffer()
    try:
        serial_port.write(request)
        serial_port.flush()
        header = read_exact(serial_port, 3)
        rx_slave, rx_function, third = header
        if rx_slave != slave_id:
            raise ModbusError(f'Sai slave: doi {slave_id}, nhan {rx_slave}')
        if rx_function & 0x80:
            tail = read_exact(serial_port, 2)
            check_crc(header + tail)
            raise ModbusError(
                f'Modbus exception ID{slave_id}: code=0x{third:02X}')
        if rx_function != 0x04:
            raise ModbusError(
                f'Sai function: doi 0x04, nhan 0x{rx_function:02X}')
        if third != count * 2:
            raise ModbusError(f'Sai byte count: doi {count * 2}, nhan {third}')
        body_and_crc = read_exact(serial_port, third + 2)
        frame = header + body_and_crc
        check_crc(frame)
        return list(struct.unpack(f'>{count}H', body_and_crc[:-2]))
    finally:
        time.sleep(max(0.0, bus_gap_sec))


def to_signed_16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def decode_active_point_mask(reg_1014: int, reg_1015: int) -> int:
    mask = 0
    for sensor_number in range(1, 8):
        if reg_1015 & (1 << sensor_number):
            mask |= 1 << (sensor_number - 1)
    for sensor_number in range(8, 16):
        if reg_1015 & (1 << sensor_number):
            mask |= 1 << (sensor_number - 1)
    if reg_1014 & 0x0001:
        mask |= 1 << 15
    return mask


def active_point_span(mask: int) -> int:
    if mask == 0:
        return 0
    first = (mask & -mask).bit_length() - 1
    last = mask.bit_length() - 1
    return last - first + 1


@dataclass
class SensorData:
    slave_id: int
    ok: bool
    detected: bool
    status: int = 0
    strip_state: int = 0
    offset_mm: float = 0.0
    strength: int = 0
    points: int = 0
    active_mask: int = 0
    raw_active_points: int = 0
    active_span_points: int = 0
    sampled_at: float = 0.0
    error_text: str = ''


class MagneticSensorBus:
    def __init__(
        self, port: str, baudrate: int, timeout_sec: float, bus_gap_sec: float,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout_sec = timeout_sec
        self.bus_gap_sec = bus_gap_sec
        self.serial = None

    @property
    def is_open(self) -> bool:
        return bool(self.serial and self.serial.is_open)

    def open(self) -> None:
        if self.is_open:
            return
        if not self.port:
            raise RuntimeError(
                'Chua cau hinh port cho cam bien line tu trong hardware_ports.yaml')
        import serial
        self.serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout_sec,
            write_timeout=self.timeout_sec,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def close(self) -> None:
        if self.serial is not None:
            try:
                self.serial.close()
            finally:
                self.serial = None

    def read_sensor(self, slave_id: int) -> SensorData:
        if not self.is_open:
            return SensorData(slave_id, False, False, error_text='serial closed')
        try:
            regs = read_input_registers(
                self.serial, slave_id, 1000, 16, self.bus_gap_sec)
            mask = decode_active_point_mask(regs[14], regs[15])
            points = regs[4]
            return SensorData(
                slave_id=slave_id,
                ok=True,
                detected=regs[0] == 0 and regs[1] != 0 and points > 0,
                status=regs[0],
                strip_state=regs[1],
                offset_mm=float(to_signed_16(regs[2])),
                strength=to_signed_16(regs[3]),
                points=points,
                active_mask=mask,
                raw_active_points=mask.bit_count(),
                active_span_points=active_point_span(mask),
                sampled_at=time.monotonic(),
            )
        except Exception as exc:  # serial.SerialException or ModbusError
            return SensorData(
                slave_id, False, False, sampled_at=time.monotonic(),
                error_text=str(exc))


class HorizontalMarkerDetector:
    def __init__(self, sensor_ids: tuple[int, int]) -> None:
        self.counts = {sensor_id: 0 for sensor_id in sensor_ids}

    def reset(self) -> None:
        for sensor_id in self.counts:
            self.counts[sensor_id] = 0

    def observe(self, sensor: SensorData) -> tuple[bool, str]:
        if not sensor.ok:
            self.counts[sensor.slave_id] = 0
            return False, ''
        raw_wide = (
            sensor.raw_active_points >= HORIZONTAL_MARKER_MIN_ACTIVE_POINTS
            and sensor.active_span_points >= HORIZONTAL_MARKER_MIN_SPAN_POINTS
        )
        if raw_wide:
            self.counts[sensor.slave_id] = 0
            return True, (
                f'ID{sensor.slave_id} raw-wide active={sensor.raw_active_points} '
                f'span={sensor.active_span_points} mask=0x{sensor.active_mask:04X}')
        if sensor.points >= HORIZONTAL_MARKER_FALLBACK_SELECTED_POINTS:
            self.counts[sensor.slave_id] += 1
        else:
            self.counts[sensor.slave_id] = 0
        if self.counts[sensor.slave_id] >= HORIZONTAL_MARKER_FALLBACK_CONFIRM_SAMPLES:
            return True, (
                f'ID{sensor.slave_id} selected-points={sensor.points} '
                f'confirm={self.counts[sensor.slave_id]}')
        return False, ''


class TrackingMode(Enum):
    NONE = auto()
    LEADING_ONLY = auto()
    DUAL = auto()
    TRAILING_RECOVERY = auto()


@dataclass
class TrackingMeasurement:
    control_error_mm: float
    position_error_mm: float
    heading_error_mm: float
    leading_offset_mm: float
    trailing_offset_mm: float
    mode: TrackingMode


class PDController:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.filtered_error = 0.0
        self.previous_error = 0.0
        self.previous_time: Optional[float] = None

    def prime(self, error: float, now: float) -> None:
        self.filtered_error = error
        self.previous_error = error
        self.previous_time = now

    def reset_derivative(self, now: float) -> None:
        self.previous_error = self.filtered_error
        self.previous_time = now

    def update(self, raw_error_mm: float, now: float) -> float:
        error = 0.0 if abs(raw_error_mm) <= ERROR_DEADBAND_MM else raw_error_mm
        self.filtered_error = (
            ERROR_FILTER_ALPHA * error
            + (1.0 - ERROR_FILTER_ALPHA) * self.filtered_error)
        dt = max(now - self.previous_time, 1e-3) if self.previous_time else 0.0
        derivative = (
            (self.filtered_error - self.previous_error) / dt if dt > 0 else 0.0)
        p_term = KP_RPM_PER_MM * self.filtered_error
        d_term = max(
            -MAX_D_TERM_RPM,
            min(MAX_D_TERM_RPM, KD_RPM_PER_MM_PER_S * derivative))
        correction = max(
            -MAX_CORRECTION_RPM,
            min(MAX_CORRECTION_RPM, p_term + d_term))
        self.previous_error = self.filtered_error
        self.previous_time = now
        return correction


def compute_tracking_measurement(
    front: SensorData, rear: SensorData, dual_enabled: bool,
) -> TrackingMeasurement:
    front_offset = FRONT_SENSOR_OFFSET_SIGN * front.offset_mm
    rear_offset = REAR_SENSOR_OFFSET_SIGN * rear.offset_mm
    if front.detected and rear.detected and dual_enabled:
        position = (front_offset + rear_offset) / 2.0
        heading = front_offset - rear_offset
        return TrackingMeasurement(
            POSITION_GAIN * position + HEADING_GAIN * heading,
            position, heading, front_offset, rear_offset, TrackingMode.DUAL)
    if front.detected:
        return TrackingMeasurement(
            front_offset, front_offset, 0.0, front_offset, rear_offset,
            TrackingMode.LEADING_ONLY)
    if rear.detected:
        error = -TRAILING_RECOVERY_GAIN * rear_offset
        return TrackingMeasurement(
            error, rear_offset, 0.0, front_offset, rear_offset,
            TrackingMode.TRAILING_RECOVERY)
    return TrackingMeasurement(
        0.0, 0.0, 0.0, front_offset, rear_offset, TrackingMode.NONE)


def adaptive_base_rpm(measurement: TrackingMeasurement) -> float:
    if measurement.mode is TrackingMode.LEADING_ONLY:
        max_rpm, min_rpm = float(LEADING_ONLY_RPM), float(LEADING_ONLY_MIN_RPM)
    elif measurement.mode is TrackingMode.DUAL:
        max_rpm, min_rpm = float(DUAL_TRACKING_RPM), float(DUAL_TRACKING_MIN_RPM)
    elif measurement.mode is TrackingMode.TRAILING_RECOVERY:
        return float(TRAILING_RECOVERY_RPM)
    else:
        return float(NO_SENSOR_RECOVERY_RPM)
    error = abs(measurement.control_error_mm)
    low, high = ADAPTIVE_SPEED_FULL_RPM_ERROR_MM, ADAPTIVE_SPEED_MIN_RPM_ERROR_MM
    if error <= low:
        base = max_rpm
    elif error >= high:
        base = min_rpm
    else:
        ratio = (error - low) / (high - low)
        base = max_rpm - ratio * (max_rpm - min_rpm)
    if measurement.mode is TrackingMode.DUAL:
        base -= min(
            MAX_HEADING_SPEED_PENALTY_RPM,
            HEADING_SPEED_PENALTY_RPM_PER_MM * abs(measurement.heading_error_mm))
    return max(min_rpm, min(max_rpm, base))


def correction_limit_for_base(base_rpm: float) -> float:
    return max(0.0, min(
        MAX_CORRECTION_RPM,
        base_rpm - MIN_RUNNING_RPM,
        MAX_RUNNING_RPM - base_rpm))


def wheel_rpms(base_rpm: float, correction_rpm: float) -> tuple[int, int, float]:
    limit = correction_limit_for_base(base_rpm)
    correction = max(-limit, min(limit, correction_rpm))
    return (
        int(round(base_rpm + correction)),
        int(round(base_rpm - correction)),
        correction,
    )


def compute_pd_wheel_command(
    controller: PDController, measurement: TrackingMeasurement, now: float,
) -> tuple[int, int, float]:
    requested = STEERING_OUTPUT_SIGN * controller.update(
        measurement.control_error_mm, now)
    return wheel_rpms(adaptive_base_rpm(measurement), requested)


def compute_home_tracking_measurement(rear: SensorData) -> TrackingMeasurement:
    """Sai số Home khi cảm biến sau là cảm biến dẫn hướng duy nhất."""
    rear_offset = REAR_SENSOR_OFFSET_SIGN * rear.offset_mm
    if rear.detected:
        return TrackingMeasurement(
            rear_offset, rear_offset, 0.0, rear_offset, rear_offset,
            TrackingMode.LEADING_ONLY)
    return TrackingMeasurement(
        0.0, 0.0, 0.0, rear_offset, rear_offset, TrackingMode.NONE)


def reverse_wheel_rpms(
    base_rpm: float, correction_rpm: float,
) -> tuple[int, int, float]:
    """RPM chạy lùi; correction dương bẻ đuôi xe về phía trái."""
    limit = correction_limit_for_base(base_rpm)
    correction = max(-limit, min(limit, correction_rpm))
    return (
        int(round(-base_rpm + correction)),
        int(round(-base_rpm - correction)),
        correction,
    )


def compute_home_reverse_wheel_command(
    controller: PDController, measurement: TrackingMeasurement, now: float,
) -> tuple[int, int, float]:
    requested = STEERING_OUTPUT_SIGN * controller.update(
        measurement.control_error_mm, now)
    return reverse_wheel_rpms(adaptive_base_rpm(measurement), requested)


def compute_no_sensor_recovery_command(
    last_correction_rpm: float,
) -> tuple[int, int, float]:
    correction = max(
        -RECOVERY_MAX_CORRECTION_RPM,
        min(RECOVERY_MAX_CORRECTION_RPM,
            RECOVERY_CORRECTION_DECAY * last_correction_rpm))
    return wheel_rpms(NO_SENSOR_RECOVERY_RPM, correction)


def compute_home_reverse_recovery_command(
    last_correction_rpm: float,
) -> tuple[int, int, float]:
    correction = max(
        -RECOVERY_MAX_CORRECTION_RPM,
        min(RECOVERY_MAX_CORRECTION_RPM,
            RECOVERY_CORRECTION_DECAY * last_correction_rpm))
    return reverse_wheel_rpms(NO_SENSOR_RECOVERY_RPM, correction)


def motor_rpms_to_twist(
    left_motor_rpm: float,
    right_motor_rpm: float,
    gear_ratio: float,
    wheel_radius_m: float,
    wheel_separation_m: float,
) -> tuple[float, float]:
    left_rad_s = left_motor_rpm * 2.0 * math.pi / (60.0 * gear_ratio)
    right_rad_s = right_motor_rpm * 2.0 * math.pi / (60.0 * gear_ratio)
    left_mps = left_rad_s * wheel_radius_m
    right_mps = right_rad_s * wheel_radius_m
    linear = (left_mps + right_mps) / 2.0
    angular = (right_mps - left_mps) / wheel_separation_m
    return linear, angular


def belt_command_at_marker(
    marker_index: int, belt1_command: str, belt2_command: str,
) -> Optional[tuple[int, str]]:
    """Marker 1 chay BT1, marker 2 chay BT2; ``none`` thi bo qua marker."""
    commands = {1: belt1_command, 2: belt2_command}
    command = commands.get(marker_index)
    if command in ('load', 'unload'):
        return marker_index, command
    return None


def normalize_angle_rad(angle: float) -> float:
    """Chuan hoa goc ve [-pi, pi] de luon lay chieu xoay ngan nhat."""
    return math.atan2(math.sin(angle), math.cos(angle))


@dataclass(frozen=True)
class PoseErrors:
    yaw_error_rad: float
    forward_error_m: float
    lateral_error_m: float


def compute_pose_errors(
    target_x: float,
    target_y: float,
    target_yaw_rad: float,
    actual_x: float,
    actual_y: float,
    actual_yaw_rad: float,
) -> PoseErrors:
    """Sai so robot so voi truc di vao tram cua Approach Pose.

    lateral > 0: robot nam ben trai truc tram, line du kien o ben phai.
    lateral < 0: robot nam ben phai truc tram, line du kien o ben trai.
    """
    dx = actual_x - target_x
    dy = actual_y - target_y
    cos_yaw = math.cos(target_yaw_rad)
    sin_yaw = math.sin(target_yaw_rad)
    return PoseErrors(
        yaw_error_rad=normalize_angle_rad(target_yaw_rad - actual_yaw_rad),
        forward_error_m=cos_yaw * dx + sin_yaw * dy,
        lateral_error_m=-sin_yaw * dx + cos_yaw * dy,
    )


def choose_sweep_direction(
    yaw_error_rad: float,
    lateral_error_m: float,
    yaw_deadband_rad: float,
    lateral_deadband_m: float,
) -> int:
    """Tra +1 de quet trai, -1 de quet phai.

    ALIGN se tu xu ly sai so yaw truoc. Vi vay phia quet sau ALIGN uu tien sai
    so ngang. Neu x/y gan nhu khong lech, giu chieu yaw ngan nhat; neu ca hai
    deu rat nho thi mac dinh quet trai.
    """
    if lateral_error_m > lateral_deadband_m:
        return -1
    if lateral_error_m < -lateral_deadband_m:
        return +1
    if abs(yaw_error_rad) > yaw_deadband_rad:
        return +1 if yaw_error_rad > 0.0 else -1
    return +1


def reached_sweep_limit(
    relative_yaw_rad: float,
    direction: int,
    max_search_yaw_rad: float,
) -> bool:
    """Kiem tra da cham bien trai (+1) hoac bien phai (-1) hay chua."""
    if direction > 0:
        return relative_yaw_rad >= max_search_yaw_rad
    return relative_yaw_rad <= -max_search_yaw_rad
