#!/usr/bin/env bash
# Pull and deploy the Resume Optimisation Engine on the production VM.
# This script is intentionally run by root via cron; application processes
# themselves always run as the unprivileged `resumeopt` account.
set -Eeuo pipefail

APP_ROOT="/opt/resume-optimizer/app"
APP_USER="resumeopt"
API_SERVICE="resume-optimizer-api.service"
WEB_SERVICE="resume-optimizer-web.service"
MIGRATION_SERVICE="resume-optimizer-migrate.service"
LOCK_FILE="/var/lock/resume-optimizer-deploy.lock"
LOG_FILE="/var/log/resume-optimizer/deploy.log"

mkdir -p "$(dirname "$LOG_FILE")"
exec >>"$LOG_FILE" 2>&1
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "$(date -Is) deployment already running; exiting"; exit 0; }

echo "$(date -Is) starting deployment check"

recover_services() {
  local exit_code=$?
  echo "$(date -Is) deployment failed (exit ${exit_code}); attempting service recovery"
  systemctl start "$API_SERVICE" "$WEB_SERVICE" || true
  exit "$exit_code"
}

if [[ "${1:-}" == "--check" ]]; then
  runuser -u "$APP_USER" -- git -C "$APP_ROOT" fetch --quiet origin main
  runuser -u "$APP_USER" -- git -C "$APP_ROOT" show-ref --verify --quiet refs/remotes/origin/main
  echo "$(date -Is) deployment preflight passed"
  exit 0
fi

# Fetch before disrupting traffic. When main has not advanced, no restart is
# required and the scheduled run completes without downtime.
runuser -u "$APP_USER" -- git -C "$APP_ROOT" fetch --quiet origin main
CURRENT_REVISION="$(runuser -u "$APP_USER" -- git -C "$APP_ROOT" rev-parse HEAD)"
REMOTE_REVISION="$(runuser -u "$APP_USER" -- git -C "$APP_ROOT" rev-parse origin/main)"
if [[ "$CURRENT_REVISION" == "$REMOTE_REVISION" ]]; then
  echo "$(date -Is) main is unchanged (${CURRENT_REVISION:0:12}); no deployment needed"
  exit 0
fi

trap recover_services ERR
echo "$(date -Is) deploying ${CURRENT_REVISION:0:12} -> ${REMOTE_REVISION:0:12}"
systemctl stop "$WEB_SERVICE" "$API_SERVICE"
runuser -u "$APP_USER" -- git -C "$APP_ROOT" pull --ff-only origin main

# Requirements may change with a deployment. Reinstalling from the pinned
# project requirements is idempotent and keeps both runtimes in sync.
"$APP_ROOT/backend/.venv/bin/pip" install --disable-pip-version-check --requirement "$APP_ROOT/backend/requirements.txt"
"$APP_ROOT/frontend/.venv/bin/pip" install --disable-pip-version-check --requirement "$APP_ROOT/frontend/requirements.txt"
runuser -u "$APP_USER" -- "$APP_ROOT/frontend/.venv/bin/python" "$APP_ROOT/frontend/manage.py" collectstatic --noinput

systemctl daemon-reload
systemctl start "$MIGRATION_SERVICE"
systemctl restart "$API_SERVICE" "$WEB_SERVICE"
nginx -t
systemctl reload nginx

trap - ERR
echo "$(date -Is) deployment completed successfully"
