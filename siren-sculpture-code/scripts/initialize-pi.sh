#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
PROVISIONING_DIR="${PROVISIONING_DIR:-${APP_DIR}/vendor/rpi-ble-wifi-provisioning}"
ENABLE_BLE_CONTROL="${ENABLE_BLE_CONTROL:-1}"
INSTALL_WITTYPI="${INSTALL_WITTYPI:-1}"
DISABLE_UWI="${DISABLE_UWI:-1}"
DISABLE_WIFI="${DISABLE_WIFI:-0}"
DISABLE_HDMI="${DISABLE_HDMI:-1}"

if [ "$(id -u)" -ne 0 ]; then
  echo "initialize-pi.sh must be run as root. Use sudo." >&2
  exit 1
fi

if ! id "${SCULPTURE_USER}" >/dev/null 2>&1; then
  echo "User '${SCULPTURE_USER}' does not exist." >&2
  exit 1
fi

ensure_script_permissions() {
  local script_dir
  for script_dir in "${APP_DIR}/scripts" "${APP_DIR}/siren-app/scripts"; do
    if [[ -d "${script_dir}" ]]; then
      chown -R "${SCULPTURE_USER}:${SCULPTURE_USER}" "${script_dir}" 2>/dev/null || true
      find "${script_dir}" -maxdepth 1 -type f -name "*.sh" -exec chmod 755 {} +
    fi
  done
}

echo
echo "Initializing sculpture audio controller for user ${SCULPTURE_USER} in ${APP_DIR}"
echo "------------------------------------------------"
echo "Installing packages"
echo "------------------------------------------------"
echo

apt update
apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  mpv \
  alsa-utils \
  i2c-tools \
  unzip \
  wget \
  ca-certificates \
  logrotate \
  curl \
  bluez \
  network-manager \
  rfkill

mkdir -p /var/log/sculpture
chown -R "${SCULPTURE_USER}:audio" /var/log/sculpture
mkdir -p /var/lib/sculpture
chown -R "${SCULPTURE_USER}:${SCULPTURE_USER}" /var/lib/sculpture
chown -R "${SCULPTURE_USER}:${SCULPTURE_USER}" "${APP_DIR}"
ensure_script_permissions

if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  if [[ ! -f "${PROVISIONING_DIR}/pyproject.toml" ]]; then
    echo "Missing BLE provisioning package: ${PROVISIONING_DIR}" >&2
    echo "Run sync-to-pi.sh from the shared siren-project folder before initializing." >&2
    exit 1
  fi
  "${APP_DIR}/scripts/check-service-conflicts.sh"
fi

echo
echo "------------------------------------------------"
echo "Checking Bluetooth kernel and adapter state"
echo "------------------------------------------------"
echo
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  "${APP_DIR}/scripts/configure-bluetooth.sh"
fi

echo
echo "------------------------------------------------"
echo "Installing Python dependencies"
echo "------------------------------------------------"
echo
sudo -u "${SCULPTURE_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install --upgrade pip
sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install -e "${PROVISIONING_DIR}"
fi

usermod -aG audio "${SCULPTURE_USER}"

if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_i2c 0 || true
else
  echo "raspi-config not found; skipping automatic I2C enable."
fi

echo
echo "------------------------------------------------"
echo "Configuring audio"
echo "------------------------------------------------"
echo
"${APP_DIR}/siren-app/scripts/configure-audio.sh"

echo
echo "------------------------------------------------"
echo "Installing Witty Pi"
echo "------------------------------------------------"
echo
INSTALL_WITTYPI="${INSTALL_WITTYPI}" DISABLE_UWI="${DISABLE_UWI}" "${APP_DIR}/siren-app/scripts/configure-wittypi.sh"

echo
echo "------------------------------------------------"
echo "Disabling unused services/devices"
echo "------------------------------------------------"
echo
DISABLE_UWI="${DISABLE_UWI}" DISABLE_WIFI="${DISABLE_WIFI}" DISABLE_HDMI="${DISABLE_HDMI}" "${APP_DIR}/scripts/configure-low-power.sh"

cp "${APP_DIR}/config/logrotate-sculpture" /etc/logrotate.d/sculpture

echo
echo "------------------------------------------------"
echo "Starting system services"
echo "------------------------------------------------"
echo
cp "${APP_DIR}"/siren-app/systemd/*.service /etc/systemd/system/
cp "${APP_DIR}"/siren-app/systemd/*.timer /etc/systemd/system/

if [[ "${SCULPTURE_USER}" != "admin" ]]; then
  sed -i "s/^User=admin$/User=${SCULPTURE_USER}/" /etc/systemd/system/sculpture-*.service
fi

systemctl daemon-reload
systemctl enable sculpture-audio.service
systemctl enable sculpture-healthcheck.timer
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  systemctl enable --now NetworkManager.service
  systemctl enable sculpture-ble-control.service
else
  systemctl disable --now sculpture-ble-control.service 2>/dev/null || true
fi

systemctl restart sculpture-audio.service
systemctl restart sculpture-healthcheck.timer
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  systemctl restart sculpture-ble-control.service
fi

echo
echo "Initialization complete. Reboot is recommended before field testing."
echo
echo "Useful status commands:"
echo "  systemctl status bluetooth.service"
echo "  systemctl status sculpture-audio.service"
echo "  systemctl status sculpture-healthcheck.timer"
echo "  systemctl status sculpture-ble-control.service"
echo "  journalctl -u sculpture-ble-control.service -n 50 --no-pager"
