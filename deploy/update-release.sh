#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-$(id -un)}"
DOMAIN="myfinancing.asia"
API_PORT="8000"
CONDA_ENV_NAME="my-financing"
SKIP_GIT_PULL=0
SKIP_SCHEDULED_TASKS=0

usage() {
  cat <<'EOF'
Usage: sudo deploy/update-release.sh [options]

Apply code changes and publish the latest My Financing build on an existing server.

What it does:
  - optionally git pull latest code
  - install/update backend Python dependencies
  - build frontend into frontend/dist
  - verify Nginx config and reload Nginx
  - restart FastAPI systemd service
  - keep cloudflared-tunnel service enabled/running
  - install/update cron scheduled tasks
  - run health checks

Options:
  --app-dir PATH          Project directory. Defaults to this repository.
  --user USER             Linux user that owns/runs the app. Defaults to SUDO_USER.
  --domain DOMAIN         Public domain. Defaults to myfinancing.asia.
  --api-port PORT         Local FastAPI port. Defaults to 8000.
  --conda-env NAME        Prefer this conda env. Defaults to my-financing.
  --skip-git-pull         Use current working tree without pulling.
  --no-scheduled-tasks    Do not update cron scheduled tasks.
  -h, --help              Show this help.

Examples:
  sudo deploy/update-release.sh --user cykkk
  sudo deploy/update-release.sh --user cykkk --skip-git-pull
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --user)
      APP_USER="$2"
      shift 2
      ;;
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --api-port)
      API_PORT="$2"
      shift 2
      ;;
    --conda-env)
      CONDA_ENV_NAME="$2"
      shift 2
      ;;
    --skip-git-pull)
      SKIP_GIT_PULL=1
      shift
      ;;
    --no-scheduled-tasks)
      SKIP_SCHEDULED_TASKS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo/root." >&2
  exit 1
fi

if [ ! -d "$APP_DIR/backend" ] || [ ! -d "$APP_DIR/frontend" ]; then
  echo "Invalid --app-dir: $APP_DIR" >&2
  exit 1
fi

run_as_app_user() {
  sudo -u "$APP_USER" "$@"
}

echo "=== 1/8 Update source code ==="
if [ "$SKIP_GIT_PULL" -eq 0 ] && [ -d "$APP_DIR/.git" ]; then
  run_as_app_user git -C "$APP_DIR" pull --ff-only
else
  echo "Skipped git pull."
fi

echo "=== 2/8 Ensure backend Python environment and dependencies ==="
PYTHON_BIN=""
PIP_BIN=""
UVICORN_BIN=""
PYTHON_ENV_BIN=""

for prefix in "/home/${APP_USER}/miniconda3" "/home/${APP_USER}/anaconda3" "/opt/miniconda3" "/opt/anaconda3"; do
  if [ -x "${prefix}/envs/${CONDA_ENV_NAME}/bin/python" ]; then
    PYTHON_BIN="${prefix}/envs/${CONDA_ENV_NAME}/bin/python"
    PIP_BIN="${prefix}/envs/${CONDA_ENV_NAME}/bin/pip"
    UVICORN_BIN="${prefix}/envs/${CONDA_ENV_NAME}/bin/uvicorn"
    PYTHON_ENV_BIN="$(dirname "$PYTHON_BIN")"
    break
  fi
done

if [ -z "$PYTHON_BIN" ] && run_as_app_user bash -lc "command -v conda >/dev/null 2>&1 && conda run -n ${CONDA_ENV_NAME} python -c 'import sys; print(sys.executable)'" >/tmp/my-financing-python-path 2>/dev/null; then
  PYTHON_BIN="$(cat /tmp/my-financing-python-path | tail -n 1)"
  PIP_BIN="$(dirname "$PYTHON_BIN")/pip"
  UVICORN_BIN="$(dirname "$PYTHON_BIN")/uvicorn"
  PYTHON_ENV_BIN="$(dirname "$PYTHON_BIN")"
  rm -f /tmp/my-financing-python-path
fi

