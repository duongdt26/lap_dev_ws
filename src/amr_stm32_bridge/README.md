# amr_stm32_bridge

Cầu nối UART giữa ROS2 Humble và STM32, tương thích cả firmware
**Version3** và **AMR Conveyor Safe V4.1**.

Mặc định `protocol_mode: legacy_v3` để khớp firmware đang chạy trên xe thật.
Có thể chọn `auto` để bridge đọc `HELLO_ACK`: firmware trả `good job` sẽ dùng
Version3, còn firmware trả `AMR_CONVEYOR_SAFE_V4` sẽ dùng V4.1.

Xem spec đầy đủ: `docs/STM32_UART_PROTOCOL_V4.1.md`

## Frame chính

### ROS2 → STM32

| Lệnh | Frame |
|------|--------|
| Hello | `$HELLO` |
| Ping | `$PING,<seq>` |
| Ready | `$CMD,<seq>,READY` |
| Load | `$CMD,<seq>,START,1` |
| Unload | `$CMD,<seq>,UNLOAD,1,LEFT` |
| Reset | `$CMD,<seq>,RESET` |

### STM32 → ROS2

| Frame | Ý nghĩa |
|-------|---------|
| `$HELLO_ACK,STM32,OK,AMR_CONVEYOR_SAFE_V4` | Link OK |
| `$ACK,<seq>,CMD,START,1,ACCEPTED` | Nhận lệnh load |
| `$EVENT,<seq>,LOAD_DETECTED,1,1,3` | Phát hiện hàng |
| `$EVENT,<seq>,LOAD_DONE,1,3` | Load xong |
| `$EVENT,<seq>,UNLOAD_DONE,1,LEFT,1` | Unload xong |
| `$TELEMETRY,READY,10000100,0,NONE,0,0,LOADED,IDLE,0` | Telemetry 500ms |

## Luồng load V4.1

1. `$HELLO` → `$HELLO_ACK`
2. `$PING,<seq>` định kỳ 500ms
3. `$CMD,<seq>,READY`
4. `$CMD,<seq>,START,<belt>` → `$ACK,...,ACCEPTED`
5. `$EVENT,<seq>,LOAD_DETECTED,...`
6. `$EVENT,<seq>,LOAD_DONE,...`

## Luồng load Version3

1. `$HELLO` → `$HELLO_ACK,STM32,OK,good job`
2. Không gửi `READY`
3. `$CMD,START,<belt>` → `$ACK,CMD,START,<belt>`
4. `$ACK,CMD,STOP,<belt>` báo load xong

Với line ngang thứ nhất và lệnh `load`, frame gửi xuống STM32 là
`$CMD,START,1`.

## Chạy

```bash
cd ~/dev_ws && source install/setup.bash
ros2 launch amr_stm32_bridge stm32_bridge.launch.py
```

Config: `config/stm32_bridge.yaml` — `protocol_mode: legacy_v3`,
`ping_interval_sec: 0.5`, `pong_timeout_sec: 2.0`.

## Test

```bash
ros2 service call /stm32/hello amr_stm32_interfaces/srv/Stm32Hello "{}"
ros2 service call /run_belt_command amr_stm32_interfaces/srv/RunBeltCommand "{belt_id: 1, command: 'load', side: '', timeout_sec: 60.0}"
ros2 topic echo /stm32/health
```

## ROS interface

| Tên | Loại |
|-----|------|
| `/stm32/hello` | Service |
| `/run_belt_command` | Service |
| `/stm32/estop` | Service — `$CMD,ESTOP` / `$ACK,CMD,ESTOP` |
| `/stm32/reset_estop` | Service — `$CMD,RESET_ESTOP` / `$ACK,CMD,RESET_ESTOP` |
| `/belt_load_unload` | Action |
| `/stm32/health` | Topic |
| `/conveyor/belt1/status` | Topic |
| `/conveyor/belt2/status` | Topic |
