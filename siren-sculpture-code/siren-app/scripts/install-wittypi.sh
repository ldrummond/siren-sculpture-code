#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
WITTYPI_INSTALL_URL="${WITTYPI_INSTALL_URL:-https://www.uugear.com/repo/WittyPi4/install.sh}"
WITTYPI_INSTALL_SCRIPT="${WITTYPI_INSTALL_SCRIPT:-/home/${SCULPTURE_USER}/install-wittypi-standard.sh}"
DISABLE_UWI="${DISABLE_UWI:-1}"

if ! [ $(id -u) = 0 ]; then
  echo "install-wittypi.sh must be run as root. Use sudo." >&2
  exit 1
fi

if ! id "${SCULPTURE_USER}" >/dev/null 2>&1; then
  echo "User '${SCULPTURE_USER}' does not exist." >&2
  exit 1
fi

install_prereqs() {
  apt update
  apt install -y ca-certificates curl wget unzip i2c-tools
}

disable_uwi_service() {
  if [[ "${DISABLE_UWI}" != "1" ]]; then
    return
  fi

  service uwi stop 2>/dev/null || true
  systemctl disable --now uwi.service 2>/dev/null || true
  update-rc.d -f uwi remove 2>/dev/null || true
}

install_prereqs

install_dir="$(dirname "${WITTYPI_INSTALL_SCRIPT}")"
mkdir -p "${install_dir}"
wget "${WITTYPI_INSTALL_URL}" -O "${WITTYPI_INSTALL_SCRIPT}"
chmod +x "${WITTYPI_INSTALL_SCRIPT}"
chown "${SCULPTURE_USER}:$(id -gn "${SCULPTURE_USER}")" "${WITTYPI_INSTALL_SCRIPT}" || true

# The vendor script derives /home/<user>/wittypi from its own path and uses
# SUDO_USER when assigning ownership, so run the downloaded copy from the
# runtime user's home directory with SUDO_USER set explicitly.
(
  cd "${install_dir}"
  SUDO_USER="${SCULPTURE_USER}" bash "${WITTYPI_INSTALL_SCRIPT}"
)

disable_uwi_service

echo "Standard Witty Pi software installed."
echo "UWI web service disabled: ${DISABLE_UWI}."
echo "Reboot before relying on scheduled startup/shutdown."
