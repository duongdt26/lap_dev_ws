# AMR FastAPI + SQLite

Backend mới chạy song song với ROS 2 và thay `amr_web_server.py`. Trong giai đoạn
chuyển đổi, đường `/rosbridge` vẫn được proxy để các màn hình ROSLIB chưa chuyển
xong và mô phỏng Gazebo tiếp tục hoạt động.

## 1. Cài một lần trên mini PC

Khuyến nghị tạo virtual environment có thể nhìn thấy các gói ROS của hệ thống:

```bash
cd /home/laptop/dev_ws
python3 -m venv --system-site-packages .venv-api
source .venv-api/bin/activate
python3 -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

Không cần cài MySQL/PostgreSQL. SQLite được lưu trong một file.

## 2. Tạo database và tài khoản đầu tiên

Không ghi mật khẩu trực tiếp vào `.env` hoặc source code:

```bash
cd /home/laptop/dev_ws
source .venv-api/bin/activate
python3 -m backend.amr_api.cli init-db
python3 -m backend.amr_api.cli create-user --username admin --role admin
python3 -m backend.amr_api.cli import-legacy
```

Lệnh tạo tài khoản sẽ hỏi mật khẩu hai lần và chỉ lưu Argon2 hash. Backend cũng
tự import dữ liệu cũ khi database chưa có map nào.

Tạo thêm tài khoản:

```bash
python3 -m backend.amr_api.cli create-user --username operator01 --role operator
python3 -m backend.amr_api.cli create-user --username monitor01 --role viewer
```

Đổi mật khẩu bị quên:

```bash
python3 -m backend.amr_api.cli reset-password --username admin --role admin
```

## 3. Chạy mô phỏng

Terminal ROS/Gazebo chạy như trước. Terminal web chạy:

```bash
cd /home/laptop/dev_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
source .venv-api/bin/activate
AMR_USE_SIM_TIME=true ./scripts/start_api_server.sh
```

Mở `http://localhost:8080`. API docs ở `http://localhost:8080/api/docs`.

Chạy robot thật giống lệnh trên nhưng đặt `AMR_USE_SIM_TIME=false`.

## 4. Những chỗ được phép sửa tay

Sao chép `backend/.env.example` thành `backend/.env`, rồi chỉ sửa file
`backend/.env`. File thật đã được `.gitignore` để tránh commit cấu hình máy.

| Nhu cầu | Biến trong `backend/.env` | Mặc định |
|---|---|---|
| Nơi lưu SQLite | `AMR_DB_PATH` | `~/amr_data/amr.sqlite3` |
| Nơi lưu `.yaml/.pgm` | `AMR_MAPS_ROOT` | `~/maps` |
| Nơi đọc/ghi JSON cũ | `AMR_LEGACY_DATA_ROOT` | `~/MAP_DATA` |
| Ghi song song JSON cũ | `AMR_WRITE_LEGACY_FILES` | `true` |
| Tự nhập dữ liệu cũ lần đầu | `AMR_IMPORT_LEGACY_ON_START` | `true` |
| Thời hạn đăng nhập | `AMR_SESSION_TTL_SECONDS` | `28800` (8 giờ) |
| Cookie chỉ qua HTTPS | `AMR_COOKIE_SECURE` | `false` |
| Chế độ Gazebo | `AMR_USE_SIM_TIME` | `false` |
| Giữ rosbridge tạm thời | `AMR_ENABLE_ROSBRIDGE_PROXY` | `true` |
| Địa chỉ rosbridge nội bộ | `AMR_ROSBRIDGE_URL` | `ws://127.0.0.1:9090` |

Không sửa mật khẩu trực tiếp trong SQLite. Dùng CLI `reset-password` hoặc API
quản trị. Không commit `backend/.env` hay file `.sqlite3`.

Khi dùng HTTPS/ngrok, đặt `AMR_COOKIE_SECURE=true`. Khi chạy LAN bằng HTTP thì
giữ `false`, nếu không trình duyệt sẽ không gửi cookie đăng nhập.

## 5. SQLite đang lưu gì?

