#!/usr/bin/env bash
# 1 cửa sổ Terminator, nhiều TAB (DBus tuần tự).
# Terminator không hỗ trợ nhiều --new-tab trong 1 lệnh — phải gọi từng lần.
#
# Dùng:  ./scripts/amr_terminator.sh sim
#        ./scripts/amr_terminator.sh real
#        ./scripts/amr_terminator.sh sim  nav   # tự Enter mọi tab TRỪ SLAM (chạy nav2)
#        ./scripts/amr_terminator.sh real nav
set -euo pipefail

WS="$HOME/dev_ws"
WORLD="$WS/src/amr_lan_3/worlds/obstacle_1.world"
MODE="${1:-sim}"
RUN="${2:-stage}"          # stage = dán sẵn (bấm ↑+Enter) | nav = tự chạy mọi tab trừ SLAM
BOOT_WAIT="${BOOT_WAIT:-1.2}"
TAB_WAIT="${TAB_WAIT:-0.3}"
NAV_WAIT="${NAV_WAIT:-3.0}" # chờ thêm trước khi tự chạy tab NAV (đợi LOC lên map)

if pgrep -x terminator >/dev/null 2>&1; then
  echo "Đang đóng Terminator cũ để tab không bị tách 2 cửa sổ..."
  pkill -x terminator
  sleep 0.5
fi

make_rc() {
  local cmd="$1"
  local autorun="${2:-no}"
  local f
  f="$(mktemp /tmp/amr_term_XXXXXX.rc)"
  {
    echo 'source ~/.bashrc 2>/dev/null || true'
    echo "source \"$WS/install/setup.bash\""
    echo "cd \"$WS\""
    if [[ "$autorun" == "yes" ]]; then
      echo 'echo ""'
      echo "echo \">>> Tự chạy: $cmd\""
      echo "history -s '$cmd'"
      echo "$cmd"
    else
      echo "history -s '$cmd'"
      echo 'echo ""'
      echo 'echo ">>> Lệnh đã sẵn sàng. Bấm ↑ rồi Enter:"'
      echo "echo \">>> $cmd\""
    fi
  } > "$f"
  echo "$f"
}

TABS=()
add_tab() { TABS+=("$1|$2"); }

case "$MODE" in
  sim)
    add_tab "SIM"   "ros2 launch amr_lan_3 launch_sim.launch.py world:=$WORLD"
    add_tab "WEB"   "python3 $WS/scripts/amr_web_server.py"
    add_tab "NGROK" "$WS/scripts/start_ngrok.sh"
    add_tab "SLAM"  "ros2 launch slam_toolbox online_async_launch.py slam_params_file:=./src/amr_lan_3/config/mapper_params_online_async.yaml use_sim_time:=true"
    add_tab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=true"
    add_tab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=true map_subscribe_transient_local:=true"
    ;;
  real)
    add_tab "ROBOT" "ros2 launch amr_lan_3 launch_robot.launch.py"
    add_tab "LIDAR" "ros2 launch amr_lan_3 rplidar.launch.py"
    add_tab "WEB"   "python3 $WS/scripts/amr_web_server.py"
    add_tab "NGROK" "$WS/scripts/start_ngrok.sh"
    add_tab "SLAM"  "ros2 launch slam_toolbox online_async_launch.py slam_params_file:=./src/amr_lan_3/config/mapper_params_online_async.yaml use_sim_time:=false"
    add_tab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=false"
    add_tab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=false map_subscribe_transient_local:=true"
    ;;
  *)
    echo "Dùng: $0 [sim|real] [nav]"
    echo "  nav = tự Enter mọi tab trừ SLAM (chạy nav2 luôn)"
    exit 1
    ;;
esac

# Cửa sổ mồi: tab đầu để DBus master sẵn sàng. Có thể đóng tab "boot" sau (Ctrl+Shift+W).
echo "Khởi động cửa sổ Terminator..."
terminator -T "boot" -e "bash -c 'source \"$WS/install/setup.bash\"; cd \"$WS\"; echo \"[boot] Tab này có thể đóng sau khi các tab khác đã mở.\"; exec bash'" &
sleep "$BOOT_WAIT"

for entry in "${TABS[@]}"; do
  IFS='|' read -r title cmd <<< "$entry"

  autorun="no"
  # Chế độ 'nav': tự Enter mọi tab TRỪ SLAM (SLAM vẫn để dán sẵn cho lúc quét map)
  if [[ "$RUN" == "nav" && "$title" != "SLAM" ]]; then
    autorun="yes"
    # NAV cần map từ LOC → chờ thêm trước khi tự chạy
    if [[ "$title" == "NAV" ]]; then
      sleep "$NAV_WAIT"
    fi
  fi

  rc="$(make_rc "$cmd" "$autorun")"
  terminator --new-tab -T "$title" -e "bash --rcfile $rc -i"
  sleep "$TAB_WAIT"
done

echo ""
echo "Đã mở ${#TABS[@]} tab trong 1 cửa sổ ($MODE, run=$RUN)."
if [[ "$RUN" == "nav" ]]; then
  echo "Chế độ nav: mọi tab TRỪ SLAM đã tự chạy. Tab SLAM để dán sẵn (bấm ↑+Enter khi cần quét map)."
else
  echo "Tab 'boot' có thể đóng (Ctrl+Shift+W). Các tab khác: bấm ↑ rồi Enter."
fi
echo "Chuyển tab: Ctrl+PageUp / Ctrl+PageDown."
