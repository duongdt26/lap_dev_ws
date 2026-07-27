#!/usr/bin/env bash
# Mở các tab gnome-terminal, tự cd + source, tự chạy lệnh.
# mapping: tự chạy trừ tab SLAM (dán sẵn).
#
# Dùng:
#   ./scripts/amr_tabs.sh sim idle           # SIM + WEB + NGROK (tự chạy)
#   ./scripts/amr_tabs.sh real idle          # ROBOT + LIDAR + WEB + NGROK
#   ./scripts/amr_tabs.sh sim localization  # + LOC + NAV
#   ./scripts/amr_tabs.sh real mapping       # + tab SLAM (dán sẵn)
#
# Profile idle: không bật SLAM/LOC/NAV.
#   Trên web: SLAM ON  → API bật slam_toolbox
#             SLAM OFF → tắt SLAM, Save map (nếu có tên), bật LOC+NAV
set -euo pipefail

WS="$HOME/dev_ws"
WORLD="$WS/src/amr_lan_3/worlds/obstacle_1.world"
NGROK_WAIT="${NGROK_WAIT:-2.5}"
NAV_WAIT="${NAV_WAIT:-3.0}"
# SKIP_CLEAN=1 ./scripts/amr_tabs.sh …  → không dọn session cũ
SKIP_CLEAN="${SKIP_CLEAN:-0}"

# shellcheck source=amr_clean_session.sh
source "$WS/scripts/amr_clean_session.sh"

# Ghi rcfile tạm (tránh process-substitution bị đóng trước khi tab bash đọc).
make_rc() {
  local cmd="$1" autorun="${2:-yes}"
  local f
  f="$(mktemp /tmp/amr_tabs_XXXXXX.rc)"
  {
    echo 'source ~/.bashrc 2>/dev/null || true'
    echo "source \"$WS/install/setup.bash\""
    echo "cd \"$WS\""
    if [[ "$autorun" == "yes" ]]; then
      echo 'echo ""'
      # shellcheck disable=SC2016
      printf 'echo ">>> Tự chạy: %s"\n' "$cmd"
      printf "history -s %q\n" "$cmd"
      printf '%s\n' "$cmd"
      echo 'exec bash'
    else
      printf "history -s %q\n" "$cmd"
      echo 'echo ""'
      echo 'echo ">>> Lệnh đã sẵn sàng. Bấm ↑ rồi Enter:"'
      printf 'echo ">>> %s"\n' "$cmd"
    fi
  } > "$f"
  echo "$f"
}

# $1=title $2=cmd $3=autorun(yes|no)
mktab() {
  local title="$1" cmd="$2" autorun="${3:-yes}"
  local rc
  rc="$(make_rc "$cmd" "$autorun")"
  gnome-terminal --tab --title="$title" -- bash --rcfile "$rc" -i 2>/dev/null || true
}

MODE="${1:-sim}"
PROFILE="${2:-idle}" # idle | localization | mapping

case "$PROFILE" in
  idle|localization|mapping) ;;
  *)
    echo "Dùng profile: idle | localization | mapping"
    echo "  idle         = chỉ robot/sim + WEB (SLAM/LOC/NAV điều khiển trên web)"
    echo "  localization = + LOC + NAV ngay từ đầu"
    echo "  mapping      = + tab SLAM thủ công (không khuyến nghị nếu dùng nút web)"
    exit 1
    ;;
esac

case "$MODE" in
  sim|real) ;;
  *)
    echo "Dùng: $0 [sim|real] [idle|localization|mapping]"
    exit 1
    ;;
esac

if [[ "$SKIP_CLEAN" != "1" ]]; then
  amr_clean_session "$MODE"
fi

case "$MODE" in
  sim)
    mktab "SIM"   "ros2 launch amr_lan_3 launch_sim.launch.py world:=$WORLD" yes
    mktab "WEB"   "AMR_USE_SIM_TIME=true $WS/scripts/start_api_server.sh" yes
    sleep "$NGROK_WAIT"
    mktab "NGROK" "$WS/scripts/start_ngrok.sh" yes
    if [[ "$PROFILE" == "mapping" ]]; then
      mktab "SLAM"  "$WS/scripts/slam_session.sh start sim" no
    elif [[ "$PROFILE" == "localization" ]]; then
      mktab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=true" yes
      sleep "$NAV_WAIT"
      mktab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=true map_subscribe_transient_local:=true" yes
    fi
    ;;
  real)
    mktab "ROBOT" "ros2 launch amr_lan_3 launch_robot.launch.py" yes
    mktab "LIDAR" "ros2 launch amr_lan_3 rplidar.launch.py" yes
    mktab "WEB"   "AMR_USE_SIM_TIME=false $WS/scripts/start_api_server.sh" yes
    sleep "$NGROK_WAIT"
    mktab "NGROK" "$WS/scripts/start_ngrok.sh" yes
    if [[ "$PROFILE" == "mapping" ]]; then
      mktab "SLAM"  "$WS/scripts/slam_session.sh start real" no
    elif [[ "$PROFILE" == "localization" ]]; then
      mktab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=false" yes
      sleep "$NAV_WAIT"
      mktab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=false map_subscribe_transient_local:=true" yes
    fi
    ;;
esac

echo "Đã mở tab ($MODE / $PROFILE) — lệnh tự chạy (SIM và real như nhau)."
if [[ "$PROFILE" == "idle" ]]; then
  echo "Idle: chưa chạy SLAM/LOC/NAV."
  echo "  → Web: SLAM ON để quét | SLAM OFF (+ tên map) để Save và bật LOC+NAV."
elif [[ "$PROFILE" == "mapping" ]]; then
  echo "Tab SLAM vẫn dán sẵn — bấm ↑ rồi Enter khi cần quét map."
fi
