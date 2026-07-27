#!/usr/bin/env bash
# Dọn session AMR cũ trước khi mở tab mới (tránh slam/loc/nav/web trùng).
#
# Dùng:
#   ./scripts/amr_clean_session.sh          # dọn LOC/NAV/SLAM + WEB (+ sim/robot nếu có)
#   ./scripts/amr_clean_session.sh sim      # + Gazebo / launch_sim
#   ./scripts/amr_clean_session.sh real     # + launch_robot / rplidar
#   source scripts/amr_clean_session.sh && amr_clean_session sim

amr_clean_session() {
  local mode="${1:-all}"
  echo "[amr_clean] Dọn session cũ (mode=$mode)…"

  _amr_pkill() {
    local sig="$1"; shift
    local pat
    for pat in "$@"; do
      pkill -"$sig" -f "$pat" 2>/dev/null || true
    done
  }

  # Luôn dọn SLAM / LOC / NAV (tránh 2 slam hoặc map_server tranh /map)
  local common=(
    'online_async_launch.py'
    'async_slam_toolbox_node'
    'localization_launch.py'
    'navigation_launch.py'
    'nav2_map_server/map_server'
    'nav2_amcl/amcl'
    'nav2_bt_navigator/bt_navigator'
    'nav2_lifecycle_manager/lifecycle_manager'
    'nav2_controller/controller_server'
    'nav2_planner/planner_server'
    'nav2_behaviors/behavior_server'
    'nav2_smoother/smoother_server'
    'nav2_waypoint_follower/waypoint_follower'
    'nav2_velocity_smoother/velocity_smoother'
  )

  # WEB / bridge (API spawn lại trong tab WEB)
  local web=(
    'start_api_server.sh'
    'web_support.launch.py'
    'rosbridge_websocket'
    'map_bridge_node'
    'nav_pose_bridge'
    'start_ngrok.sh'
    'ngrok http'
    'uvicorn amr_api'
    'amr_api.main'
  )

  local sim=(
    'launch_sim.launch.py'
    'gzserver'
    'gzclient'
  )

  local real=(
    'launch_robot.launch.py'
    'rplidar.launch.py'
  )

  local pats=("${common[@]}" "${web[@]}")
  # Luôn dọn cả sim + real base stack — tránh Gazebo còn sót khi chạy real
  # (cùng ROS_DOMAIN) hoặc ngược lại.
  pats+=("${sim[@]}" "${real[@]}")
  case "$mode" in
    sim|real|all) ;;
    *)
      echo "[amr_clean] mode không rõ ($mode) — vẫn dọn all" >&2
      ;;
  esac

  _amr_pkill TERM "${pats[@]}"
  sleep 1.5
  _amr_pkill KILL "${pats[@]}"
  sleep 0.3

  if command -v ros2 >/dev/null 2>&1; then
    ros2 daemon stop >/dev/null 2>&1 || true
    ros2 daemon start >/dev/null 2>&1 || true
  fi

  echo "[amr_clean] Xong — sẵn sàng mở session mới."
}

# Chạy trực tiếp: ./scripts/amr_clean_session.sh [sim|real|all]
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  amr_clean_session "${1:-all}"
fi
