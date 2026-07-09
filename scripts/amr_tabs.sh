#!/usr/bin/env bash
# Mở các tab gnome-terminal, tự cd + source, dán sẵn lệnh (CHƯA Enter).
# Dùng:  ./scripts/amr_tabs.sh sim
#        ./scripts/amr_tabs.sh real
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

case "$MODE" in
  sim)
    mktab "SIM"   "ros2 launch amr_lan_3 launch_sim.launch.py world:=$WORLD"
    mktab "WEB"   "python3 $WS/scripts/amr_web_server.py"
    mktab "NGROK" "$WS/scripts/start_ngrok.sh"
    mktab "SLAM"  "ros2 launch slam_toolbox online_async_launch.py slam_params_file:=./src/amr_lan_3/config/mapper_params_online_async.yaml use_sim_time:=true"
    mktab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=true"
    mktab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=true map_subscribe_transient_local:=true"
    ;;
  real)
    mktab "ROBOT" "ros2 launch amr_lan_3 launch_robot.launch.py"
    mktab "LIDAR" "ros2 launch amr_lan_3 rplidar.launch.py"
    mktab "WEB"   "python3 $WS/scripts/amr_web_server.py"
    mktab "NGROK" "$WS/scripts/start_ngrok.sh"
    mktab "SLAM"  "ros2 launch slam_toolbox online_async_launch.py slam_params_file:=./src/amr_lan_3/config/mapper_params_online_async.yaml use_sim_time:=false"
    mktab "LOC"   "ros2 launch amr_lan_3 localization_launch.py map:=./obs_3_map_save.yaml use_sim_time:=false"
    mktab "NAV"   "ros2 launch amr_lan_3 navigation_launch.py use_sim_time:=false map_subscribe_transient_local:=true"
    ;;
  *)
    echo "Dùng: $0 [sim|real]"; exit 1 ;;
esac
