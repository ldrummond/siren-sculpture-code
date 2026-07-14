#!/usr/bin/env bash
set -euo pipefail

AUDIO_DEVICE_FILE="${SCULPTURE_AUDIO_DEVICE_FILE:-/run/sculpture-audio-controller/audio-device}"
USB_CARD_PATTERN="${SCULPTURE_USB_CARD_PATTERN:-USB Audio}"
FALLBACK_CARD_PATTERN="${SCULPTURE_FALLBACK_CARD_PATTERN:-bcm2835 Headphones}"
APLAY_LIST_FILE="${APLAY_LIST_FILE:-}"
SKIP_AUDIO_PROBE="${SCULPTURE_SKIP_AUDIO_PROBE:-0}"

list_playback_devices() {
  if [[ -n "${APLAY_LIST_FILE}" ]]; then
    cat "${APLAY_LIST_FILE}"
  else
    aplay -l
  fi
}

find_playback_device() {
  local pattern="$1"

  awk -v pattern="${pattern}" '
    /^card [0-9]+:/ {
      if (index(tolower($0), tolower(pattern)) > 0) {
        card_id = $3
        sub(/:$/, "", card_id)
        for (i = 4; i <= NF; i++) {
          if ($i == "device") {
            device_id = $(i + 1)
            sub(/:$/, "", device_id)
            print card_id ":" device_id
            exit
          }
        }
        exit
      }
    }
  '
}

alsa_device_for_selection() {
  local selection="$1"
  local card_id="${selection%%:*}"
  local device_id="${selection##*:}"

  if [[ ! "${card_id}" =~ ^[A-Za-z0-9_-]+$ || ! "${device_id}" =~ ^[0-9]+$ ]]; then
    echo "Unsafe ALSA playback device detected: ${selection}" >&2
    return 1
  fi
  printf 'plughw:CARD=%s,DEV=%s\n' "${card_id}" "${device_id}"
}

probe_audio_device() {
  local alsa_device="$1"

  if [[ "${SKIP_AUDIO_PROBE}" == "1" ]]; then
    return 0
  fi
  aplay -q -D "${alsa_device}" -t raw -f S16_LE -r 44100 -c 2 -d 1 /dev/zero
}

if ! PLAYBACK_DEVICES="$(list_playback_devices)"; then
  echo "Unable to list ALSA playback devices with aplay." >&2
  exit 1
fi

USB_SELECTION="$(printf '%s\n' "${PLAYBACK_DEVICES}" | find_playback_device "${USB_CARD_PATTERN}")"
FALLBACK_SELECTION="$(printf '%s\n' "${PLAYBACK_DEVICES}" | find_playback_device "${FALLBACK_CARD_PATTERN}")"
ALSA_DEVICE=""
DEVICE_KIND=""

if [[ -n "${USB_SELECTION}" ]]; then
  USB_DEVICE="$(alsa_device_for_selection "${USB_SELECTION}")"
  if probe_audio_device "${USB_DEVICE}"; then
    ALSA_DEVICE="${USB_DEVICE}"
    DEVICE_KIND="USB"
  else
    echo "USB audio output was detected but could not be opened: ${USB_DEVICE}" >&2
  fi
fi

if [[ -z "${ALSA_DEVICE}" && -n "${FALLBACK_SELECTION}" ]]; then
  FALLBACK_DEVICE="$(alsa_device_for_selection "${FALLBACK_SELECTION}")"
  if probe_audio_device "${FALLBACK_DEVICE}"; then
    ALSA_DEVICE="${FALLBACK_DEVICE}"
    DEVICE_KIND="on-board headphones"
  else
    echo "On-board headphone output was detected but could not be opened: ${FALLBACK_DEVICE}" >&2
  fi
fi

if [[ -z "${ALSA_DEVICE}" ]]; then
  echo "No supported audio output found. Expected a USB audio card or bcm2835 Headphones." >&2
  echo "Detected ALSA playback devices:" >&2
  printf '%s\n' "${PLAYBACK_DEVICES}" >&2
  exit 1
fi

install -d -m 0775 "$(dirname "${AUDIO_DEVICE_FILE}")"
TEMP_FILE="${AUDIO_DEVICE_FILE}.tmp"
printf '%s\n' "${ALSA_DEVICE}" > "${TEMP_FILE}"
chmod 0644 "${TEMP_FILE}"
mv "${TEMP_FILE}" "${AUDIO_DEVICE_FILE}"

echo "Selected ${DEVICE_KIND} audio output: ${ALSA_DEVICE}"
