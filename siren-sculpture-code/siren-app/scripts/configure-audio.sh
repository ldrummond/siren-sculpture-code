#!/usr/bin/env bash
set -euo pipefail

SCULPTURE_USER="${SCULPTURE_USER:-admin}"
APP_DIR="${APP_DIR:-/opt/sculpture}"

echo "Detected ALSA playback devices:"
aplay -l || {
  echo "aplay failed. Is alsa-utils installed?" >&2
  exit 1
}

usermod -aG audio "${SCULPTURE_USER}"
SCULPTURE_AUDIO_DEVICE_FILE="/run/sculpture-audio-controller/audio-device" \
  "${APP_DIR}/siren-app/scripts/select-audio-device.sh"

echo "Audio is selected dynamically whenever sculpture-audio.service starts."
echo "Test with: ${APP_DIR}/siren-app/scripts/test-audio.sh"
