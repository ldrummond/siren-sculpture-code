#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sculpture}"
DISABLE_WIFI="${DISABLE_WIFI:-0}"
MIGRATE_LEGACY_WIFI="${MIGRATE_LEGACY_WIFI:-1}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "configure-networkmanager.sh must be run as root. Use sudo." >&2
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "ERROR: NetworkManager is not installed; nmcli was not found." >&2
  exit 1
fi

systemctl enable --now NetworkManager.service

if [[ "${DISABLE_WIFI}" == "1" ]]; then
  echo "NetworkManager enabled; Wi-Fi remains disabled because DISABLE_WIFI=1."
  exit 0
fi

if command -v rfkill >/dev/null 2>&1; then
  rfkill unblock wifi
fi
nmcli networking on
nmcli radio wifi on

if [[ "${MIGRATE_LEGACY_WIFI}" == "1" ]]; then
  python3 "${APP_DIR}/scripts/migrate_legacy_wifi.py"
  nmcli connection reload
fi

if command -v rfkill >/dev/null 2>&1 && rfkill list wifi 2>/dev/null | grep -q "Hard blocked: yes"; then
  echo "WARNING: Wi-Fi is hardware-blocked and cannot be enabled in software." >&2
elif [[ "$(nmcli -t -f WIFI general status)" != "enabled" ]]; then
  echo "WARNING: NetworkManager reports that Wi-Fi is still disabled." >&2
else
  echo "NetworkManager networking and Wi-Fi are enabled."
fi