- `users`: tài khoản, Argon2 password hash, vai trò và trạng thái.
- `login_sessions`: hash của token phiên đăng nhập và thời điểm hết hạn.
- `maps`: tên map, đường dẫn YAML/PGM và metadata.
- `setpoint_collections`: danh sách setpoint theo map.
- `processes`: từng process và các bước theo map.
- `keepout_collections`: polygon vùng cấm theo map.
- `app_settings`: cấu hình nghiệp vụ bổ sung sau này.
- `audit_logs`: lịch sử đăng nhập và thay đổi dữ liệu quan trọng.

File ảnh map vẫn nằm ngoài SQLite vì PGM có kích thước lớn và ROS/Nav2 cần đọc
trực tiếp bằng đường dẫn.

## 6. Phân quyền

- `admin`: quản lý tài khoản và toàn bộ dữ liệu/điều khiển.
- `operator`: sửa dữ liệu và điều khiển robot.
- `viewer`: chỉ đọc dữ liệu/telemetry.

Trong giai đoạn tương thích, rosbridge vẫn cho frontend cũ truy cập ROS trực
tiếp nên chưa thể xem là lớp bảo mật cuối cùng. Chỉ đặt
`AMR_ENABLE_ROSBRIDGE_PROXY=false` và bind rosbridge vào `127.0.0.1` sau khi tất
cả module điều khiển đã chuyển sang API.

## 7. Backup và phục hồi

Khi server đã dừng, backup các mục sau:

```text
~/amr_data/amr.sqlite3
~/maps/
~/MAP_DATA/        # giữ trong giai đoạn chuyển đổi
backend/.env
```

Nếu backup lúc server đang chạy, cần copy cả file `-wal` và `-shm` hoặc dùng
lệnh backup của SQLite; không chỉ copy riêng file `.sqlite3`.

## 8. Quy trình SLAM mapping ổn định

Không chạy đồng thời `slam_toolbox` và `localization_launch.py`. Hai luồng này
đều liên quan đến transform `map -> odom`; chạy cùng lúc có thể làm TF/map nhảy.

Sau khi `launch_sim.launch.py` hoặc `launch_robot.launch.py` đã chạy, mở một
terminal khác:

```bash
# Mô phỏng
./scripts/slam_session.sh start sim

# Robot thật
./scripts/slam_session.sh start real
```

Điều khiển robot, chạy một vòng quét kín, rồi lưu và tự dừng SLAM:

```bash
./scripts/slam_session.sh save ten_map_moi
```

Lệnh này gọi `/save_map_named` của `map_bridge_node`, tạo
`~/maps/ten_map_moi.yaml`, `~/maps/ten_map_moi.pgm`, sau đó dừng process SLAM.
Nếu cần dừng mà không lưu:

```bash
./scripts/slam_session.sh stop
```

Sau khi map đã lưu, chạy localization và Nav2 (không chạy SLAM):

```bash
ros2 launch amr_lan_3 localization_launch.py map:=./ten_map_moi.yaml use_sim_time:=false
ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=false map_subscribe_transient_local:=true
```

Shortcut desktop đã được sửa để có hai profile riêng:

```bash
./scripts/amr_tabs.sh real localization  # map đã lưu + Nav2
./scripts/amr_tabs.sh real mapping       # chỉ phiên SLAM, không LOC/NAV
```

## 9. Trạng thái chuyển đổi hiện tại

Đã chuyển:

- Đăng nhập, đăng xuất, session cookie và vai trò tài khoản.
- SQLite schema/migration, audit log và API quản lý tài khoản.
- Setpoint, process và keepout đọc/ghi qua REST API.
- Import JSON cũ và ghi song song JSON trong giai đoạn chuyển đổi.
- ROS gateway cho telemetry, teleop và navigation service ở backend.
- WebSocket telemetry có xác thực ở `/api/ws/telemetry`.
- WebSocket control có xác thực ở `/api/ws/control`, tự gửi stop khi mất kết nối.

Vẫn dùng rosbridge tương thích:

- Render map/costmap/plan và đặt initial pose.
- STM32/conveyor, mission và magnetic line.
- ROS service áp dụng keepout mask ngay lập tức.

Vì vậy chưa đổi `AMR_ENABLE_ROSBRIDGE_PROXY=false`. Giai đoạn tiếp theo sẽ chuyển
từng module còn lại sang API/WebSocket rồi mới đóng port `9090` khỏi bên ngoài.
