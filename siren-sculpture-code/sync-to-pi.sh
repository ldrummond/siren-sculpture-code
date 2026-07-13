#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISIONING_REPO_DIR="${PROVISIONING_REPO_DIR:-${REPO_DIR}/../rpi-ble-wifi-provisioning}"
DEPLOY_CONFIG="${DEPLOY_CONFIG:-${REPO_DIR}/sync.env}"

# Preserve one-off environment overrides while still allowing sync.env to hold
# the normal defaults for this project.
ENV_PI_HOST="${PI_HOST:-}"
ENV_PI_USER="${PI_USER:-}"
ENV_SSH_PORT="${SSH_PORT:-}"
ENV_APP_DIR="${APP_DIR:-}"
ENV_RUN_INITIALIZE="${RUN_INITIALIZE:-}"
ENV_RUN_INSTALL="${RUN_INSTALL:-}"
ENV_RUN_DEPLOY="${RUN_DEPLOY:-}"
ENV_SYNC_AUDIO="${SYNC_AUDIO:-}"

if [[ -f "${DEPLOY_CONFIG}" ]]; then
  # shellcheck disable=SC1090
  source "${DEPLOY_CONFIG}"
fi

# Laptop-side sync helper. Run this from your Mac to copy the current checkout
# to the Pi, then run the Pi-side install script by default.
PI_HOST="${ENV_PI_HOST:-${PI_HOST:-}}"
PI_USER="${ENV_PI_USER:-${PI_USER:-}}"
SSH_PORT="${ENV_SSH_PORT:-${SSH_PORT:-}}"
APP_DIR="${ENV_APP_DIR:-${APP_DIR:-/opt/sculpture}}"
REMOTE_PROVISIONING_DIR="${APP_DIR}/vendor/rpi-ble-wifi-provisioning"
RUN_INITIALIZE="${ENV_RUN_INITIALIZE:-${RUN_INITIALIZE:-0}}"
RUN_INSTALL="${ENV_RUN_INSTALL:-${RUN_INSTALL:-${RUN_DEPLOY:-1}}}"
SYNC_AUDIO="${ENV_SYNC_AUDIO:-${SYNC_AUDIO:-1}}"

# Backward-compatible alias for older local shells/configs that still export
# RUN_DEPLOY. New config should use RUN_INSTALL.
if [[ -z "${ENV_RUN_INSTALL}" && -n "${ENV_RUN_DEPLOY}" ]]; then
  RUN_INSTALL="${ENV_RUN_DEPLOY}"
fi

missing=()
[[ -n "${PI_HOST}" ]] || missing+=(PI_HOST)
[[ -n "${PI_USER}" ]] || missing+=(PI_USER)
[[ -n "${SSH_PORT}" ]] || missing+=(SSH_PORT)
if (( ${#missing[@]} > 0 )); then
  echo "Missing sync connection setting(s): ${missing[*]}" >&2
  echo "Set them in ${DEPLOY_CONFIG} or pass them as environment variables." >&2
  exit 1
fi

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

if [[ ! -f "${PROVISIONING_REPO_DIR}/pyproject.toml" ]]; then
  echo "Provisioning repo not found at ${PROVISIONING_REPO_DIR}." >&2
  echo "Keep rpi-ble-wifi-provisioning next to siren-sculpture-code or set PROVISIONING_REPO_DIR." >&2
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
  "--exclude=desktop/"
  "--exclude=vendor/"
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

echo "Syncing ${PROVISIONING_REPO_DIR}/ to ${REMOTE}:${REMOTE_PROVISIONING_DIR}/"
ssh "${SSH_OPTS[@]}" "${REMOTE}" "sudo mkdir -p '${REMOTE_PROVISIONING_DIR}' && sudo chown -R '${PI_USER}:${PI_USER}' '${APP_DIR}/vendor'"
rsync -az --delete --human-readable --info=progress2 \
  -e "ssh -p ${SSH_PORT}" \
  "--exclude=.git/" \
  "--exclude=.venv/" \
  "--exclude=.DS_Store" \
  "--exclude=__pycache__/" \
  "--exclude=.pytest_cache/" \
  "--exclude=dist/" \
  "${PROVISIONING_REPO_DIR}/" \
  "${REMOTE}:${REMOTE_PROVISIONING_DIR}/"

if [[ "${RUN_INITIALIZE}" == "1" ]]; then
  echo
  echo "-----------------------------------------------"
  echo "Running Pi-side fresh image initialization script"
  echo "-----------------------------------------------"
  echo 
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "sudo '${APP_DIR}/scripts/initialize-pi.sh'"
elif [[ "${RUN_INSTALL}" == "1" ]]; then
  echo "Running Pi-side install script"
  echo
  echo "-----------------------------------------------"
  echo "Running Pi-side app install script"
  echo "-----------------------------------------------"
  echo 
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "sudo '${APP_DIR}/scripts/install.sh'"
else
  echo
  echo "-----------------------------------------------"
  echo "Skipping Pi-side install. Run one of these when ready:"
  echo "-----------------------------------------------"
  echo 
  echo "  ssh -p ${SSH_PORT} ${REMOTE} \"sudo '${APP_DIR}/scripts/install.sh'\""
  echo "  ssh -p ${SSH_PORT} ${REMOTE} \"sudo '${APP_DIR}/scripts/initialize-pi.sh'\""
fi
