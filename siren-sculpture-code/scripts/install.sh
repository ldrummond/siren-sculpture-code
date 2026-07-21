#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
SCULPTURE_REPO_DIR="${SCULPTURE_REPO_DIR:-}"
PROVISIONING_DIR="${PROVISIONING_DIR:-${APP_DIR}/vendor/rpi-ble-wifi-provisioning}"
WITTYPI_DIR="${WITTYPI_DIR:-/home/${SCULPTURE_USER}/wittypi}"
APPLY_WITTYPI_SCHEDULE="${APPLY_WITTYPI_SCHEDULE:-1}"
ENABLE_WITTYPI_CLOCK_SYNC="${ENABLE_WITTYPI_CLOCK_SYNC:-1}"
ENABLE_BLE_CONTROL="${ENABLE_BLE_CONTROL:-1}"
INSTALL_WITTYPI="${INSTALL_WITTYPI:-0}"
DISABLE_UWI="${DISABLE_UWI:-1}"
DISABLE_WIFI="${DISABLE_WIFI:-0}"
DISABLE_HDMI="${DISABLE_HDMI:-1}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must be run as root. Use sudo." >&2
  exit 1
fi

echo
echo "-----------------------------------------------"
echo "Installing Siren Services on PI..."
echo "-----------------------------------------------"
echo

cd "${APP_DIR}"

ensure_script_permissions() {
  local script_dir
  for script_dir in "${APP_DIR}/scripts" "${APP_DIR}/siren-app/scripts"; do
    if [[ -d "${script_dir}" ]]; then
      chown -R "${SCULPTURE_USER}:${SCULPTURE_USER}" "${script_dir}" 2>/dev/null || true
      find "${script_dir}" -maxdepth 1 -type f -name "*.sh" -exec chmod 755 {} +
    fi
  done
}
ensure_script_permissions
mkdir -p /var/lib/sculpture
chown -R "${SCULPTURE_USER}:${SCULPTURE_USER}" /var/lib/sculpture

if [[ "${ENABLE_BLE_CONTROL}" == "1" && ! -f "${PROVISIONING_DIR}/pyproject.toml" ]]; then
  echo "Missing BLE provisioning package: ${PROVISIONING_DIR}" >&2
  echo "Run sync-to-pi.sh from the shared siren-project folder before installing." >&2
  exit 1
fi

APT_UPDATED=0
ensure_apt_updated() {
  if [[ "${APT_UPDATED}" == "0" ]]; then
    apt update
    APT_UPDATED=1
  fi
}

if ! command -v bluetoothctl >/dev/null 2>&1; then
  ensure_apt_updated
  apt install -y bluez rfkill
fi
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]] && ! command -v nmcli >/dev/null 2>&1; then
  ensure_apt_updated
  apt install -y network-manager
fi
if ! command -v git-lfs >/dev/null 2>&1; then
  ensure_apt_updated
  apt install -y git-lfs
fi
sudo -u "${SCULPTURE_USER}" git lfs install --skip-repo

echo
echo "-----------------------------------------------"
echo "Configuring Bluetooth Service..."
echo "-----------------------------------------------"
echo

if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  "${APP_DIR}/scripts/configure-bluetooth.sh"
fi

if [[ ! -x "${APP_DIR}/.venv/bin/pip" ]]; then
  sudo -u "${SCULPTURE_USER}" python3 -m venv "${APP_DIR}/.venv"
fi
sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  sudo -u "${SCULPTURE_USER}" "${APP_DIR}/.venv/bin/pip" install -e "${PROVISIONING_DIR}"
fi
install -m 0755 "${APP_DIR}/siren-app/scripts/sculpture-control.sh" /usr/local/bin/sculpture-control
install -m 0644 "${APP_DIR}/scripts/sculpture-login-banner.sh" /etc/profile.d/sculpture-login.sh
if [[ -n "${SCULPTURE_REPO_DIR}" ]] && git -C "${SCULPTURE_REPO_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ln -sfn "${SCULPTURE_REPO_DIR}" /etc/sculpture-repo
elif [[ ! -e /etc/sculpture-repo && ! -L /etc/sculpture-repo ]]; then
  echo "Git checkout path was not supplied; the SSH banner will report repository status as unknown."
fi

cp "${APP_DIR}"/siren-app/systemd/*.service /etc/systemd/system/
cp "${APP_DIR}"/siren-app/systemd/*.timer /etc/systemd/system/
if [[ "${SCULPTURE_USER}" != "admin" ]]; then
  sed -i "s/^User=admin$/User=${SCULPTURE_USER}/" /etc/systemd/system/sculpture-*.service
fi
echo
echo "-----------------------------------------------"
echo "Configuring WittyPI Scheduling and Disabling WIFI Interface..."
echo "-----------------------------------------------"
echo

if [[ "${APPLY_WITTYPI_SCHEDULE}" == "1" ]]; then
  INSTALL_WITTYPI="${INSTALL_WITTYPI}" DISABLE_UWI="${DISABLE_UWI}" "${APP_DIR}/siren-app/scripts/configure-wittypi.sh"
elif [[ "${ENABLE_WITTYPI_CLOCK_SYNC}" == "1" && -d "${WITTYPI_DIR}" ]]; then
  SCULPTURE_USER="${SCULPTURE_USER}" WITTYPI_DIR="${WITTYPI_DIR}" \
    "${APP_DIR}/siren-app/scripts/patch-wittypi-clock-policy.sh"
fi

DISABLE_UWI="${DISABLE_UWI}" DISABLE_WIFI="${DISABLE_WIFI}" DISABLE_HDMI="${DISABLE_HDMI}" "${APP_DIR}/scripts/configure-low-power.sh" || true

echo
echo "-----------------------------------------------"
echo "Restarting Audio Service..."
echo "-----------------------------------------------"
echo

systemctl daemon-reload
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  DISABLE_WIFI="${DISABLE_WIFI}" "${APP_DIR}/scripts/configure-networkmanager.sh"
  systemctl enable sculpture-ble-control.service
else
  systemctl disable --now sculpture-ble-control.service 2>/dev/null || true
fi
systemctl restart sculpture-audio.service
systemctl restart sculpture-healthcheck.timer
if [[ "${ENABLE_WITTYPI_CLOCK_SYNC}" == "1" && -d "${WITTYPI_DIR}" ]]; then
  systemctl enable --now sculpture-wittypi-clock-sync.timer
else
  systemctl disable --now sculpture-wittypi-clock-sync.timer 2>/dev/null || true
fi
if [[ "${ENABLE_BLE_CONTROL}" == "1" ]]; then
  systemctl restart sculpture-ble-control.service
fi

echo
echo "-----------------------------------------------"
echo "Install Complete"
echo "Logging Service Statuses"
echo "-----------------------------------------------"
echo

systemctl --no-pager --full status bluetooth.service || true
systemctl --no-pager --full status sculpture-audio.service || true
systemctl --no-pager --full status sculpture-healthcheck.timer || true
systemctl --no-pager --full status sculpture-wittypi-clock-sync.timer || true
systemctl --no-pager --full status sculpture-ble-control.service || true
