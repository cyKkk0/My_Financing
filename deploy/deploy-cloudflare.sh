#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-$(id -un)}"
DOMAIN="myfinancing.asia"
API_PORT="8000"
CONDA_ENV_NAME="my-financing"
ADMIN_TOKEN_VALUE="${ADMIN_TOKEN:-}"
CLOUDFLARED_TOKEN_VALUE="${CLOUDFLARED_TOKEN:-}"
INSTALL_SCHEDULED_TASKS=1

usage() {
  cat <<'EOF'
Usage: sudo deploy/deploy-cloudflare.sh [options]

Deploy My Financing behind Cloudflare Tunnel on a Linux server.

Before running:
  1. Add myfinancing.asia to Cloudflare and point nameservers to Cloudflare.
  2. Cloudflare Zero Trust -> Networks -> Tunnels -> Create tunnel.
  3. Add Public Hostname:
       Hostname: myfinancing.asia
       Service:  http://127.0.0.1:80
  4. Copy the tunnel token and pass it with --cloudflared-token or CLOUDFLARED_TOKEN.

Options:
  --app-dir PATH              Project directory. Defaults to this repository.
  --user USER                 Linux user that owns/runs the app. Defaults to SUDO_USER.
  --domain DOMAIN             Public domain. Defaults to myfinancing.asia.
  --api-port PORT             Local FastAPI port. Defaults to 8000.
  --conda-env NAME            Prefer this conda env. Defaults to my-financing.
  --admin-token TOKEN         Backend admin token. Defaults to ADMIN_TOKEN or backend/.env.
  --cloudflared-token TOKEN   Cloudflare Tunnel token. Defaults to CLOUDFLARED_TOKEN.
  --no-scheduled-tasks        Do not install cron jobs.
  -h, --help                  Show this help.
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
    --admin-token)
      ADMIN_TOKEN_VALUE="$2"
      shift 2
      ;;
    --cloudflared-token)
      CLOUDFLARED_TOKEN_VALUE="$2"
      shift 2
      ;;
    --no-scheduled-tasks)
      INSTALL_SCHEDULED_TASKS=0
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

if [ -z "$CLOUDFLARED_TOKEN_VALUE" ]; then
  echo "Cloudflare Tunnel token is required. Pass --cloudflared-token or export CLOUDFLARED_TOKEN." >&2
  exit 1
fi

BACKEND_ENV="$APP_DIR/backend/.env"
if [ -z "$ADMIN_TOKEN_VALUE" ] && [ -f "$BACKEND_ENV" ]; then
  ADMIN_TOKEN_VALUE="$(grep -E '^ADMIN_TOKEN=' "$BACKEND_ENV" | tail -n 1 | cut -d= -f2- || true)"
fi
if [ -z "$ADMIN_TOKEN_VALUE" ]; then
  ADMIN_TOKEN_VALUE="$(openssl rand -hex 24)"
fi

echo "=== 1/9 Install system packages ==="
apt-get update
apt-get install -y nginx curl ca-certificates python3 python3-venv python3-pip openssl

NODE_MAJOR="$(node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/' || true)"
if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

echo "=== 2/9 Install cloudflared ==="
if ! command -v cloudflared >/dev/null 2>&1; then
  ARCH="$(dpkg --print-architecture)"
  case "$ARCH" in
    amd64|arm64) ;;
    *) echo "Unsupported architecture for automatic cloudflared install: $ARCH" >&2; exit 1 ;;
  esac
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb" -o /tmp/cloudflared.deb
  dpkg -i /tmp/cloudflared.deb
  rm -f /tmp/cloudflared.deb
fi

echo "=== 3/9 Write backend environment ==="
touch "$BACKEND_ENV"
chown "$APP_USER":"$APP_USER" "$BACKEND_ENV"
chmod 600 "$BACKEND_ENV"

set_env() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" "$BACKEND_ENV"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$BACKEND_ENV"
  else
    echo "${key}=${value}" >> "$BACKEND_ENV"
  fi
}

set_env "DATABASE_URL" "sqlite:///./finance.sqlite3"
set_env "FRONTEND_ORIGINS" "https://${DOMAIN},http://localhost:5173,http://127.0.0.1:5173"
set_env "ADMIN_TOKEN" "$ADMIN_TOKEN_VALUE"
grep -qE '^LLM_API_BASE=' "$BACKEND_ENV" || echo "LLM_API_BASE=https://api.openai.com/v1" >> "$BACKEND_ENV"
grep -qE '^LLM_MODEL=' "$BACKEND_ENV" || echo "LLM_MODEL=gpt-4o-mini" >> "$BACKEND_ENV"
grep -qE '^LLM_API_KEY=' "$BACKEND_ENV" || echo "LLM_API_KEY=" >> "$BACKEND_ENV"

