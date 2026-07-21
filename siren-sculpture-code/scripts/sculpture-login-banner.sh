#!/bin/sh

# This file is sourced by /etc/profile for interactive SSH sessions. Keep it
# POSIX-compatible because /etc/profile can be read by shells other than Bash.
_sculpture_login_banner() {
  if [ "${SCULPTURE_BANNER_FORCE:-0}" != "1" ]; then
    case "$-" in
      *i*) ;;
      *) return 0 ;;
    esac
    [ -n "${SSH_CONNECTION:-}" ] || return 0
  fi

  _sculpture_repo_link="${SCULPTURE_REPO_LINK:-/etc/sculpture-repo}"
  _sculpture_fetch_timeout="${SCULPTURE_GIT_FETCH_TIMEOUT:-5}"

  echo
  echo "Connected to '$(hostname)'"
  echo "Run 'sculpture-control' to view status and control sculpture playback."
  echo

  if [ ! -e "${_sculpture_repo_link}" ]; then
    echo "Repository status: UNKNOWN (Git checkout location is not configured)"
    echo "Run sync-on-pi.sh once with deployment enabled to configure this check."
    echo
    return 0
  fi

  _sculpture_repo_dir="$(readlink -f "${_sculpture_repo_link}" 2>/dev/null || true)"
  if [ -z "${_sculpture_repo_dir}" ] || ! git -C "${_sculpture_repo_dir}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Repository status: UNKNOWN (${_sculpture_repo_dir:-${_sculpture_repo_link}} is not a Git checkout)"
    echo
    return 0
  fi

  _sculpture_upstream="$(git -C "${_sculpture_repo_dir}" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
  if [ -z "${_sculpture_upstream}" ]; then
    echo "Repository status: UNKNOWN (the current branch has no upstream)"
    echo "Checkout: ${_sculpture_repo_dir}"
    echo
    return 0
  fi

  if ! GIT_TERMINAL_PROMPT=0 timeout "${_sculpture_fetch_timeout}" git -C "${_sculpture_repo_dir}" fetch --quiet >/dev/null 2>&1; then
    echo "Repository status: UNKNOWN (remote could not be checked; the Pi may be offline)"
    echo "Checkout: ${_sculpture_repo_dir}"
    echo
    return 0
  fi

  _sculpture_counts="$(git -C "${_sculpture_repo_dir}" rev-list --left-right --count "HEAD...${_sculpture_upstream}" 2>/dev/null || true)"
  _sculpture_ahead="$(printf '%s\n' "${_sculpture_counts}" | awk '{print $1}')"
  _sculpture_behind="$(printf '%s\n' "${_sculpture_counts}" | awk '{print $2}')"
  if [ "${_sculpture_behind:-0}" -gt 0 ] 2>/dev/null; then
    echo "WARNING: siren-sculpture-code is NOT UP TO DATE (${_sculpture_behind} remote commit(s) available)."
    echo "Update the checkout with:"
    echo "  cd '${_sculpture_repo_dir}'"
    echo "  git pull --ff-only"
    echo "  git lfs pull"
    echo "Then deploy it with:"
    echo "  ./sync-on-pi.sh"
  elif [ "${_sculpture_ahead:-0}" -gt 0 ] 2>/dev/null; then
    echo "Repository status: local checkout is ${_sculpture_ahead} commit(s) ahead of ${_sculpture_upstream}."
    echo "Checkout: ${_sculpture_repo_dir}"
  else
    echo "Repository status: siren-sculpture-code is up to date."
    echo "Checkout: ${_sculpture_repo_dir}"
  fi

  if [ -n "$(git -C "${_sculpture_repo_dir}" status --porcelain --untracked-files=normal 2>/dev/null)" ]; then
    echo "Note: the checkout also contains uncommitted changes."
  fi
  echo
}

_sculpture_login_banner
unset -f _sculpture_login_banner 2>/dev/null || true
unset _sculpture_repo_link _sculpture_fetch_timeout _sculpture_repo_dir
unset _sculpture_upstream _sculpture_counts _sculpture_ahead _sculpture_behind
