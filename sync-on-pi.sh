#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCULPTURE_DIR="${SCULPTURE_DIR:-${PROJECT_ROOT}/siren-sculpture-code}"
PROVISIONING_DIR="${PROVISIONING_DIR:-${PROJECT_ROOT}/rpi-ble-wifi-provisioning}"
DEPLOY_CONFIG="${DEPLOY_CONFIG:-${PROJECT_ROOT}/sync.env}"

# Preserve one-off environment overrides while still allowing sync.env to hold
# the normal defaults for this project.
ENV_APP_DIR="${APP_DIR:-}"
ENV_SYNC_AUDIO="${SYNC_AUDIO:-}"

if [[ -f "${DEPLOY_CONFIG}" ]]; then
  # shellcheck disable=SC1090
  source "${DEPLOY_CONFIG}"
fi

# Pi-side sync helper. Run this from a Git checkout on the Pi to copy the
# current checkout into the installed application tree.
APP_DIR="${ENV_APP_DIR:-${APP_DIR:-/opt/sculpture}}"
PROVISIONING_INSTALL_DIR="${APP_DIR}/vendor/rpi-ble-wifi-provisioning"
SYNC_AUDIO="${ENV_SYNC_AUDIO:-${SYNC_AUDIO:-1}}"

prompt_yes_no() {
  local prompt="$1"
  local answer

  while true; do
    read -r -p "${prompt} (yes/no) [no]: " answer
    case "${answer}" in
      y|Y|yes|Yes|YES)
        return 0
        ;;
      ""|n|N|no|No|NO)
        return 1
        ;;
      *)
        echo "Please answer yes or no." >&2
        ;;
    esac
  done
}

