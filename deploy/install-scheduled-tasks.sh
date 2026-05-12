#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON_USER="${SUDO_USER:-$(id -un)}"
CONDA_ENV_NAME="my-financing"
PYTHON_BIN=""
ACTION="install"

usage() {
  cat <<'EOF'
Usage: deploy/install-scheduled-tasks.sh [options]

Install or remove local cron jobs for My Financing.

Options:
  --app-dir PATH       Project directory. Defaults to the repository root.
  --conda-env NAME     Conda env that runs the backend. Defaults to my-financing.
  --python-bin PATH    Python executable for the backend env.
  --user USER          Cron user. Defaults to SUDO_USER or the current user.
  --uninstall          Remove My Financing cron jobs.
  -h, --help           Show this help.

Examples:
  sudo deploy/install-scheduled-tasks.sh --user cykkk
  sudo deploy/install-scheduled-tasks.sh --user cykkk --conda-env my-financing
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --conda-env)
      CONDA_ENV_NAME="$2"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --user)
      CRON_USER="$2"
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

if [ "$ACTION" = "install" ]; then
  if [ ! -d "$APP_DIR/backend" ]; then
    echo "Invalid --app-dir: $APP_DIR" >&2
    exit 1
  fi

  if [ -z "$PYTHON_BIN" ]; then
    for prefix in "/home/${CRON_USER}/miniconda3" "/home/${CRON_USER}/anaconda3" "/opt/miniconda3" "/opt/anaconda3"; do
      if [ -x "${prefix}/envs/${CONDA_ENV_NAME}/bin/python" ]; then
        PYTHON_BIN="${prefix}/envs/${CONDA_ENV_NAME}/bin/python"
        break
      fi
    done
  fi

  if [ ! -x "$PYTHON_BIN" ]; then
    echo "Python executable not found. Pass --python-bin or create conda env ${CONDA_ENV_NAME}." >&2
    exit 1
  fi

  mkdir -p "$APP_DIR/logs"
  if [ "$(id -u)" -eq 0 ]; then
    chown "$CRON_USER":"$CRON_USER" "$APP_DIR/logs"
  fi
fi

printf -v BACKEND_DIR_Q "%q" "$APP_DIR/backend"
printf -v PYTHON_BIN_Q "%q" "$PYTHON_BIN"
printf -v DAILY_LOG_Q "%q" "$APP_DIR/logs/daily-update.log"
printf -v DCA_LOG_Q "%q" "$APP_DIR/logs/dca-check.log"

if command -v flock >/dev/null 2>&1; then
  FLOCK_BIN="$(command -v flock)"
  DAILY_COMMAND="${FLOCK_BIN} -n /tmp/my-financing-daily-update.lock bash -lc 'cd ${BACKEND_DIR_Q} && PYTHONPATH=. ${PYTHON_BIN_Q} -m app.jobs.runner daily-update >> ${DAILY_LOG_Q} 2>&1'"
  DCA_COMMAND="${FLOCK_BIN} -n /tmp/my-financing-dca-check.lock bash -lc 'cd ${BACKEND_DIR_Q} && PYTHONPATH=. ${PYTHON_BIN_Q} -m app.jobs.runner dca-check >> ${DCA_LOG_Q} 2>&1'"
else
  DAILY_COMMAND="bash -lc 'cd ${BACKEND_DIR_Q} && PYTHONPATH=. ${PYTHON_BIN_Q} -m app.jobs.runner daily-update >> ${DAILY_LOG_Q} 2>&1'"
  DCA_COMMAND="bash -lc 'cd ${BACKEND_DIR_Q} && PYTHONPATH=. ${PYTHON_BIN_Q} -m app.jobs.runner dca-check >> ${DCA_LOG_Q} 2>&1'"
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
  "${CRONTAB_LIST[@]}" | sed -n '/# BEGIN My Financing scheduled tasks/,/# END My Financing scheduled tasks/p'
else
  echo "Removed My Financing scheduled tasks for user ${CRON_USER}."
fi
