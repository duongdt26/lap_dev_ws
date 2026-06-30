# amr_stm32_bridge

Cầu nối UART giữa ROS2 Humble và STM32 (băng tải, E-Stop, telemetry) — **protocol Version3**.

## Frame UART (quy ước)

- Bắt đầu: `$`
- ROS2 → STM32: **không** thêm `\n`
- STM32 → ROS2: có thể kết thúc `\r\n`
- Phân tách: `,`

### ROS2 → STM32

| Lệnh | Frame |
|------|--------|
| Hello | `$HELLO,ChuongDuong,ROS2,1.0` |
| Ping | `$PING,<seq>` |
| Load (arm) | `$CMD,START,1` |
| Unload trái | `$CMD,STOP,1,LEFT` |
| Unload phải | `$CMD,STOP,1,RIGHT` |
| Buzzer sau load | `$BUZZER,START,1` |
| Buzzer sau unload | `$BUZZER,STOP,1` |
| Reset E-Stop | `$CMD,RESET_ESTOP` |

### STM32 → ROS2

| Frame | Ý nghĩa |
|-------|---------|
| `$HELLO_ACK,STM32,OK,good job` | STM32 còn sống |
| `$PONG,<seq>` | Heartbeat |
| `$ACK,CMD,START,1` | Phát hiện hàng, bắt đầu load |
| `$ACK,CMD,STOP,1` | Load xong (hàng ở cảm biến cuối) |
| `$ACK,CMD,STOP,1,LEFT` | Unload xong |
| `$NACK,CMD,START,1,BUSY` | Từ chối lệnh |
| `$TELEMETRY,RUNNING,10000000,1,NONE` | Đang chạy |
| `$TELEMETRY,ESTOP,00000000,0,NONE,10` | E-Stop |

### Luồng load / unload

**Load belt 1:**
1. ROS2 → `$CMD,START,1`
2. STM32 → `$ACK,CMD,START,1`
3. STM32 → `$ACK,CMD,STOP,1`
4. ROS2 → `$BUZZER,START,1`

**Unload belt 1 trái:**
1. ROS2 → `$CMD,STOP,1,LEFT`
2. STM32 → `$ACK,CMD,STOP,1,LEFT`
3. ROS2 → `$BUZZER,STOP,1`

Belt 2 tương tự với id `2`.

## Chạy

```bash
cd ~/dev_ws && source install/setup.bash

# Simulate (không cần STM32)
ros2 launch amr_stm32_bridge stm32_bridge.launch.py

# UART thật — sửa config/stm32_bridge.yaml: simulate: false, port: /dev/ttyUSB0
```

## Test nhanh

```bash
# Hello
ros2 service call /stm32/hello amr_stm32_interfaces/srv/Stm32Hello "{client_name: 'ChuongDuong'}"

# Load băng tải 1
ros2 service call /run_belt_command amr_stm32_interfaces/srv/RunBeltCommand "{belt_id: 1, command: 'load', side: '', timeout_sec: 60.0}"

# Unload băng tải 1 về trái
ros2 service call /run_belt_command amr_stm32_interfaces/srv/RunBeltCommand "{belt_id: 1, command: 'unload', side: 'LEFT', timeout_sec: 60.0}"

# Xem health
ros2 topic echo /stm32/health
```

## ROS interface

| Tên | Loại |
|-----|------|
| `/stm32/hello` | Service |
| `/run_belt_command` | Service |
| `/stm32/reset_estop` | Service |
| `/belt_load_unload` | Action |
| `/stm32/health` | Topic |
| `/conveyor/belt1/status` | Topic |
| `/conveyor/belt2/status` | Topic |

Code frame: `amr_stm32_bridge/uart_protocol.py`
