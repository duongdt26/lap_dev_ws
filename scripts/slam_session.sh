#!/usr/bin/env bash
# Quan ly mot phien SLAM rieng: khong chay dong thoi localization/AMCL.
#
#   ./scripts/slam_session.sh start sim
#   ./scripts/slam_session.sh save my_map
#   ./scripts/slam_session.sh stop
#
# launch_robot/launch_sim phai dang chay truoc de co sensor, odom, TF va map_bridge.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/scripts/.slam_session.pid"
PARAM_FILE="$ROOT/src/amr_lan_3/config/mapper_params_online_async.yaml"

running_pid() {
  [[ -s "$PID_FILE" ]] || return 1
  local pid
  pid="$(<"$PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

stop_session() {
  if ! running_pid; then
    rm -f "$PID_FILE"
    echo "Không có phiên SLAM đang chạy."
    return 0
  fi
  local pid
  pid="$(<"$PID_FILE")"
  echo "Dừng SLAM process group $pid..."
  kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 0.2
  done
  rm -f "$PID_FILE"
  echo "Đã dừng phiên SLAM."
}

start_session() {
  local mode="${1:-real}"
  local use_sim_time=false
  case "$mode" in
    sim) use_sim_time=true ;;
    real) use_sim_time=false ;;
    *) echo "Dùng: $0 start [sim|real]"; exit 2 ;;
  esac

  if running_pid; then
    echo "SLAM đã chạy (PID $(<"$PID_FILE")). Không khởi động bản thứ hai.";
    exit 1
  fi
  if ros2 node list 2>/dev/null | grep -qx '/slam_toolbox'; then
    echo "Đã có node /slam_toolbox; không khởi động trùng." >&2
    exit 1
  fi

  echo "Khởi động SLAM mapping (use_sim_time=$use_sim_time)..."
  echo "Sau khi quét xong, chạy: $0 save TEN_MAP"
  setsid ros2 launch slam_toolbox online_async_launch.py \
    slam_params_file:="$PARAM_FILE" \
    use_sim_time:="$use_sim_time" &
  local pid=$!
  echo "$pid" > "$PID_FILE"
  trap 'kill -INT -- -"$pid" 2>/dev/null || true; rm -f "$PID_FILE"' INT TERM EXIT
  wait "$pid"
}

save_session() {
  local map_name="${1:-}"
  if [[ ! "$map_name" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Tên map chỉ được dùng chữ, số, _ và -." >&2
    exit 2
  fi
  if ! running_pid; then
    echo "Không có phiên SLAM đang chạy." >&2
    exit 1
  fi
  echo "Lưu map '$map_name' qua map_bridge..."
  ros2 service call /save_map_named amr_web_interfaces/srv/SaveMap \
    "{map_name: '$map_name'}"
  stop_session
  echo "Hoàn tất: $ROOT/maps/$map_name.yaml và .pgm"
}

case "${1:-}" in
  start) start_session "${2:-real}" ;;
  save) save_session "${2:-}" ;;
  stop) stop_session ;;
  status)
    if running_pid; then echo "SLAM đang chạy (PID $(<"$PID_FILE"))."; else echo "SLAM đang dừng."; fi
    ;;
  *)
    echo "Dùng: $0 start [sim|real] | save TEN_MAP | stop | status"
    exit 2
    ;;
esac
