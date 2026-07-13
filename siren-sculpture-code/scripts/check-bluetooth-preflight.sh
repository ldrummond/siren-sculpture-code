#!/usr/bin/env bash
set -euo pipefail

ALLOW_BAD_BLE_KERNEL="${ALLOW_BAD_BLE_KERNEL:-0}"
BAD_BLE_KERNEL_PATTERN="${BAD_BLE_KERNEL_PATTERN:-6.12.93*}"
SKIP_BLE_ADVERTISING_TEST="${SKIP_BLE_ADVERTISING_TEST:-0}"
TEST_NAME="${TEST_NAME:-SirenTest}"
TEST_UUID="${TEST_UUID:-9f0d0001-7b6d-4d2c-9f4f-6f70726f7601}"

if ! [ "$(id -u)" = 0 ]; then
  echo "check-bluetooth-preflight.sh must be run as root. Use sudo." >&2
  exit 1
fi

kernel="$(uname -r)"
bluez_version="unknown"
if command -v bluetoothctl >/dev/null 2>&1; then
  bluez_version="$(bluetoothctl --version 2>/dev/null | awk '{print $2}' || true)"
fi

case "${kernel}" in
  ${BAD_BLE_KERNEL_PATTERN})
    if [[ "${ALLOW_BAD_BLE_KERNEL}" != "1" ]]; then
      cat >&2 <<EOF
ERROR: Bluetooth LE advertising is blocked on this kernel: ${kernel}

Known issue: BlueZ D-Bus advertising fails on Raspberry Pi kernel 6.12.93
with BlueZ 5.79. The symptom is that LE advertisements fail to register with
org.bluez.Error.Failed / Invalid Parameters (0x0d), so Web Bluetooth cannot
see this device.

Reference: https://github.com/bluez/bluez/issues/2269
Observed failing kernel: 6.12.93+rpt-rpi-v8
Observed working kernel: 6.12.87+rpt-rpi-v8
Current BlueZ version: ${bluez_version}

Update or downgrade the Raspberry Pi kernel, reboot, and rerun install.
Override only for diagnostics with: ALLOW_BAD_BLE_KERNEL=1
EOF
      exit 1
    fi
    ;;
esac

if ! command -v bluetoothctl >/dev/null 2>&1; then
  echo "ERROR: bluetoothctl not found. Install bluez before enabling BLE." >&2
  exit 1
fi

if command -v rfkill >/dev/null 2>&1 && rfkill list bluetooth 2>/dev/null | grep -q 'Soft blocked: yes\|Hard blocked: yes'; then
  echo "ERROR: Bluetooth is rfkill-blocked. Run: sudo rfkill unblock bluetooth" >&2
  rfkill list bluetooth >&2 || true
  exit 1
fi

if ! systemctl is-active --quiet bluetooth.service; then
  echo "ERROR: bluetooth.service is not active." >&2
  systemctl --no-pager --full status bluetooth.service >&2 || true
  exit 1
fi

if ! bluetoothctl show >/tmp/sculpture-bluetoothctl-show.txt 2>/tmp/sculpture-bluetoothctl-show.err; then
  echo "ERROR: bluetoothctl cannot read adapter state." >&2
  cat /tmp/sculpture-bluetoothctl-show.err >&2 || true
  exit 1
fi

if ! grep -q 'Powered: yes' /tmp/sculpture-bluetoothctl-show.txt; then
  echo "ERROR: Bluetooth adapter is not powered." >&2
  cat /tmp/sculpture-bluetoothctl-show.txt >&2
  exit 1
fi

if ! grep -q 'Roles:.*peripheral' /tmp/sculpture-bluetoothctl-show.txt; then
  echo "ERROR: Bluetooth adapter does not report the BLE peripheral role required for advertising." >&2
  cat /tmp/sculpture-bluetoothctl-show.txt >&2
  exit 1
fi

if [[ "${SKIP_BLE_ADVERTISING_TEST}" != "1" ]]; then
  if ! command -v timeout >/dev/null 2>&1; then
    echo "WARNING: timeout command not found; skipping minimal BLE advertising test." >&2
  else
    advertise_output="$(
      timeout 20s bluetoothctl 2>&1 <<EOF
menu advertise
clear
name ${TEST_NAME}
uuids ${TEST_UUID}
back
advertise peripheral
advertise off
quit
EOF
    )" || {
      echo "ERROR: minimal bluetoothctl advertisement command failed:" >&2
      echo "${advertise_output}" >&2
      exit 1
    }

    if grep -q "Failed to register advertisement" <<<"${advertise_output}"; then
      echo "ERROR: BlueZ rejected a minimal D-Bus LE advertisement:" >&2
      echo "${advertise_output}" >&2
      exit 1
    fi

    if ! grep -Eq "Advertising object registered|Advertising (started|on)|advertise\.tx-power" <<<"${advertise_output}"; then
      echo "WARNING: Bluetooth advertising preflight did not see a standard success marker." >&2
      echo "${advertise_output}" >&2
      echo "Continuing because bluetoothctl exited successfully." >&2
    fi
  fi
fi

echo "Bluetooth preflight passed: kernel=${kernel}, bluez=${bluez_version}"