echo "=== 4/9 Install backend dependencies ==="
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

if [ -z "$PYTHON_BIN" ] && sudo -u "$APP_USER" bash -lc "command -v conda >/dev/null 2>&1 && conda run -n ${CONDA_ENV_NAME} python -c 'import sys; print(sys.executable)'" >/tmp/my-financing-python-path 2>/dev/null; then
  PYTHON_BIN="$(cat /tmp/my-financing-python-path | tail -n 1)"
  PIP_BIN="$(dirname "$PYTHON_BIN")/pip"
  UVICORN_BIN="$(dirname "$PYTHON_BIN")/uvicorn"
  PYTHON_ENV_BIN="$(dirname "$PYTHON_BIN")"
  rm -f /tmp/my-financing-python-path
fi

if [ -n "$PYTHON_BIN" ]; then
  echo "Using conda env ${CONDA_ENV_NAME}: ${PYTHON_BIN}"
  sudo -u "$APP_USER" "$PIP_BIN" install -r "$APP_DIR/backend/requirements.txt"
else
  echo "Conda env ${CONDA_ENV_NAME} not found; falling back to backend/.venv."
  sudo -u "$APP_USER" python3 -m venv "$APP_DIR/backend/.venv"
  sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install --upgrade pip
  sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
  UVICORN_BIN="$APP_DIR/backend/.venv/bin/uvicorn"
  PYTHON_ENV_BIN="$APP_DIR/backend/.venv/bin"
fi

echo "=== 5/9 Build frontend ==="
cd "$APP_DIR/frontend"
if [ -f package-lock.json ]; then
  sudo -u "$APP_USER" npm ci
else
  sudo -u "$APP_USER" npm install
fi
sudo -u "$APP_USER" env VITE_API_BASE=/api npm run build

echo "=== 6/9 Configure Nginx ==="
cat > /etc/nginx/sites-available/my-financing <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    root ${APP_DIR}/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    server_tokens off;
}
EOF
ln -sf /etc/nginx/sites-available/my-financing /etc/nginx/sites-enabled/my-financing
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo "=== 7/9 Configure systemd services ==="
cat > /etc/systemd/system/my-financing-api.service <<EOF
[Unit]
Description=My Financing API (FastAPI)
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
ExecStart=${UVICORN_BIN} app.main:app --host 127.0.0.1 --port ${API_PORT} --workers 2
Environment=PYTHONUNBUFFERED=1
Environment=PATH=${PYTHON_ENV_BIN}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

install -d -m 700 /etc/my-financing
cat > /etc/my-financing/cloudflared.env <<EOF
CLOUDFLARED_TOKEN=${CLOUDFLARED_TOKEN_VALUE}
EOF
chmod 600 /etc/my-financing/cloudflared.env

cat > /etc/systemd/system/cloudflared-tunnel.service <<'EOF'
[Unit]
Description=Cloudflare Tunnel for My Financing
After=network.target nginx.service

[Service]
Type=simple
EnvironmentFile=/etc/my-financing/cloudflared.env
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run --token ${CLOUDFLARED_TOKEN}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now my-financing-api nginx cloudflared-tunnel
systemctl restart my-financing-api nginx cloudflared-tunnel

echo "=== 8/9 Install scheduled tasks ==="
if [ "$INSTALL_SCHEDULED_TASKS" -eq 1 ]; then
  "$APP_DIR/deploy/install-scheduled-tasks.sh" \
    --app-dir "$APP_DIR" \
    --user "$APP_USER" \
    --api-base "http://127.0.0.1:${API_PORT}" \
    --token "$ADMIN_TOKEN_VALUE"
else
  echo "Skipped scheduled tasks."
fi

echo "=== 9/9 Status ==="
systemctl --no-pager --full status my-financing-api nginx cloudflared-tunnel || true
echo ""
echo "Deployment finished."
echo "Public URL: https://${DOMAIN}"
echo "Admin token was written to ${BACKEND_ENV}."
echo "If the URL is not live yet, check the Cloudflare Tunnel public hostname:"
echo "  ${DOMAIN} -> http://127.0.0.1:80"
