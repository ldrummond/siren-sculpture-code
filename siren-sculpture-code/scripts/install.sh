#!/usr/bin/env bash
set -euo pipefail

# Runtime defaults. Override these at install time with environment variables,
# for example: sudo ENABLE_PROVISIONING=0 ./scripts/install.sh
SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
ENABLE_PROVISIONING="${ENABLE_PROVISIONING:-1}"
ENABLE_BLE_PROVISIONING="${ENABLE_BLE_PROVISIONING:-1}"
ENABLE_BLE_CONTROL="${ENABLE_BLE_CONTROL:-1}"
ENABLE_RPI_CONNECT="${ENABLE_RPI_CONNECT:-1}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must be run as root. Use sudo." >&2
  exit 1
fi

# The runtime user must already exist on the Pi image.
if ! id "${SCULPTURE_USER}" >/dev/null 2>&1; then
  echo "User '${SCULPTURE_USER}' does not exist." >&2
  exit 1
fi

echo "Installing sculpture audio controller for user ${SCULPTURE_USER} in ${APP_DIR}"

# Base packages for Python, audio playback, ALSA inspection, Witty Pi I2C, logs,
# NetworkManager-based BLE provisioning, Bluetooth, and Pi Connect.
apt update
apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  mpv \
  alsa-utils \
  i2c-tools \
  git \
  logrotate \
  curl \
  network-manager \
  bluez \
  rpi-connect-lite

# Runtime log directory lives outside the repo and is rotated by logrotate.
mkdir -p /var/log/sculpture
chown -R "${SCULPTURE_USER}:audio" /var/log/sculpture

# The installed checkout should be writable by the non-root runtime user.
chown -R "${SCULPTURE_USER}:${SCULPTURE_USER}" "${APP_DIR}"

# Install Python dependencies into the repo-local virtualenv used by systemd.
sudo -u "${SCULPTURE_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install --upgrade pip
sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

# Audio services run as the runtime user with access to ALSA devices.
usermod -aG audio "${SCULPTURE_USER}"

# Witty Pi needs I2C. raspi-config is expected on Raspberry Pi OS, but this
# script stays tolerant for non-Pi test environments.
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_i2c 0 || true
else
  echo "raspi-config not found; skipping automatic I2C enable."
fi

# Component-owned setup scripts keep hardware details out of the root installer.
"${APP_DIR}/siren-app/scripts/configure-audio.sh"
"${APP_DIR}/siren-app/scripts/configure-wittypi.sh"

# Configure the Bluetooth adapter for direct BLE provisioning/control services.
if [[ "${ENABLE_BLE_PROVISIONING}" == "1" || "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  "${APP_DIR}/provisioning/scripts/configure-bluetooth.sh"
fi

# Raspberry Pi Connect provides remote shell once the Pi has internet.
if [[ "${ENABLE_RPI_CONNECT}" == "1" ]]; then
  "${APP_DIR}/scripts/configure-connect.sh"
fi

# Host-level log rotation config is shared by the installed services.
cp "${APP_DIR}/config/logrotate-sculpture" /etc/logrotate.d/sculpture

# Install systemd units from each component. Root scripts orchestrate; component
# directories own the units they need.
cp "${APP_DIR}"/siren-app/systemd/*.service /etc/systemd/system/
cp "${APP_DIR}"/siren-app/systemd/*.timer /etc/systemd/system/
cp "${APP_DIR}"/provisioning/systemd/*.service /etc/systemd/system/

# Service templates default to admin. Rewrite installed units only if the image
# uses a different runtime user.
if [[ "${SCULPTURE_USER}" != "admin" ]]; then
  sed -i "s/^User=admin$/User=${SCULPTURE_USER}/" /etc/systemd/system/sculpture-*.service
fi

# Enable siren app services unconditionally.
systemctl daemon-reload
systemctl enable sculpture-audio.service
systemctl enable sculpture-healthcheck.timer
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  systemctl enable sculpture-ble-control.service
else
  systemctl disable --now sculpture-ble-control.service 2>/dev/null || true
fi

# Provisioning is optional. Disabled provisioning stops the BLE provisioning
# service and any stale services from earlier AP-based installs.
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

# Start/restart services after installation so issues are visible immediately.
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

echo
echo "Install complete. A reboot is recommended before field testing."
echo
echo "Useful status commands:"
echo "  systemctl status sculpture-audio.service"
echo "  systemctl status sculpture-healthcheck.timer"
echo "  systemctl status sculpture-ble-provisioning.service"
echo "  systemctl status sculpture-ble-control.service"
echo "  journalctl -u sculpture-audio.service -n 50 --no-pager"
