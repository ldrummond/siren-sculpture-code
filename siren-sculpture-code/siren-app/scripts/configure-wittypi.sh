#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
WITTYPI_DIR="${WITTYPI_DIR:-/home/${SCULPTURE_USER}/wittypi}"
SCHEDULE_FILE="${SCHEDULE_FILE:-${APP_DIR}/siren-app/config/wittypi/schedule.wpi}"
INSTALL_WITTYPI="${INSTALL_WITTYPI:-1}"
DISABLE_UWI="${DISABLE_UWI:-1}"
RUN_WITTYPI_SCHEDULE_NOW="${RUN_WITTYPI_SCHEDULE_NOW:-0}"
ENABLE_WITTYPI_POWER_SCHEDULE="${ENABLE_WITTYPI_POWER_SCHEDULE:-0}"
POWER_ON_WHEN_EXTERNAL_POWER="${POWER_ON_WHEN_EXTERNAL_POWER:-1}"

if [[ "${DISABLE_UWI}" == "1" ]]; then
  service uwi stop 2>/dev/null || true
  systemctl disable --now uwi.service 2>/dev/null || true
  update-rc.d -f uwi remove 2>/dev/null || true
fi

if [[ "${INSTALL_WITTYPI}" == "1" ]]; then
  "${APP_DIR}/siren-app/scripts/install-wittypi.sh"
elif [[ ! -d "${WITTYPI_DIR}" ]]; then
  echo "Witty Pi software directory not found at ${WITTYPI_DIR}."
  echo "Run ${APP_DIR}/siren-app/scripts/install-wittypi.sh, then rerun this script."
  echo "Schedule file to apply later: ${SCHEDULE_FILE}"
  exit 0
fi

SCULPTURE_USER="${SCULPTURE_USER}" WITTYPI_DIR="${WITTYPI_DIR}" \
  "${APP_DIR}/siren-app/scripts/patch-wittypi-clock-policy.sh"

TARGET="${WITTYPI_DIR}/schedule.wpi"
if [[ -f "${TARGET}" ]]; then
  BACKUP="${TARGET}.bak.$(date +%Y%m%d%H%M%S)"
  cp "${TARGET}" "${BACKUP}"
  echo "Backed up existing Witty Pi schedule to ${BACKUP}"
fi

if [[ "${ENABLE_WITTYPI_POWER_SCHEDULE}" == "1" ]]; then
  if [[ ! -f "${SCHEDULE_FILE}" ]]; then
    echo "Schedule file not found: ${SCHEDULE_FILE}" >&2
    exit 1
  fi

  cp "${SCHEDULE_FILE}" "${TARGET}"
  chown "${SCULPTURE_USER}:${SCULPTURE_USER}" "${TARGET}" || true
  echo "Copied Witty Pi schedule to ${TARGET}"

  if [[ "${RUN_WITTYPI_SCHEDULE_NOW}" == "1" && -x "${WITTYPI_DIR}/runScript.sh" ]]; then
    sudo -u "${SCULPTURE_USER}" "${WITTYPI_DIR}/runScript.sh" 0 revise || true
  fi
else
  rm -f "${TARGET}"
  (
    set +u
    cd "${WITTYPI_DIR}"
    # shellcheck disable=SC1091
    source ./utilities.sh
    clear_startup_time
    clear_shutdown_time
    if [[ "${POWER_ON_WHEN_EXTERNAL_POWER}" == "1" ]]; then
      i2c_write "${I2C_BUS}" "${I2C_MC_ADDRESS}" "${I2C_CONF_DEFAULT_ON}" 0x01
    fi
  )
  echo "Disabled Witty Pi scheduled startup and shutdown."
  if [[ "${POWER_ON_WHEN_EXTERNAL_POWER}" == "1" ]]; then
    echo "Configured Witty Pi Default ON when external power is connected."
  fi
fi

echo "UWI web service is disabled; standard Witty Pi tools remain installed."
echo "Reboot to let the Witty Pi daemon load the power policy cleanly."
