#!/usr/bin/env bash
# Dọn session Gazebo/rosbridge cũ trước khi launch sim mới.
set -euo pipefail

echo "[clean_sim] Dừng gzserver, gzclient, rosbridge, launch_sim..."
pkill -f 'gzserver' 2>/dev/null || true
pkill -f 'gzclient' 2>/dev/null || true
pkill -f 'rosbridge_websocket' 2>/dev/null || true
pkill -f 'launch_sim.launch.py' 2>/dev/null || true
sleep 2

if ss -tlnp 2>/dev/null | grep -q ':9091 '; then
  echo "[clean_sim] CẢNH BÁO: port 9091 vẫn bị chiếm — kiểm tra thủ công:"
  ss -tlnp | grep ':9091 ' || true
else
  echo "[clean_sim] Port 9091 trống."
fi

if pgrep -f 'gzserver' >/dev/null 2>&1; then
  echo "[clean_sim] CẢNH BÁO: gzserver vẫn còn chạy."
else
  echo "[clean_sim] Không còn gzserver."
fi

WORLD="${1:-/home/laptop/dev_ws/src/amr_lan_3/worlds/obstacle_1.world}"
echo "[clean_sim] Launch sim: world=${WORLD}"
source /home/laptop/dev_ws/install/setup.bash
exec ros2 launch amr_lan_3 launch_sim.launch.py "world:=${WORLD}"
