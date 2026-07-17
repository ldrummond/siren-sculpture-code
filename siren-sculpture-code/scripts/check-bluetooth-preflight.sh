#!/usr/bin/env bash
set -euo pipefail

ALLOW_BAD_BLE_KERNEL="${ALLOW_BAD_BLE_KERNEL:-0}"
BAD_BLE_KERNEL_PATTERNS="${BAD_BLE_KERNEL_PATTERNS:-6.12.93* 6.18.34* 6.18.37*}"
SKIP_BLE_ADVERTISING_TEST="${SKIP_BLE_ADVERTISING_TEST:-0}"
TEST_NAME="${TEST_NAME:-SirenTest}"
BLE_ADVERTISING_SETTLE_SECONDS="${BLE_ADVERTISING_SETTLE_SECONDS:-4}"

if ! [ "$(id -u)" = 0 ]; then
  echo "check-bluetooth-preflight.sh must be run as root. Use sudo." >&2
  exit 1
fi

kernel="$(uname -r)"
bluez_version="unknown"
if command -v bluetoothctl >/dev/null 2>&1; then
  bluez_version="$(bluetoothctl --version 2>/dev/null | awk '{print $2}' || true)"
fi

kernel_is_known_bad=0
read -r -a bad_kernel_patterns <<<"${BAD_BLE_KERNEL_PATTERNS}"
for pattern in "${bad_kernel_patterns[@]}"; do
  if [[ "${kernel}" == ${pattern} ]]; then
    kernel_is_known_bad=1
    break
  fi
done

if [[ "${kernel_is_known_bad}" == "1" && "${ALLOW_BAD_BLE_KERNEL}" != "1" ]]; then
  cat >&2 <<EOF
ERROR: Bluetooth LE advertising is blocked on this kernel: ${kernel}

Known issue: BlueZ D-Bus advertising fails on Raspberry Pi kernel 6.12.93 and
affected 6.18 builds. The symptom is that LE advertisements fail to register
with org.bluez.Error.Failed / Invalid Parameters (0x0d), so Web Bluetooth
cannot see this device. This failure also occurs with bluetoothctl and is below
the sculpture Python application.

Reference: https://github.com/bluez/bluez/issues/2269
Observed failing kernel: 6.12.93+rpt-rpi-v8
Observed working kernel: 6.12.87+rpt-rpi-v8
Current BlueZ version: ${bluez_version}

Boot a known-working kernel, reboot, and rerun install. Do not rely on a package
update until its newly installed kernel has been booted and uname -r confirms it.
Override only for diagnostics with both ALLOW_BAD_BLE_KERNEL=1 and
SKIP_BLE_ADVERTISING_TEST=1.
EOF
  exit 1
fi

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
      {
        printf 'menu advertise\nclear\nname %s\nback\nadvertise peripheral\n' "${TEST_NAME}"
        sleep "${BLE_ADVERTISING_SETTLE_SECONDS}"
        printf 'advertise off\nquit\n'
      } | timeout 20s bluetoothctl 2>&1
    )" || {
      echo "ERROR: minimal bluetoothctl advertisement command failed:" >&2
      echo "${advertise_output}" >&2
      exit 1
    }

    if grep -Eq "Failed to (register|add) advertisement|Invalid Parameters|org\.bluez\.Error\.Failed" <<<"${advertise_output}"; then
      echo "ERROR: BlueZ rejected a minimal D-Bus LE advertisement:" >&2
      echo "${advertise_output}" >&2
      echo "Kernel: ${kernel}; BlueZ: ${bluez_version}" >&2
      echo "This is a system Bluetooth stack failure, not a sculpture BLE payload failure." >&2
      exit 1
    fi

    if ! grep -Eq "Advertising object registered|Advertising (started|on)" <<<"${advertise_output}"; then
      echo "ERROR: Bluetooth advertising preflight did not see a success marker after ${BLE_ADVERTISING_SETTLE_SECONDS}s." >&2
      echo "${advertise_output}" >&2
      exit 1
    fi
  fi
fi

echo "Bluetooth preflight passed: kernel=${kernel}, bluez=${bluez_version}"
