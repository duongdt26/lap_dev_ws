# AMR Magnetic Line Follower

Node này tiếp quản chuyển động sau khi Nav2 đã tới `Approach Pose`.

## Luồng hoạt động

1. Web chờ Nav2 báo goal thành công.
2. Web gửi yêu cầu tới `/magnetic_line/command`; BT1 và BT2 đều bắt buộc chọn
   `Load` hoặc `Unload`.
3. Node xuất vận tốc 0 trong 0,5 giây và chụp pose thật từ TF
   `map -> base_footprint`.
4. Node xoay theo đường ngắn nhất về yaw setpoint. Trong lúc xoay, ID83 luôn
   tìm line.
5. Nếu chưa có line, node quét hai phía trong giới hạn
   `yaw_setpoint ±90°`; không xoay một vòng 360°.
6. Khi xác nhận line, node khóa hướng chạy tiến và bám line bằng thuật toán PD
   từ `cambientu_V3.py`.
7. Node chống đếm lặp và xử lý ba line ngang:
   - Line 1: dừng và chạy lệnh `Load/Unload` đã chọn cho BT1; chờ STM32 xong.
   - Line 2: dừng và chạy lệnh `Load/Unload` đã chọn cho BT2; chờ STM32 xong.
   - Line 3: dừng cuối và báo thành công.

`Normal` luôn là `None/None` và chỉ dùng Nav2. `Approach Pose` không cho phép
`None`; bốn tổ hợp hợp lệ là `Load/Load`, `Load/Unload`, `Unload/Load` và
`Unload/Unload`. `Load` nhận hàng từ đầu nào kích hoạt cảm biến trước và gửi
`$CMD,START,<belt>` không kèm phía. `Unload` chỉ được phép trả về phía `LEFT`.

Lệnh motor được xuất ở `/cmd_vel_line` và đi qua `twist_mux`. Node không mở
cổng driver motor. Lệnh băng tải đi qua service `/run_belt_command`; node không
mở cổng UART STM32.

## Cấu hình bắt buộc

Điền cổng bus cảm biến ID83 + ID86 tại:

```yaml
magnetic_line_follower_node:
  ros__parameters:
    port: "abcdef"
```

File cấu hình dùng chung nằm tại `src/amr_lan_3/config/hardware_ports.yaml`.
`abcdef` chỉ là placeholder. Khi lắp phần cứng, nên thay bằng
`/dev/serial/by-id/...` hoặc `/dev/serial/by-path/...`; không dùng tên
`/dev/ttyUSB0` có thể thay đổi sau khi khởi động lại.

## Cách chọn chiều xoay

Sai số yaw được chuẩn hóa về `[-180°, 180°]`:

```text
delta_yaw = atan2(sin(yaw_setpoint - yaw_that),
                  cos(yaw_setpoint - yaw_that))
```

- `delta_yaw > 0`: xoay trái.
- `delta_yaw < 0`: xoay phải.

Ví dụ yaw thật `315°`, yaw setpoint `0°` cho kết quả `+45°`, nên xe xoay trái
45° thay vì xoay phải 315°.

Khi yaw đã gần setpoint, sai số ngang từ x/y chọn phía quét trước:

```text
lateral = -sin(yaw_setpoint) * (x_that - x_setpoint)
          +cos(yaw_setpoint) * (y_that - y_setpoint)
```

- `lateral > 0,02 m`: xe lệch trái, ưu tiên quét phải.
- `lateral < -0,02 m`: xe lệch phải, ưu tiên quét trái.
- Nằm trong ±0,02 m: mặc định quét trái trước.

Quét phía đầu tới biên 90°. Nếu chưa thấy line, node đổi chiều và quét tới
biên 90° đối diện. Hết cả hai phía thì dừng và báo lỗi.

## Giao thức STM32

Node chờ service hiện có trả thành công sau sự kiện `LOAD_DONE`. Bridge STM32
V4.1 hiện gửi frame có sequence, ví dụ `$CMD,<seq>,START,<belt>`. Không nên để
node line mở UART và gửi frame legacy song song vì hai node sẽ tranh cùng cổng.

Với firmware Version3, timeout BT1 mặc định là 120 giây và được tính từ lúc
bridge gửi lệnh UART sau khi phát hiện line ngang số 1 (`$CMD,START,1` đối với
`Load`). BT2 vẫn dùng timeout 60 giây.
