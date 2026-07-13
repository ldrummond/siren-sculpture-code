#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "configure-connect.sh must be run as root. Use sudo." >&2
  exit 1
fi

if ! id "${SCULPTURE_USER}" >/dev/null 2>&1; then
  echo "User '${SCULPTURE_USER}' does not exist." >&2
  exit 1
fi

if ! command -v rpi-connect >/dev/null 2>&1; then
  echo "rpi-connect command not found. Install rpi-connect-lite first." >&2
  exit 1
fi

loginctl enable-linger "${SCULPTURE_USER}" || true

if ! sudo -u "${SCULPTURE_USER}" rpi-connect on; then
  echo "Could not enable Raspberry Pi Connect automatically."
  echo "After logging in as ${SCULPTURE_USER}, run: rpi-connect on"
fi

if [[ -n "${RPI_CONNECT_AUTH_KEY:-}" ]]; then
  USER_HOME="$(getent passwd "${SCULPTURE_USER}" | cut -d: -f6)"
  AUTH_DIR="${USER_HOME}/.config/com.raspberrypi.connect"
  install -d -m 700 -o "${SCULPTURE_USER}" -g "${SCULPTURE_USER}" "${AUTH_DIR}"
  printf '%s\n' "${RPI_CONNECT_AUTH_KEY}" > "${AUTH_DIR}/auth.key"
  chown "${SCULPTURE_USER}:${SCULPTURE_USER}" "${AUTH_DIR}/auth.key"
  chmod 600 "${AUTH_DIR}/auth.key"
  if sudo -u "${SCULPTURE_USER}" rpi-connect signin --auth-key="${RPI_CONNECT_AUTH_KEY}"; then
    echo "Raspberry Pi Connect signed in with provided auth key."
  else
    echo "Raspberry Pi Connect auth key staged for automatic sign-in when internet is available."
  fi
elif [[ -n "${RPI_CONNECT_AUTH_KEY_FILE:-}" ]]; then
  if sudo -u "${SCULPTURE_USER}" rpi-connect signin --auth-key="@${RPI_CONNECT_AUTH_KEY_FILE}"; then
    echo "Raspberry Pi Connect signed in with provided auth key file."
  else
    echo "Raspberry Pi Connect sign-in did not complete. Check network access and rerun rpi-connect signin."
  fi
else
  echo "Raspberry Pi Connect is installed and enabled."
  echo "To link this Pi, run as ${SCULPTURE_USER}: rpi-connect signin"
  echo "Or reinstall with RPI_CONNECT_AUTH_KEY set to a Connect auth key."
fi
