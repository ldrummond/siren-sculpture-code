#!/usr/bin/env bash
set -euo pipefail

DEST="${1:-/opt/sculpture/log-backups}"
STAMP="$(date +%Y%m%d%H%M%S)"
OUTPUT="${DEST}/sculpture-journal-${STAMP}.log.gz"

mkdir -p "${DEST}"
journalctl \
  -u sculpture-audio.service \
  -u sculpture-ble-control.service \
  -u sculpture-healthcheck.service \
  -u sculpture-wittypi-clock-sync.service \
  --no-pager \
  --output=short-iso | gzip -c > "${OUTPUT}"
echo "Wrote ${OUTPUT}"
