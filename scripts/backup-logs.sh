#!/usr/bin/env bash
set -euo pipefail

DEST="${1:-/opt/sculpture/log-backups}"
STAMP="$(date +%Y%m%d%H%M%S)"

mkdir -p "${DEST}"
tar -czf "${DEST}/sculpture-logs-${STAMP}.tgz" -C /var/log sculpture
echo "Wrote ${DEST}/sculpture-logs-${STAMP}.tgz"
