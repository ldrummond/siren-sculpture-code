#!/usr/bin/env bash
set -euo pipefail

# Laptop-side deploy helper. Run this from your Mac to copy the current checkout
# to the Pi, then optionally run the Pi-side deploy script.
PI_HOST="${PI_HOST:-10.10.30.112}"
PI_USER="${PI_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
RUN_INSTALL="${RUN_INSTALL:-0}"
RUN_DEPLOY="${RUN_DEPLOY:-1}"
SYNC_AUDIO="${SYNC_AUDIO:-0}"
SSH_PORT="${SSH_PORT:-22}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REMOTE="${PI_USER}@${PI_HOST}"
SSH_OPTS=(-p "${SSH_PORT}")

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required but was not found." >&2
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ssh is required but was not found." >&2
  exit 1
fi

RSYNC_EXCLUDES=(
  "--exclude=.git/"
  "--exclude=.venv/"
  "--exclude=.env"
  "--exclude=.DS_Store"
  "--exclude=__pycache__/"
  "--exclude=.pytest_cache/"
  "--exclude=logs/"
)

if [[ "${SYNC_AUDIO}" != "1" ]]; then
  RSYNC_EXCLUDES+=(
    "--exclude=siren-app/assets/audio/*.wav"
    "--exclude=siren-app/assets/audio/*.mp3"
    "--exclude=siren-app/assets/audio/*.flac"
    "--exclude=siren-app/assets/audio/*.m4a"
  )
fi

echo "Preparing ${REMOTE}:${APP_DIR}"
ssh "${SSH_OPTS[@]}" "${REMOTE}" "sudo mkdir -p '${APP_DIR}' && sudo chown -R '${PI_USER}:${PI_USER}' '${APP_DIR}'"

echo "Syncing ${REPO_DIR}/ to ${REMOTE}:${APP_DIR}/"
rsync -az --delete --human-readable --info=progress2 \
  -e "ssh -p ${SSH_PORT}" \
  "${RSYNC_EXCLUDES[@]}" \
  "${REPO_DIR}/" \
  "${REMOTE}:${APP_DIR}/"

if [[ "${RUN_INSTALL}" == "1" ]]; then
  echo "Running Pi-side install script"
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "sudo '${APP_DIR}/scripts/install.sh'"
elif [[ "${RUN_DEPLOY}" == "1" ]]; then
  echo "Running Pi-side deploy script"
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "sudo '${APP_DIR}/scripts/deploy.sh'"
else
  echo "Skipping Pi-side deploy. Run this when ready:"
  echo "  ssh -p ${SSH_PORT} ${REMOTE} \"sudo '${APP_DIR}/scripts/deploy.sh'\""
fi
