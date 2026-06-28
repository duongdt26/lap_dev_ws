#!/usr/bin/env bash
# Ngrok FREE (1 tunnel): public web + rosbridge qua amr_web_server.py
#
# Trước khi chạy (1 lần):
#   ngrok config add-authtoken YOUR_TOKEN
#
# Mỗi lần:
#   ros2 launch amr_lan_3 launch_robot.launch.py
#   python3 scripts/amr_web_server.py
#   ./scripts/start_ngrok.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NGROK_CONFIG="$ROOT/scripts/ngrok_amr.yml"
CONFIG_OUT="$ROOT/web/amr_dashboard/config.json"
WRITE_PY="$ROOT/scripts/write_ngrok_config.py"

# ngrok snap: ~/snap/ngrok/current/.config/ngrok/ngrok.yml
# ngrok apt/binary: ~/.config/ngrok/ngrok.yml
find_ngrok_user_config() {
  local f
  for f in \
    "${HOME}/.config/ngrok/ngrok.yml" \
    "${HOME}/snap/ngrok/current/.config/ngrok/ngrok.yml"
  do
    if [[ -f "$f" ]]; then
      echo "$f"
      return 0
    fi
  done
  for f in "${HOME}/snap/ngrok/"*/.config/ngrok/ngrok.yml; do
    if [[ -f "$f" ]]; then
      echo "$f"
      return 0
    fi
  done
  return 1
}

NGROK_USER_CONFIG="$(find_ngrok_user_config || true)"

if ! command -v ngrok >/dev/null 2>&1; then
  echo "Chưa cài ngrok. Xem: https://dashboard.ngrok.com/get-started/setup"
  exit 1
fi

if ! python3 -c "import aiohttp" 2>/dev/null; then
  echo "Cần aiohttp cho amr_web_server.py:"
  echo "  pip install -r scripts/requirements-web.txt"
  exit 1
fi

has_authtoken() {
  if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
    return 0
  fi
  if [[ -n "$NGROK_USER_CONFIG" ]] && grep -qE '^[[:space:]]*authtoken:[[:space:]]+[A-Za-z0-9_/-]+' "$NGROK_USER_CONFIG"; then
    return 0
  fi
  if grep -qE '^[[:space:]]*authtoken:[[:space:]]+[A-Za-z0-9_/-]+' "$NGROK_CONFIG"; then
    return 0
  fi
  return 1
}

if ! has_authtoken; then
  echo ""
  echo "=== Chưa có ngrok authtoken (ERR_NGROK_4018) ==="
  echo ""
  echo "1. Đăng ký miễn phí: https://dashboard.ngrok.com/signup"
  echo "2. Lấy token:        https://dashboard.ngrok.com/get-started/your-authtoken"
  echo "3. Chạy một lần trên máy này:"
  echo ""
  echo "     ngrok config add-authtoken YOUR_TOKEN_HERE"
  echo ""
  echo "Snap ngrok lưu tại: ~/snap/ngrok/current/.config/ngrok/ngrok.yml"
  echo "Kiểm tra: cat ~/snap/ngrok/current/.config/ngrok/ngrok.yml"
  echo ""
  echo "Sau đó chạy lại: ./scripts/start_ngrok.sh"
  echo ""
  exit 1
fi

if [[ -n "$NGROK_USER_CONFIG" ]]; then
  echo "Dùng ngrok config: $NGROK_USER_CONFIG"
fi

mkdir -p "$(dirname "$CONFIG_OUT")"

ngrok_cmd() {
  if [[ -n "$NGROK_USER_CONFIG" ]]; then
    ngrok start amr --config "$NGROK_USER_CONFIG" --config "$NGROK_CONFIG" --log=stdout
  else
    ngrok start amr --config "$NGROK_CONFIG" --log=stdout
  fi
}

start_ngrok() {
  echo "Đang khởi động ngrok (1 tunnel → :8080, web + rosbridge proxy)..."
  ngrok_cmd &
  echo $! > "$ROOT/scripts/.ngrok_amr.pid"
}

if [[ -f "$ROOT/scripts/.ngrok_amr.pid" ]]; then
  pid="$(cat "$ROOT/scripts/.ngrok_amr.pid")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "ngrok đã chạy (pid $pid), chỉ cập nhật config.json..."
  else
    start_ngrok
  fi
else
  start_ngrok
fi

echo "Đợi ngrok API..."
ready=false
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
    ready=true
    break
  fi
  if ! kill -0 "$(cat "$ROOT/scripts/.ngrok_amr.pid")" 2>/dev/null; then
    echo ""
    echo "ngrok thoát sớm — kiểm tra authtoken hoặc port 8080 đã có amr_web_server chưa."
    exit 1
  fi
  sleep 1
done

if [[ "$ready" != true ]]; then
  echo "Không kết nối được ngrok API sau 30s."
  exit 1
fi

python3 "$WRITE_PY" "$CONFIG_OUT"

WEB_URL="$(python3 -c "import json; print(json.load(open('$CONFIG_OUT')).get('webUrl',''))")"

echo ""
echo "=== AMR ngrok (free — 1 link) ==="
echo "Chia sẻ link này: $WEB_URL"
echo "Rosbridge: cùng domain, path /rosbridge (tự điền + tự kết nối)"
echo ""
echo "Dashboard ngrok: http://127.0.0.1:4040"
