#!/usr/bin/env python3
"""Đọc pin 24 V từ PZEM-017 qua Modbus RTU và publish BatteryState."""

import math
from typing import List, Optional

import minimalmodbus
import rclpy
import serial
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import BatteryState


class PzemBatteryNode(Node):
    """Đọc PZEM-017 định kỳ và phát trạng thái pin cho các node/web."""

    def __init__(self) -> None:
        super().__init__('pzem_battery_node')

        self.declare_parameter('port', '/dev/ttyUSB3')
        self.declare_parameter('slave_address', 1)
        self.declare_parameter('baudrate', 9600)
        self.declare_parameter('timeout', 0.6)
        self.declare_parameter('poll_period', 1.0)
        self.declare_parameter('empty_voltage', 21.0)
        self.declare_parameter('full_voltage', 30.0)
        self.declare_parameter('profile_name', '24V LiFePO4')
        self.declare_parameter('current_multiplier', -1.0)

        self._port = str(self.get_parameter('port').value)
        self._slave_address = int(self.get_parameter('slave_address').value)
        self._baudrate = int(self.get_parameter('baudrate').value)
        self._timeout = float(self.get_parameter('timeout').value)
        self._poll_period = max(
            0.1, float(self.get_parameter('poll_period').value))
        self._empty_voltage = float(
            self.get_parameter('empty_voltage').value)
        self._full_voltage = float(
            self.get_parameter('full_voltage').value)
        self._profile_name = str(self.get_parameter('profile_name').value)
        self._current_multiplier = float(
            self.get_parameter('current_multiplier').value)

        if self._full_voltage <= self._empty_voltage:
            raise ValueError('full_voltage phải lớn hơn empty_voltage')

        self._publisher = self.create_publisher(
            BatteryState, '/battery_state', 10)
        self._instrument: Optional[minimalmodbus.Instrument] = None
        self._failure_reported = False
        # Gọi Modbus xuống PZEM đúng 1 lần / chu kỳ (mặc định 1.0 s).
        self._timer = self.create_timer(self._poll_period, self._poll)

        self.get_logger().info(
            f'PZEM-017: port={self._port}, slave={self._slave_address}, '
            f'chu kỳ đọc={self._poll_period:.1f}s (1 lần/chu kỳ), '
            f'profile={self._profile_name}')
        # Đọc ngay lần đầu, không đợi hết chu kỳ timer.
        self._poll()

    def _connect(self) -> minimalmodbus.Instrument:
        instrument = minimalmodbus.Instrument(
            self._port, self._slave_address)
        instrument.mode = minimalmodbus.MODE_RTU
        instrument.serial.baudrate = self._baudrate
        instrument.serial.bytesize = 8
        instrument.serial.parity = serial.PARITY_NONE
        instrument.serial.stopbits = 2
        instrument.serial.timeout = self._timeout
        instrument.clear_buffers_before_each_transaction = True
        self._instrument = instrument
        return instrument

    @staticmethod
    def _decode_registers(registers: List[int]) -> dict:
        """Giải mã 8 input register của PZEM-017."""
        if len(registers) != 8:
            raise ValueError(f'PZEM trả về {len(registers)}/8 register')
        return {
            'voltage': registers[0] * 0.01,
            'current': registers[1] * 0.01,
            'power': ((registers[3] << 16) | registers[2]) * 0.1,
            'energy_wh': (registers[5] << 16) | registers[4],
            'high_alarm': registers[6] == 0xFFFF,
            'low_alarm': registers[7] == 0xFFFF,
        }

    def _estimate_percentage(self, voltage: float) -> float:
        ratio = (
            (voltage - self._empty_voltage)
            / (self._full_voltage - self._empty_voltage)
        )
        return min(1.0, max(0.0, ratio))

    def _make_message(self, data: Optional[dict] = None) -> BatteryState:
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'battery_link'
        msg.location = self._profile_name
        msg.serial_number = f'PZEM-017 slave {self._slave_address}'
        msg.design_capacity = math.nan
        msg.capacity = math.nan
        msg.charge = math.nan
        msg.temperature = math.nan

        if data is None:
            msg.voltage = math.nan
            msg.current = math.nan
            msg.percentage = math.nan
            msg.present = False
            msg.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_UNKNOWN
            msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_UNKNOWN
            msg.power_supply_technology = (
                BatteryState.POWER_SUPPLY_TECHNOLOGY_LIFE)
            return msg

        msg.voltage = float(data['voltage'])
        msg.current = float(data['current']) * self._current_multiplier
        msg.percentage = self._estimate_percentage(msg.voltage)
        msg.present = True
        msg.power_supply_status = (
            BatteryState.POWER_SUPPLY_STATUS_FULL
            if msg.percentage >= 0.995
            else BatteryState.POWER_SUPPLY_STATUS_DISCHARGING
        )
        if data['high_alarm']:
            msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_OVERVOLTAGE
        elif data['low_alarm']:
            msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_DEAD
        else:
            msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_GOOD
        msg.power_supply_technology = BatteryState.POWER_SUPPLY_TECHNOLOGY_LIFE
        return msg

    def _poll(self) -> None:
        try:
            instrument = self._instrument or self._connect()
            registers = instrument.read_registers(
                registeraddress=0x0000,
                number_of_registers=8,
                functioncode=4,
            )
            data = self._decode_registers(registers)
            msg = self._make_message(data)
            self._publisher.publish(msg)

            if self._failure_reported:
                self.get_logger().info('Đã kết nối lại với PZEM-017')
                self._failure_reported = False

            self.get_logger().info(
                f"Pin: {msg.percentage * 100.0:.1f}% | "
                f"{data['voltage']:.2f} V | "
                f"{msg.current:.2f} A | {data['power']:.1f} W")
        except Exception as exc:  # serial/Modbus có nhiều kiểu lỗi khác nhau
            if self._instrument is not None:
                try:
                    self._instrument.serial.close()
                except Exception:
                    pass
            self._instrument = None
            self._publisher.publish(self._make_message())
            if not self._failure_reported:
                self.get_logger().warning(
                    f'Chưa đọc được PZEM-017 tại {self._port}: {exc}. '
                    'Node sẽ tự thử lại.')
                self._failure_reported = True

    def destroy_node(self) -> bool:
        if self._instrument is not None:
            try:
                self._instrument.serial.close()
            except Exception:
                pass
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PzemBatteryNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
