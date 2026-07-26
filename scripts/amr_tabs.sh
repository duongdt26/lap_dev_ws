#!/usr/bin/env bash
# Mở các tab gnome-terminal, tự cd + source, dán sẵn lệnh (CHƯA Enter).
# Dùng:  ./scripts/amr_tabs.sh sim localization
#        ./scripts/amr_tabs.sh real mapping
set -euo pipefail

WS="$HOME/dev_ws"
WORLD="$WS/src/amr_lan_3/worlds/obstacle_1.world"

# Tạo 1 tab: $1 = tiêu đề, $2 = lệnh dán sẵn
mktab() {
  local title="$1" cmd="$2"
  gnome-terminal --tab --title="$title" -- bash --rcfile <(cat <<EOF
source ~/.bashrc
source "$WS/install/setup.bash"
cd "$WS"
bind '"\e[0n": "$cmd"'
printf '\e[5n'
EOF
) 2>/dev/null
}

MODE="${1:-sim}"
PROFILE="${2:-localization}" # localization | mapping

case "$PROFILE" in
  localization|mapping) ;;
  *) echo "Dùng profile: localization hoặc mapping"; exit 1 ;;
esac

case "$MODE" in
  sim)
    mktab "SIM"   "ros2 launch amr_lan_3 launch_sim.launch.py world:=$WORLD"
    mktab "WEB"   "AMR_USE_SIM_TIME=true $WS/scripts/start_api_server.sh"
    mktab "NGROK" "$WS/scripts/start_ngrok.sh"
    if [[ "$PROFILE" == "mapping" ]]; then
      mktab "SLAM"  "$WS/scripts/slam_session.sh start sim"
    else
      mktab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=true"
      mktab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=true map_subscribe_transient_local:=true"
    fi
    ;;
  real)
    mktab "ROBOT" "ros2 launch amr_lan_3 launch_robot.launch.py"
    mktab "LIDAR" "ros2 launch amr_lan_3 rplidar.launch.py"
    mktab "WEB"   "AMR_USE_SIM_TIME=false $WS/scripts/start_api_server.sh"
    mktab "NGROK" "$WS/scripts/start_ngrok.sh"
    if [[ "$PROFILE" == "mapping" ]]; then
      mktab "SLAM"  "$WS/scripts/slam_session.sh start real"
    else
      mktab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=false"
      mktab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=false map_subscribe_transient_local:=true"
    fi
    ;;
  *)
    echo "Dùng: $0 [sim|real] [localization|mapping]"; exit 1 ;;
esac
