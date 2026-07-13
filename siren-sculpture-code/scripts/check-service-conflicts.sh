#!/usr/bin/env bash
set -euo pipefail

CONFLICTING_BLE_SERVICES="${CONFLICTING_BLE_SERVICES:-rpi-ble-wifi-provisioning.service rpi-ble-wifi.service}"

unit_exists() {
  local unit="$1"
  systemctl list-unit-files "${unit}" --no-legend 2>/dev/null | grep -q "^${unit}"     || systemctl status "${unit}" >/dev/null 2>&1
}

unit_conflicts() {
  local unit="$1"
  local active="unknown"
  local enabled="unknown"
  active="$(systemctl is-active "${unit}" 2>/dev/null || true)"
  enabled="$(systemctl is-enabled "${unit}" 2>/dev/null || true)"

  case "${active}:${enabled}" in
    active:*|activating:*|reloading:*|*:enabled|*:enabled-runtime|*:linked|*:linked-runtime)
      return 0
      ;;
  esac
  return 1
}

for unit in ${CONFLICTING_BLE_SERVICES}; do
  if unit_exists "${unit}" && unit_conflicts "${unit}"; then
    cat >&2 <<EOF
ERROR: Conflicting BLE service is active or enabled: ${unit}

Only one BLE GATT advertising service should own the Raspberry Pi Bluetooth
adapter at a time. Disable the Wi-Fi provisioning service before starting the
sculpture BLE control service:

  sudo systemctl disable --now ${unit}
  sudo systemctl reset-failed ${unit}
  sudo systemctl restart sculpture-ble-control.service

EOF
    exit 1
  fi
done
