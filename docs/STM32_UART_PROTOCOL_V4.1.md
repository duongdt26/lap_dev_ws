# STM32 ↔ ROS2 UART Protocol — AMR Conveyor Safe V4.1

Tài liệu tham chiếu triển khai trong repo:
- ROS2: `src/amr_stm32_bridge/amr_stm32_bridge/uart_protocol.py`
- Bridge node: `src/amr_stm32_bridge/amr_stm32_bridge/stm32_conveyor_bridge_node.py`
- STM32: `test_mach_Version3/MDK-ARM/uart_proto.c`, `belt_fsm.c`

## UART

```text
Baudrate: 256000, 8N1, ASCII, frame kết thúc \r\n hoặc \n
```

## ROS2 → STM32

| Lệnh | Frame |
|------|--------|
| Handshake | `$HELLO` |
| Heartbeat | `$PING,<seq>` |
| Ready | `$CMD,<seq>,READY` hoặc `ENABLE` |
| Reset | `$CMD,<seq>,RESET` hoặc `RESET_ESTOP` |
| Nhận hàng | `$CMD,<seq>,START,<belt_id>` |
| Trả hàng | `$CMD,<seq>,UNLOAD,<belt_id>,LEFT\|RIGHT` |
| Buzzer | `$BUZZER,START,<belt>` / `$BUZZER,STOP,<belt>` |

## STM32 → ROS2

| Frame | Ý nghĩa |
|-------|---------|
| `$HELLO_ACK,STM32,OK,AMR_CONVEYOR_SAFE_V4` | Link OK |
| `$PONG,<seq>` | Heartbeat reply |
| `$ACK,<seq>,CMD,START,<belt>,ACCEPTED` | Nhận lệnh load |
| `$EVENT,<seq>,LOAD_DETECTED,<belt>,<src>,<tgt>` | Phát hiện hàng |
| `$EVENT,<seq>,LOAD_DONE,<belt>,<cargo_sensor>` | Load xong |
| `$ACK,<seq>,CMD,STOP,<belt>,<side>,ACCEPTED` | Nhận lệnh unload |
| `$EVENT,<seq>,UNLOAD_DONE,<belt>,<side>,<exit>` | Unload xong |
| `$TELEMETRY,<state>,<bits>,<belt>,NONE,<estop>,<fault>,<b1>,<b2>,<stop_lock>` | 500ms |
| `$EVENT,ESTOP,<code>,TRIGGER` | Emergency/bumper |
| `$EVENT,STOP_LOCK,TRIGGER\|CLEAR` | Stop vật lý |
| `$EVENT,COMM_LOST` | Mất heartbeat >2s |

## Workflow load

1. HELLO + PING → ONLINE
2. `$CMD,<seq>,READY`
3. `$CMD,<seq>,START,<belt>` → ACK ACCEPTED
4. EVENT LOAD_DETECTED → EVENT LOAD_DONE
5. Nav2 tiếp tục mission

## Workflow unload

1. Xác nhận belt LOADED / Cx=1
2. `$CMD,<seq>,UNLOAD,<belt>,LEFT|RIGHT` → ACK ACCEPTED
3. EVENT UNLOAD_DONE

## Safety priority

```text
Emergency/Bumper > Stop Lock > Fault/Comm Lost > Ready > conveyor command
```

Nút START vật lý chỉ READY / mở STOP_LOCK — **không tự chạy băng tải**.
