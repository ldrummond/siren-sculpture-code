#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sculpture}"
PROVISIONING_CONFIG="${PROVISIONING_CONFIG:-${APP_DIR}/provisioning/settings/provisioning.yaml}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "configure-bluetooth.sh must be run as root. Use sudo." >&2
  exit 1
fi

if ! command -v bluetoothctl >/dev/null 2>&1; then
  echo "bluetoothctl not found. Install bluez before enabling the Bluetooth trigger." >&2
  exit 1
fi

ALIAS="SculptureSetup"
if command -v python3 >/dev/null 2>&1 && [[ -f "${PROVISIONING_CONFIG}" ]]; then
  ALIAS="$(python3 -c 'import sys, yaml; data=yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}; print(data.get("triggers", {}).get("bluetooth", {}).get("adapter_alias", "SculptureSetup"))' "${PROVISIONING_CONFIG}" 2>/dev/null || printf 'SculptureSetup')"
fi

systemctl enable bluetooth.service
systemctl restart bluetooth.service

bluetoothctl power on || true
bluetoothctl system-alias "${ALIAS}" || true
bluetoothctl pairable on || true
bluetoothctl discoverable on || true

echo "Bluetooth trigger configured with adapter alias '${ALIAS}'."
echo "BLE provisioning/control services can now advertise through the Bluetooth adapter."
