#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sculpture}"
PYTHON="${SCULPTURE_PYTHON:-${APP_DIR}/.venv/bin/python}"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Sculpture Python environment not found: ${PYTHON}" >&2
  echo "Run ${APP_DIR}/scripts/install.sh before using sculpture-control." >&2
  exit 1
fi

export PYTHONPATH="${APP_DIR}/siren-app${PYTHONPATH:+:${PYTHONPATH}}"
export SCULPTURE_CONFIG="${SCULPTURE_CONFIG:-${APP_DIR}/siren-app/config/sculpture.yaml}"

exec "${PYTHON}" -m siren_app.control "$@"
