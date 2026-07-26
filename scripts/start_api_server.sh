#!/usr/bin/env bash
# Chay dashboard + FastAPI + SQLite. Source ROS workspace truoc khi goi script.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${AMR_ENV_FILE:-$PROJECT_ROOT/backend/.env}"

# Lenh `AMR_USE_SIM_TIME=true ./scripts/start_api_server.sh` phai uu tien hon .env.
SIM_TIME_WAS_SET=false
SIM_TIME_OVERRIDE=""
if [[ -v AMR_USE_SIM_TIME ]]; then
  SIM_TIME_WAS_SET=true
  SIM_TIME_OVERRIDE="$AMR_USE_SIM_TIME"
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ "$SIM_TIME_WAS_SET" == true ]]; then
  export AMR_USE_SIM_TIME="$SIM_TIME_OVERRIDE"
fi

cd "$PROJECT_ROOT"
PYTHON_BIN="python3"
if [[ -x "$PROJECT_ROOT/.venv-api/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv-api/bin/python"
fi

exec "$PYTHON_BIN" -m uvicorn backend.amr_api.main:app \
  --host "${AMR_API_HOST:-0.0.0.0}" \
  --port "${AMR_API_PORT:-8080}"
