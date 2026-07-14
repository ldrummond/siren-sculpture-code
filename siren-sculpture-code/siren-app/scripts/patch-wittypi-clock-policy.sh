#!/usr/bin/env bash
set -euo pipefail

# Patch Weird RTC Override Policy from WittyPI

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
WITTYPI_DIR="${WITTYPI_DIR:-/home/${SCULPTURE_USER}/wittypi}"
DAEMON_FILE="${WITTYPI_DIR}/daemon.sh"
CLOCK_TRUST_FILE="${SCULPTURE_CLOCK_TRUST_FILE:-/run/sculpture-clock-trusted}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "patch-wittypi-clock-policy.sh must be run as root. Use sudo." >&2
  exit 1
fi

if [[ ! -f "${DAEMON_FILE}" ]]; then
  echo "Witty Pi daemon not found: ${DAEMON_FILE}" >&2
  exit 1
fi

python3 - "${DAEMON_FILE}" <<'PY'
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


daemon_path = Path(sys.argv[1])
source = daemon_path.read_text(encoding="utf-8")
marker = "SCULPTURE_CLOCK_POLICY_V1"
if marker in source:
    print(f"Witty Pi clock safety policy already installed in {daemon_path}")
    raise SystemExit(0)

vendor_block = """  # synchronize system and RTC time
  if [ $(rtc_has_bad_time) == 1 ]; then
    log 'RTC has bad time, write system time into RTC'
    system_to_rtc
  else
    log 'Seems RTC has good time, write RTC time into system'
    rtc_to_system
  fi
"""

managed_block = """  # SCULPTURE_CLOCK_POLICY_V1
  # Never seed an invalid RTC from an unverified system clock. A separate
  # systemd timer writes system time to the RTC only after confirmed NTP sync.
  clock_trust_file=\"${SCULPTURE_CLOCK_TRUST_FILE:-/run/sculpture-clock-trusted}\"
  rm -f \"$clock_trust_file\"
  rtc_valid=0
  rtc_ts=$(get_rtc_timestamp 2>/dev/null || true)
  if [[ \"$rtc_ts\" =~ ^[0-9]+$ ]]; then
    rtc_year=$(date -d \"@$rtc_ts\" +%Y 2>/dev/null || true)
    if [[ \"$rtc_year\" =~ ^[0-9]{4}$ ]] && (( 10#$rtc_year >= 2020 && 10#$rtc_year <= 2099 )); then
      rtc_valid=1
    fi
  fi

  if (( rtc_valid == 1 )); then
    log 'RTC has plausible time, write RTC time into system'
    rtc_to_system
    touch \"$clock_trust_file\"
  else
    log 'RTC time is invalid; leave RTC unchanged until network time is confirmed'
  fi
"""

if vendor_block not in source:
    raise SystemExit(
        "ERROR: Witty Pi daemon clock block did not match the supported vendor layout. "
        "The daemon was not modified; review the installed Witty Pi version before continuing."
    )

backup_path = daemon_path.with_name(f"{daemon_path.name}.sculpture-original")
if not backup_path.exists():
    shutil.copy2(daemon_path, backup_path)

patched_path = daemon_path.with_name(f".{daemon_path.name}.sculpture-patched")
patched_path.write_text(source.replace(vendor_block, managed_block, 1), encoding="utf-8")
shutil.copymode(daemon_path, patched_path)
os.replace(patched_path, daemon_path)
print(f"Installed Witty Pi clock safety policy in {daemon_path}")
PY

# Preserve trusted playback during an in-place update when the running system
# and RTC already agree. On a fresh or inconsistent clock, the boot daemon or
# confirmed-NTP timer must establish trust instead.
rtc_ts=$(cd "${WITTYPI_DIR}" && bash -c 'source ./utilities.sh >/dev/null 2>&1 && get_rtc_timestamp' 2>/dev/null || true)
system_ts=$(date +%s)
rtc_valid=0
if [[ "${rtc_ts}" =~ ^[0-9]+$ ]]; then
  rtc_year=$(date -d "@${rtc_ts}" +%Y 2>/dev/null || true)
  if [[ "${rtc_year}" =~ ^[0-9]{4}$ ]] && (( 10#${rtc_year} >= 2020 && 10#${rtc_year} <= 2099 )); then
    drift=$((rtc_ts - system_ts))
    if (( drift < 0 )); then
      drift=$((-drift))
    fi
    if (( drift <= 120 )); then
      rtc_valid=1
    fi
  fi
fi

if (( rtc_valid == 1 )); then
  touch "${CLOCK_TRUST_FILE}"
  echo "Current Witty Pi RTC agrees with system time; clock marked trusted."
else
  rm -f "${CLOCK_TRUST_FILE}"
  echo "Current Witty Pi RTC is invalid or differs from system time; clock remains untrusted."
fi
