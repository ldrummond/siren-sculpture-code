#!/usr/bin/env bash
set -eo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
WITTYPI_DIR="${WITTYPI_DIR:-/home/${SCULPTURE_USER}/wittypi}"
CLOCK_TRUST_FILE="${SCULPTURE_CLOCK_TRUST_FILE:-/run/sculpture-clock-trusted}"
NETWORK_SYNC_FILE="${SCULPTURE_NETWORK_SYNC_FILE:-/run/sculpture-wittypi-network-synced}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "sync-wittypi-clock.sh must be run as root. Use sudo." >&2
  exit 1
fi

if [[ ! -f "${WITTYPI_DIR}/utilities.sh" ]]; then
  echo "Witty Pi utilities not found: ${WITTYPI_DIR}/utilities.sh" >&2
  exit 1
fi

# The vendor rtc_to_system function disables NTP. Restore the operating
# system's time synchronization after Witty Pi initializes the system clock.
timedatectl set-ntp true

if [[ -f "${NETWORK_SYNC_FILE}" ]]; then
  exit 0
fi

if [[ "$(timedatectl show --property=NTPSynchronized --value 2>/dev/null)" != "yes" ]]; then
  echo "Network time is not synchronized; leaving the Witty Pi RTC unchanged."
  exit 0
fi

cd "${WITTYPI_DIR}"
# shellcheck disable=SC1091
source ./utilities.sh
system_to_rtc

rtc_ts=$(get_rtc_timestamp 2>/dev/null || true)
system_ts=$(date +%s)
if [[ ! "${rtc_ts}" =~ ^[0-9]+$ ]]; then
  echo "Unable to verify Witty Pi RTC after network synchronization." >&2
  exit 1
fi

drift=$((rtc_ts - system_ts))
if (( drift < 0 )); then
  drift=$((-drift))
fi
if (( drift > 10 )); then
  echo "Witty Pi RTC verification failed: ${drift} seconds from system time." >&2
  exit 1
fi

touch "${CLOCK_TRUST_FILE}" "${NETWORK_SYNC_FILE}"
echo "Witty Pi RTC synchronized from confirmed network time."
