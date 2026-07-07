#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
WITTYPI_DIR="${WITTYPI_DIR:-/home/${SCULPTURE_USER}/wittypi}"
SCHEDULE_FILE="${SCHEDULE_FILE:-${APP_DIR}/siren-app/config/wittypi/schedule.wpi}"

if [[ ! -d "${WITTYPI_DIR}" ]]; then
  echo "Witty Pi software directory not found at ${WITTYPI_DIR}."
  echo "Install the Witty Pi software from UUGear, then rerun this script."
  echo "Schedule file to apply later: ${SCHEDULE_FILE}"
  exit 0
fi

if [[ ! -f "${SCHEDULE_FILE}" ]]; then
  echo "Schedule file not found: ${SCHEDULE_FILE}" >&2
  exit 1
fi

TARGET="${WITTYPI_DIR}/$(basename "${SCHEDULE_FILE}")"
if [[ -f "${TARGET}" ]]; then
  BACKUP="${TARGET}.bak.$(date +%Y%m%d%H%M%S)"
  cp "${TARGET}" "${BACKUP}"
  echo "Backed up existing Witty Pi schedule to ${BACKUP}"
fi

cp "${SCHEDULE_FILE}" "${TARGET}"
chown "${SCULPTURE_USER}:${SCULPTURE_USER}" "${TARGET}" || true
echo "Copied Witty Pi schedule to ${TARGET}"
echo "Confirm syntax and activate the schedule with the installed Witty Pi tools."
