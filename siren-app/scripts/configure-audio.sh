#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"
TEMPLATE="${APP_DIR}/siren-app/config/asound.conf.template"

echo "Detected ALSA playback devices:"
aplay -l || {
  echo "aplay failed. Is alsa-utils installed?" >&2
  exit 1
}

USB_CARD="$(aplay -l | awk '/card [0-9]+:.*USB|card [0-9]+:.*usb/ {gsub(":", "", $2); print $2; exit}')"

if [[ -z "${USB_CARD}" ]]; then
  echo
  read -r -p "USB audio card was not auto-detected. Enter ALSA card number to use: " USB_CARD
fi

if [[ ! "${USB_CARD}" =~ ^[0-9]+$ ]]; then
  echo "Invalid ALSA card number: ${USB_CARD}" >&2
  exit 1
fi

sed "s/CARD_NUMBER/${USB_CARD}/g" "${TEMPLATE}" > /etc/asound.conf
usermod -aG audio "${SCULPTURE_USER}"

echo "Configured /etc/asound.conf to use ALSA card ${USB_CARD}."
echo "Test with: ${APP_DIR}/siren-app/scripts/test-audio.sh"