if [ -n "$PYTHON_BIN" ]; then
  echo "Using conda env ${CONDA_ENV_NAME}: ${PYTHON_BIN}"
  run_as_app_user "$PIP_BIN" install -r "$APP_DIR/backend/requirements.txt"
else
  echo "Conda env ${CONDA_ENV_NAME} not found; falling back to backend/.venv."
  if [ ! -x "$APP_DIR/backend/.venv/bin/python" ]; then
    run_as_app_user python3 -m venv "$APP_DIR/backend/.venv"
  fi
  run_as_app_user "$APP_DIR/backend/.venv/bin/pip" install --upgrade pip
  run_as_app_user "$APP_DIR/backend/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
  UVICORN_BIN="$APP_DIR/backend/.venv/bin/uvicorn"
  PYTHON_ENV_BIN="$APP_DIR/backend/.venv/bin"
fi

echo "=== 3/8 Build frontend ==="
cd "$APP_DIR/frontend"
if [ -f package-lock.json ]; then
  run_as_app_user npm ci
else
  run_as_app_user npm install
fi
run_as_app_user env VITE_API_BASE=/api npm run build

echo "=== 4/8 Verify Nginx configuration ==="
if [ -f /etc/nginx/sites-available/my-financing ]; then
  if ! grep -q "server_name ${DOMAIN}" /etc/nginx/sites-available/my-financing; then
    echo "Warning: /etc/nginx/sites-available/my-financing does not contain server_name ${DOMAIN}." >&2
  fi
else
  echo "Nginx site config is missing. Run deploy/deploy-cloudflare.sh first." >&2
  exit 1
fi
nginx -t

echo "=== 5/8 Restart/reload services ==="
if [ -f /etc/systemd/system/my-financing-api.service ] && ! grep -q "ExecStart=${UVICORN_BIN} " /etc/systemd/system/my-financing-api.service; then
  sed -i "s|^ExecStart=.*uvicorn app.main:app.*|ExecStart=${UVICORN_BIN} app.main:app --host 127.0.0.1 --port ${API_PORT} --workers 2|" /etc/systemd/system/my-financing-api.service
fi
if [ -f /etc/systemd/system/my-financing-api.service ]; then
  if grep -q '^Environment=PATH=' /etc/systemd/system/my-financing-api.service; then
    sed -i "s|^Environment=PATH=.*|Environment=PATH=${PYTHON_ENV_BIN}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin|" /etc/systemd/system/my-financing-api.service
  else
    sed -i "/^Environment=PYTHONUNBUFFERED=/a Environment=PATH=${PYTHON_ENV_BIN}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" /etc/systemd/system/my-financing-api.service
  fi
fi
systemctl daemon-reload
systemctl restart my-financing-api
systemctl reload nginx || systemctl restart nginx
if systemctl list-unit-files cloudflared-tunnel.service >/dev/null 2>&1; then
  systemctl enable --now cloudflared-tunnel
  if ! systemctl is-active --quiet cloudflared-tunnel; then
    systemctl restart cloudflared-tunnel
  fi
else
  echo "Warning: cloudflared-tunnel.service is missing. Run deploy/deploy-cloudflare.sh first." >&2
fi

echo "=== 6/8 Ensure scheduled tasks ==="
if [ "$SKIP_SCHEDULED_TASKS" -eq 0 ]; then
  "$APP_DIR/deploy/install-scheduled-tasks.sh" \
    --app-dir "$APP_DIR" \
    --user "$APP_USER" \
    --api-base "http://127.0.0.1:${API_PORT}"
else
  echo "Skipped scheduled tasks."
fi

echo "=== 7/8 Health checks ==="
curl -fsS "http://127.0.0.1:${API_PORT}/api/health" >/dev/null
curl -fsS "http://127.0.0.1/" >/dev/null

echo "=== 8/8 Status ==="
if systemctl list-unit-files cloudflared-tunnel.service >/dev/null 2>&1; then
  systemctl --no-pager --full status my-financing-api nginx cloudflared-tunnel || true
else
  systemctl --no-pager --full status my-financing-api nginx || true
fi
echo ""
echo "Release updated successfully."
echo "Public URL: https://${DOMAIN}"
