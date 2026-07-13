#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sculpture}"
BLUETOOTH_ALIAS="${BLUETOOTH_ALIAS:-}"
BLUETOOTH_READY_TIMEOUT="${BLUETOOTH_READY_TIMEOUT:-12}"

if ! [ "$(id -u)" = 0 ]; then
  echo "configure-bluetooth.sh must be run as root. Use sudo." >&2
  exit 1
fi

if ! command -v bluetoothctl >/dev/null 2>&1; then
  echo "bluetoothctl not found. Install bluez before enabling Bluetooth." >&2
  exit 1
fi

if [[ -z "${BLUETOOTH_ALIAS}" ]]; then
  BLUETOOTH_ALIAS="$(hostname -s 2>/dev/null || printf 'SculptureControl')"
fi

CONFIG_PATH="${SCULPTURE_CONFIG:-${APP_DIR}/siren-app/config/sculpture.yaml}"
if [[ -f "${CONFIG_PATH}" ]]; then
  CONFIG_DEVICE_NAME="$(awk -F: '/^[[:space:]]*device_name:/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); gsub(/^"|"$/, "", $2); print $2; exit }' "${CONFIG_PATH}")"
  if [[ -n "${CONFIG_DEVICE_NAME}" && "${CONFIG_DEVICE_NAME}" != "auto" && "${CONFIG_DEVICE_NAME}" != "device" && "${CONFIG_DEVICE_NAME}" != "hostname" ]]; then
    BLUETOOTH_ALIAS="${CONFIG_DEVICE_NAME}"
  fi
fi

BLUETOOTH_ALIAS="${BLUETOOTH_ALIAS:0:29}"

show_bluetooth_debug() {
  echo
  echo "Bluetooth debug state:"
  systemctl --no-pager --full status bluetooth.service || true
  if command -v rfkill >/dev/null 2>&1; then
    rfkill list bluetooth || true
  fi
  bluetoothctl show || true
  if command -v btmgmt >/dev/null 2>&1; then
    btmgmt info || true
  fi
  journalctl -u bluetooth.service -b -n 80 --no-pager || true
}

bluetoothctl_retry() {
  local description="$1"
  shift
  local output
  local attempt

  for attempt in 1 2 3 4 5; do
    if output="$(bluetoothctl "$@" 2>&1)"; then
      [[ -n "${output}" ]] && echo "${output}"
      return 0
    fi
    echo "WARNING: bluetoothctl ${description} attempt ${attempt}/5 failed." >&2
    echo "${output}" >&2
    sleep 1
  done

  echo "WARNING: bluetoothctl ${description} failed after retries." >&2
  return 1
}

wait_for_adapter() {
  local attempt
  for attempt in $(seq 1 "${BLUETOOTH_READY_TIMEOUT}"); do
    if bluetoothctl show >/dev/null 2>&1; then
      return 0
    fi
    echo "Waiting for Bluetooth adapter (${attempt}/${BLUETOOTH_READY_TIMEOUT})..."
    sleep 1
  done
  return 1
}

unblock_bluetooth() {
  if ! command -v rfkill >/dev/null 2>&1; then
    return 0
  fi
  rfkill unblock bluetooth || true
  if rfkill list bluetooth 2>/dev/null | grep -q "Soft blocked: yes"; then
    echo "ERROR: Bluetooth is still soft-blocked after rfkill unblock bluetooth." >&2
    rfkill list bluetooth >&2 || true
    exit 1
  fi
}

unblock_bluetooth
systemctl unmask bluetooth.service 2>/dev/null || true
systemctl enable bluetooth.service
systemctl restart bluetooth.service

if ! wait_for_adapter; then
  echo "ERROR: Bluetooth adapter did not become available after restarting bluetooth.service." >&2
  show_bluetooth_debug >&2
  exit 1
fi
unblock_bluetooth

bluetoothctl_retry "power on" power on || true
bluetoothctl_retry "system alias" system-alias "${BLUETOOTH_ALIAS}" || true
bluetoothctl_retry "pairable off" pairable off || true

if ! bluetoothctl show | grep -q "Roles:.*peripheral"; then
  echo "WARNING: Bluetooth adapter does not report BLE peripheral advertising support." >&2
fi

if ! "${APP_DIR}/scripts/check-bluetooth-preflight.sh"; then
  echo
  echo "Bluetooth preflight failed after configuration. Recent bluetooth.service logs follow:" >&2
  show_bluetooth_debug >&2
  exit 1
fi

echo "Bluetooth configured with adapter alias '${BLUETOOTH_ALIAS}'."
echo "Classic discoverable mode is not required; the sculpture service advertises over BLE when systemd starts it."
