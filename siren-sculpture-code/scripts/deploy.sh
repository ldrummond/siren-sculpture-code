#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
APPLY_WITTYPI_SCHEDULE="${APPLY_WITTYPI_SCHEDULE:-1}"
ENABLE_PROVISIONING="${ENABLE_PROVISIONING:-1}"
ENABLE_BLE_PROVISIONING="${ENABLE_BLE_PROVISIONING:-1}"
ENABLE_BLE_CONTROL="${ENABLE_BLE_CONTROL:-1}"
ENABLE_RPI_CONNECT="${ENABLE_RPI_CONNECT:-1}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "deploy.sh must be run as root. Use sudo." >&2
  exit 1
fi

cd "${APP_DIR}"

APT_UPDATED=0
ensure_apt_updated() {
  if [[ "${APT_UPDATED}" == "0" ]]; then
    apt update
    APT_UPDATED=1
  fi
}

if [[ "${ENABLE_PROVISIONING}" == "1" ]] && ! command -v nmcli >/dev/null 2>&1; then
  ensure_apt_updated
  apt install -y network-manager
fi

if [[ "${ENABLE_BLE_PROVISIONING}" == "1" || "${ENABLE_BLE_CONTROL}" == "1" ]] && ! command -v bluetoothctl >/dev/null 2>&1; then
  ensure_apt_updated
  apt install -y bluez
fi

if [[ "${ENABLE_RPI_CONNECT}" == "1" ]] && ! command -v rpi-connect >/dev/null 2>&1; then
  ensure_apt_updated
  apt install -y rpi-connect-lite
fi

if [[ -d .git ]]; then
  git pull --ff-only || true
else
  echo "${APP_DIR} is not a Git checkout; skipping git pull."
fi

if [[ ! -x "${APP_DIR}/.venv/bin/pip" ]]; then
  sudo -u "${SCULPTURE_USER}" python3 -m venv "${APP_DIR}/.venv"
fi
sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

cp "${APP_DIR}"/siren-app/systemd/*.service /etc/systemd/system/
cp "${APP_DIR}"/siren-app/systemd/*.timer /etc/systemd/system/
cp "${APP_DIR}"/provisioning/systemd/*.service /etc/systemd/system/
if [[ "${SCULPTURE_USER}" != "admin" ]]; then
  sed -i "s/^User=admin$/User=${SCULPTURE_USER}/" /etc/systemd/system/sculpture-*.service
fi
cp "${APP_DIR}/config/logrotate-sculpture" /etc/logrotate.d/sculpture

if [[ "${ENABLE_BLE_PROVISIONING}" == "1" || "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  "${APP_DIR}/provisioning/scripts/configure-bluetooth.sh"
fi

if [[ "${ENABLE_RPI_CONNECT}" == "1" ]]; then
  "${APP_DIR}/scripts/configure-connect.sh" || true
fi

if [[ "${APPLY_WITTYPI_SCHEDULE}" == "1" ]]; then
  "${APP_DIR}/siren-app/scripts/configure-wittypi.sh" || true
fi

systemctl daemon-reload
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  systemctl enable sculpture-ble-control.service
else
  systemctl disable --now sculpture-ble-control.service 2>/dev/null || true
fi

if [[ "${ENABLE_PROVISIONING}" == "1" ]]; then
  if [[ "${ENABLE_BLE_PROVISIONING}" == "1" ]]; then
    systemctl enable sculpture-ble-provisioning.service
  else
    systemctl disable --now sculpture-ble-provisioning.service 2>/dev/null || true
  fi
else
  systemctl disable --now sculpture-ble-provisioning.service 2>/dev/null || true
fi
systemctl disable --now sculpture-web.service sculpture-provisioning.service sculpture-provisioning-check.timer sculpture-provisioning-bluetooth-trigger.timer sculpture-provisioning-gpio-trigger.timer 2>/dev/null || true
systemctl restart sculpture-audio.service
systemctl restart sculpture-healthcheck.timer
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  systemctl restart sculpture-ble-control.service
fi
if [[ "${ENABLE_PROVISIONING}" == "1" ]]; then
  if [[ "${ENABLE_BLE_PROVISIONING}" == "1" ]]; then
    systemctl restart sculpture-ble-provisioning.service
  fi
fi

echo "Deploy complete."
systemctl --no-pager --full status sculpture-audio.service || true
systemctl --no-pager --full status sculpture-healthcheck.timer || true
systemctl --no-pager --full status sculpture-ble-provisioning.service || true
systemctl --no-pager --full status sculpture-ble-control.service || true
