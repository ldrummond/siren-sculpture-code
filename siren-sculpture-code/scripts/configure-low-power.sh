#!/usr/bin/env bash
set -euo pipefail

DISABLE_UWI="${DISABLE_UWI:-1}"
DISABLE_WIFI="${DISABLE_WIFI:-0}"
DISABLE_BLUETOOTH="${DISABLE_BLUETOOTH:-0}"
DISABLE_HDMI="${DISABLE_HDMI:-1}"

if ! [ $(id -u) = 0 ]; then
  echo "configure-low-power.sh must be run as root. Use sudo." >&2
  exit 1
fi

# Disable UUGear Web Interface
if [[ "${DISABLE_UWI}" == "1" ]]; then
  service uwi stop 2>/dev/null || true
  systemctl disable --now uwi.service 2>/dev/null || true
  update-rc.d -f uwi remove 2>/dev/null || true
fi

if [[ "${DISABLE_WIFI}" == "1" ]]; then
  if command -v nmcli >/dev/null 2>&1; then
    nmcli radio wifi off 2>/dev/null || true
  fi
  if command -v rfkill >/dev/null 2>&1; then
    rfkill block wifi 2>/dev/null || true
  fi
fi

if [[ "${DISABLE_BLUETOOTH}" == "1" ]]; then
  if command -v rfkill >/dev/null 2>&1; then
    rfkill block bluetooth 2>/dev/null || true
  fi
  systemctl disable --now bluetooth.service 2>/dev/null || true
fi

if [[ "${DISABLE_HDMI}" == "1" ]] && command -v vcgencmd >/dev/null 2>&1; then
  vcgencmd display_power 0 >/dev/null 2>&1 || true
fi

echo "Low-power cleanup complete. Disabled? UWI=${DISABLE_UWI}, Wi-Fi=${DISABLE_WIFI}, Bluetooth=${DISABLE_BLUETOOTH}, HDMI=${DISABLE_HDMI}."