normalize_dir() {
  local path="$1"
  local part
  local result=""
  local -a parts=()
  local -a normalized=()

  if [[ -d "${path}" ]]; then
    (cd "${path}" && pwd -P)
    return
  fi

  if [[ "${path}" != /* ]]; then
    path="${PWD}/${path}"
  fi

  IFS="/" read -r -a parts <<< "${path}"
  for part in "${parts[@]}"; do
    case "${part}" in
      ""|.)
        ;;
      ..)
        if (( ${#normalized[@]} > 0 )); then
          unset "normalized[${#normalized[@]}-1]"
        fi
        ;;
      *)
        normalized+=("${part}")
        ;;
    esac
  done

  for part in "${normalized[@]}"; do
    result="${result}/${part}"
  done
  printf '%s\n' "${result:-/}"
}

RUN_INITIALIZE=0
RUN_INSTALL=0
if prompt_yes_no "Is this a fresh install? If so, run the initializer script?"; then
  RUN_INITIALIZE=1
fi
if prompt_yes_no "Deploy and restart services after sync?"; then
  RUN_INSTALL=1
fi

if [[ "${RUN_INITIALIZE}" == "1" && "${RUN_INSTALL}" == "1" ]]; then
  echo "Fresh install selected; the initializer already installs and starts services."
  RUN_INSTALL=0
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required but was not found." >&2
  exit 1
fi

if [[ ! -f "${SCULPTURE_DIR}/pyproject.toml" ]]; then
  echo "Sculpture project not found at ${SCULPTURE_DIR}." >&2
  exit 1
fi

if [[ ! -f "${PROVISIONING_DIR}/pyproject.toml" ]]; then
  echo "Provisioning project not found at ${PROVISIONING_DIR}." >&2
  exit 1
fi

PROJECT_ROOT="$(normalize_dir "${PROJECT_ROOT}")"
SCULPTURE_DIR="$(normalize_dir "${SCULPTURE_DIR}")"
PROVISIONING_DIR="$(normalize_dir "${PROVISIONING_DIR}")"
APP_DIR="$(normalize_dir "${APP_DIR}")"
PROVISIONING_INSTALL_DIR="${APP_DIR}/vendor/rpi-ble-wifi-provisioning"

for source_dir in "${SCULPTURE_DIR}" "${PROVISIONING_DIR}"; do
  case "${source_dir}/" in
    "${APP_DIR}/"*)
      echo "Refusing to sync because source directory ${source_dir} is inside ${APP_DIR}." >&2
      echo "Clone the repository somewhere outside the installed application tree." >&2
      exit 1
      ;;
  esac

  case "${APP_DIR}/" in
    "${source_dir}/"*)
      echo "Refusing to sync because ${APP_DIR} is inside source directory ${source_dir}." >&2
      exit 1
      ;;
  esac
done

if (( EUID == 0 )); then
  SUDO=()
  DEPLOY_USER="${SUDO_USER:-root}"
else
  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required to prepare and install ${APP_DIR}." >&2
    exit 1
  fi
  SUDO=(sudo)
  DEPLOY_USER="$(id -un)"
fi
DEPLOY_GROUP="$(id -gn "${DEPLOY_USER}")"

RSYNC_EXCLUDES=(
  "--exclude=.git/"
  "--exclude=.venv/"
  "--exclude=.env"
  "--exclude=.DS_Store"
  "--exclude=__pycache__/"
  "--exclude=.pytest_cache/"
  "--exclude=logs/"
  "--exclude=desktop/"
  "--exclude=vendor/"
)

if [[ "${SYNC_AUDIO}" != "1" ]]; then
  RSYNC_EXCLUDES+=(
    "--exclude=siren-app/assets/audio/*.wav"
    "--exclude=siren-app/assets/audio/*.mp3"
    "--exclude=siren-app/assets/audio/*.flac"
    "--exclude=siren-app/assets/audio/*.m4a"
  )
fi

echo
echo "-----------------------------------------------"
echo "Preparing ${APP_DIR}"
echo "-----------------------------------------------"
echo
"${SUDO[@]}" mkdir -p "${APP_DIR}"
"${SUDO[@]}" chown -R "${DEPLOY_USER}:${DEPLOY_GROUP}" "${APP_DIR}"

echo
echo "-----------------------------------------------"
echo "Syncing ${SCULPTURE_DIR}/ to ${APP_DIR}/"
echo "-----------------------------------------------"
echo
rsync -az --delete --human-readable --info=progress2 \
  "${RSYNC_EXCLUDES[@]}" \
  "${SCULPTURE_DIR}/" \
  "${APP_DIR}/"

echo
echo "-----------------------------------------------"
echo "Syncing ${PROVISIONING_DIR}/ to ${PROVISIONING_INSTALL_DIR}/"
echo "-----------------------------------------------"
echo
mkdir -p "${PROVISIONING_INSTALL_DIR}"
rsync -az --delete --human-readable --info=progress2 \
  "--exclude=.git/" \
  "--exclude=.venv/" \
  "--exclude=.env" \
  "--exclude=.DS_Store" \
  "--exclude=__pycache__/" \
  "--exclude=.pytest_cache/" \
  "--exclude=dist/" \
  "${PROVISIONING_DIR}/" \
  "${PROVISIONING_INSTALL_DIR}/"

if [[ "${RUN_INITIALIZE}" == "1" ]]; then
  echo
  echo "-----------------------------------------------"
  echo "Running Pi-side fresh image initialization script"
  echo "-----------------------------------------------"
  echo
  "${SUDO[@]}" "${APP_DIR}/scripts/initialize-pi.sh"
elif [[ "${RUN_INSTALL}" == "1" ]]; then
  echo
  echo "-----------------------------------------------"
  echo "Running Pi-side app install script"
  echo "-----------------------------------------------"
  echo
  "${SUDO[@]}" "${APP_DIR}/scripts/install.sh"
else
  echo
  echo "-----------------------------------------------"
  echo "Skipping Pi-side install. Run one of these when ready:"
  echo "-----------------------------------------------"
  echo
  echo "  sudo '${APP_DIR}/scripts/install.sh'"
  echo "  sudo '${APP_DIR}/scripts/initialize-pi.sh'"
fi
