#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE_URL="http://127.0.0.1:8000"
CRON_USER="${SUDO_USER:-$(id -un)}"
ACTION="install"

usage() {
  cat <<'EOF'
Usage: deploy/install-scheduled-tasks.sh [options]

Install or remove local cron jobs for My Financing.

Options:
  --app-dir PATH       Project directory. Defaults to the repository root.
  --api-base URL       Backend base URL. Defaults to http://127.0.0.1:8000.
  --user USER          Cron user. Defaults to SUDO_USER or the current user.
  --token TOKEN        Admin token. Defaults to ADMIN_TOKEN or backend/.env.
  --uninstall          Remove My Financing cron jobs.
  -h, --help           Show this help.

Examples:
  sudo deploy/install-scheduled-tasks.sh --user cykkk
  ADMIN_TOKEN=your-token deploy/install-scheduled-tasks.sh --api-base http://127.0.0.1:8000
EOF
}

ADMIN_TOKEN_VALUE="${ADMIN_TOKEN:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --api-base)
      API_BASE_URL="${2%/}"
      shift 2
      ;;
    --user)
      CRON_USER="$2"
      shift 2
      ;;
    --token)
      ADMIN_TOKEN_VALUE="$2"
      shift 2
      ;;
    --uninstall)
      ACTION="uninstall"
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

if [ -z "$ADMIN_TOKEN_VALUE" ] && [ -f "$APP_DIR/backend/.env" ]; then
  ADMIN_TOKEN_VALUE="$(grep -E '^ADMIN_TOKEN=' "$APP_DIR/backend/.env" | tail -n 1 | cut -d= -f2-)"
fi

if [ "$ACTION" = "install" ] && [ -z "$ADMIN_TOKEN_VALUE" ]; then
  echo "ADMIN_TOKEN is required. Pass --token, export ADMIN_TOKEN, or set backend/.env." >&2
  exit 1
fi

CURRENT_USER="$(id -un)"
if [ "$(id -u)" -eq 0 ]; then
  CRONTAB_LIST=(crontab -u "$CRON_USER" -l)
  CRONTAB_INSTALL=(crontab -u "$CRON_USER")
elif [ "$CRON_USER" = "$CURRENT_USER" ]; then
  CRONTAB_LIST=(crontab -l)
  CRONTAB_INSTALL=(crontab)
else
  echo "Installing for --user ${CRON_USER} requires root privileges." >&2
  exit 1
fi

if command -v curl >/dev/null 2>&1; then
  CURL_BIN="$(command -v curl)"
else
  echo "curl is required." >&2
  exit 1
fi

if command -v flock >/dev/null 2>&1; then
  FLOCK_BIN="$(command -v flock)"
  DAILY_COMMAND="${FLOCK_BIN} -n /tmp/my-financing-daily-update.lock ${CURL_BIN} -fsS -X POST -H 'X-Admin-Token: ${ADMIN_TOKEN_VALUE}' ${API_BASE_URL}/api/jobs/daily-update"
  DCA_COMMAND="${FLOCK_BIN} -n /tmp/my-financing-dca-check.lock ${CURL_BIN} -fsS -X POST -H 'X-Admin-Token: ${ADMIN_TOKEN_VALUE}' ${API_BASE_URL}/api/jobs/dca-check"
else
  DAILY_COMMAND="${CURL_BIN} -fsS -X POST -H 'X-Admin-Token: ${ADMIN_TOKEN_VALUE}' ${API_BASE_URL}/api/jobs/daily-update"
  DCA_COMMAND="${CURL_BIN} -fsS -X POST -H 'X-Admin-Token: ${ADMIN_TOKEN_VALUE}' ${API_BASE_URL}/api/jobs/dca-check"
fi

TMP_FILE="$(mktemp)"
cleanup() {
  rm -f "$TMP_FILE"
}
trap cleanup EXIT

"${CRONTAB_LIST[@]}" 2>/dev/null \
  | sed '/# BEGIN My Financing scheduled tasks/,/# END My Financing scheduled tasks/d' \
  > "$TMP_FILE" || true

if [ "$ACTION" = "install" ]; then
  cat >> "$TMP_FILE" <<EOF
# BEGIN My Financing scheduled tasks
# Run on a machine whose local timezone is Asia/Shanghai.
0 21 * * * ${DAILY_COMMAND}
30 9 * * * ${DCA_COMMAND}
# END My Financing scheduled tasks
EOF
fi

"${CRONTAB_INSTALL[@]}" "$TMP_FILE"

if [ "$ACTION" = "install" ]; then
  echo "Installed My Financing scheduled tasks for user ${CRON_USER}:"
  "${CRONTAB_LIST[@]}" | sed -n '/# BEGIN My Financing scheduled tasks/,/# END My Financing scheduled tasks/p' | sed -E "s/(X-Admin-Token: )[^']+/\1***/g"
else
  echo "Removed My Financing scheduled tasks for user ${CRON_USER}."
fi
