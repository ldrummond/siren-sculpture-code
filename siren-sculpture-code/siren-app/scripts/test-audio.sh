#!/usr/bin/env bash
set -euo pipefail

AUDIO_FILE="${1:-/opt/sculpture/siren-app/assets/audio/siren-5.wav}"
mpv --no-video --ao=alsa --really-quiet "${AUDIO_FILE}"
