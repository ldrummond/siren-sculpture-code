#!/usr/bin/env bash
set -euo pipefail

AUDIO_FILE="${1:-/opt/sculpture/siren-app/assets/audio/siren-5.wav}"
AUDIO_DEVICE_FILE="${SCULPTURE_AUDIO_DEVICE_FILE:-/run/sculpture-audio-controller/audio-device}"
MPV_ARGS=(--no-video --really-quiet)

if [[ -r "${AUDIO_DEVICE_FILE}" ]]; then
  AUDIO_DEVICE="$(tr -d '\r\n' < "${AUDIO_DEVICE_FILE}")"
  MPV_ARGS+=("--audio-device=alsa/${AUDIO_DEVICE}")
fi

mpv "${MPV_ARGS[@]}" "${AUDIO_FILE}"
