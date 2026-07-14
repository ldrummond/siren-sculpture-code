#!/bin/sh
set -eu

INCLUDE_BLUETOOTH="${INCLUDE_BLUETOOTH:-0}"
INCLUDE_NETWORK_MANAGER="${INCLUDE_NETWORK_MANAGER:-0}"
RESET_FAILED="${RESET_FAILED:-1}"

if [ "$(id -u)" != "0" ]; then
  echo "disable-services.sh must be run as root. Use sudo." >&2
  exit 1
fi

unit_is_known() {
  unit="$1"
  systemctl list-unit-files "${unit}" --no-legend 2>/dev/null | grep -q "^${unit}"     || systemctl status "${unit}" >/dev/null 2>&1
}

disable_unit() {
  unit="$1"
  if unit_is_known "${unit}"; then
    echo "- disabling ${unit}"
    systemctl disable --now "${unit}" >/dev/null 2>&1 || true
    if [ "${RESET_FAILED}" = "1" ]; then
      systemctl reset-failed "${unit}" >/dev/null 2>&1 || true
    fi
  else
    echo "- ${unit} not installed"
  fi
}

echo "Disabling sculpture-related services..."

disable_unit sculpture-ble-control.service
disable_unit sculpture-audio.service
disable_unit sculpture-healthcheck.timer
disable_unit sculpture-healthcheck.service
disable_unit sculpture-wittypi-clock-sync.timer
disable_unit sculpture-wittypi-clock-sync.service

# Witty Pi automation and web UI are part of the current deployment footprint.
# Disable them here only for explicit low-level Bluetooth/power debugging.
disable_unit wittypi.service
disable_unit uwi.service

if [ "${INCLUDE_BLUETOOTH}" = "1" ]; then
  disable_unit bluetooth.service
fi

if [ "${INCLUDE_NETWORK_MANAGER}" = "1" ]; then
  disable_unit NetworkManager.service
fi

if command -v service >/dev/null 2>&1; then
  service wittypi stop >/dev/null 2>&1 || true
  service uwi stop >/dev/null 2>&1 || true
fi
if command -v update-rc.d >/dev/null 2>&1; then
  update-rc.d -f wittypi remove >/dev/null 2>&1 || true
  update-rc.d -f uwi remove >/dev/null 2>&1 || true
fi

systemctl daemon-reload

echo
echo "Remaining matching units:"
systemctl list-units --type=service --type=timer --all --no-pager   | grep -E 'sculpture|wittypi|uwi|bluetooth|NetworkManager'   || true

echo
echo "Disable complete. Core bluetooth.service disabled? ${INCLUDE_BLUETOOTH}. NetworkManager disabled? ${INCLUDE_NETWORK_MANAGER}."
