#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_CONFIG="${DEPLOY_CONFIG:-${REPO_DIR}/sync.env}"

ENV_PI_HOST="${PI_HOST:-}"
ENV_PI_USER="${PI_USER:-}"
ENV_SSH_PORT="${SSH_PORT:-}"

if [[ -f "${DEPLOY_CONFIG}" ]]; then
  # shellcheck disable=SC1090
  source "${DEPLOY_CONFIG}"
fi

PI_HOST="${ENV_PI_HOST:-${PI_HOST:-}}"
PI_USER="${ENV_PI_USER:-${PI_USER:-}}"
SSH_PORT="${ENV_SSH_PORT:-${SSH_PORT:-}}"

missing=()
[[ -n "${PI_HOST}" ]] || missing+=(PI_HOST)
[[ -n "${PI_USER}" ]] || missing+=(PI_USER)
[[ -n "${SSH_PORT}" ]] || missing+=(SSH_PORT)
if (( ${#missing[@]} > 0 )); then
  echo "Missing Pi connection setting(s): ${missing[*]}" >&2
  echo "Set them in ${DEPLOY_CONFIG} or pass them as environment variables." >&2
  exit 1
fi

REMOTE="${PI_USER}@${PI_HOST}"
SSH_OPTS=(-p "${SSH_PORT}")
SERVICES=(
  bluetooth.service
  sculpture-ble-control.service
  sculpture-audio.service
  sculpture-healthcheck.timer
  sculpture-healthcheck.service
  wittypi.service
  uwi.service
)

if (( $# > 0 )); then
  SERVICES=("$@")
fi

echo "Pi: ${REMOTE}"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo

ssh "${SSH_OPTS[@]}" "${REMOTE}" 'bash -s' -- "${SERVICES[@]}" <<'REMOTE_SCRIPT'
set -u
for service in "$@"; do
  printf '\n========================================\n'
  printf '%s\n' "${service}"
  printf '========================================\n'
  systemctl --no-pager --full status "${service}" || true
done
REMOTE_SCRIPT
