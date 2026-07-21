from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

from siren_app.player import queue_command, read_published_status


COMMANDS = {
    "pause": ("pause_sculpture", "Pause Sculpture Mode"),
    "play": ("play_sculpture", "Play Sculpture Mode"),
    "testing": ("testing_mode", "Switch to Testing Mode"),
    "test-play": ("test_play", "Play test audio"),
    "test-pause": ("test_pause", "Pause test audio"),
    "test-restart": ("test_restart", "Restart test audio"),
    "sculpture": ("sculpture_mode", "Return to Sculpture Mode"),
}

MENU_OPTIONS = {
    "1": "pause",
    "2": "play",
    "3": "testing",
    "4": "test-play",
    "5": "test-pause",
    "6": "test-restart",
    "7": "sculpture",
}


def _service_state() -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "sculpture-audio.service"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _display_time(value: Any) -> str:
    if not value:
        return "none scheduled"
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return str(value)


def _playback_window(status: dict[str, Any]) -> str:
    window = status.get("playback_window")
    if not isinstance(window, dict) or not window.get("enabled"):
        return "disabled"
    active = "active now" if window.get("active") else "inactive now"
    timezone = f" {window.get('timezone')}" if window.get("timezone") else ""
    return f"{window.get('start_time', '--:--')} to {window.get('stop_time', '--:--')}{timezone} ({active})"


def format_status(status: dict[str, Any] | None, service_state: str) -> str:
    lines = [
        "==============================================================================",
        "  Sculpture Audio Control",
        "==============================================================================",
        f"System time:        {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Audio service:      {service_state}",
    ]
    if not status:
        lines.extend(
            (
                "Controller status:  unavailable",
                "",
                "The audio service may still be starting. Check:",
                "  sudo systemctl status sculpture-audio.service",
            )
        )
        return "\n".join(lines)

    testing = status.get("control_mode") == "testing" or bool(status.get("manual_override"))
    if testing:
        mode = "Testing Mode"
    elif status.get("normal_paused"):
        mode = "Sculpture Mode (paused)"
    else:
        mode = "Sculpture Mode"

    trusted = status.get("clock_trusted")
    if trusted is False:
        clock = "OUT OF SYNC - fallback autoplay; send time from blue controller"
    elif trusted is True:
        clock = "trusted"
    else:
        clock = "unknown"

    volume = status.get("volume_percent")
    lines.extend(
        (
            f"Mode:               {mode}",
            f"Playback:           {status.get('state', 'unknown')}",
            f"Clock:              {clock}",
            f"Playback window:    {_playback_window(status)}",
            f"Volume:             {volume}%" if isinstance(volume, int) else "Volume:             unknown",
            f"Audio file:         {status.get('file', 'unknown')}",
            f"Next sync restart:  {_display_time(status.get('sync_restart_at'))}",
            f"Last synchronized:  {_display_time(status.get('last_sync_restart_at'))}",
            f"Status updated:     {_display_timestamp(status.get('updated_at'))}",
        )
    )
    if status.get("error"):
        lines.append(f"Audio error:        {status['error']}")
    return "\n".join(lines)


def _display_timestamp(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "unknown"
    return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def print_status() -> None:
    print(format_status(read_published_status(), _service_state()))


def send_command(alias: str, timeout_seconds: float = 15.0) -> bool:
    command, label = COMMANDS[alias]
    try:
        command_id = queue_command(command)
    except (OSError, ValueError) as exc:
        print(f"Unable to queue {label.lower()}: {exc}", file=sys.stderr)
        return False

    print(f"\n{label} queued. Waiting for the audio service...", flush=True)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = read_published_status()
        if status and status.get("last_command_id") == command_id:
            print(f"{label} completed.")
            return True
        time.sleep(0.25)
    print(
        f"Timed out waiting for {label.lower()}. Check sculpture-audio.service.",
        file=sys.stderr,
    )
    return False


def print_menu() -> None:
    print(
        """
Actions:
  1) Pause Sculpture Mode
  2) Play Sculpture Mode
  3) Switch to Testing Mode
  4) Play test audio
  5) Pause test audio
  6) Restart test audio
  7) Return to Sculpture Mode
  8) Refresh status
  0) Exit
""".rstrip()
    )


def interactive_menu() -> int:
    while True:
        print()
        print_status()
        print_menu()
        try:
            selection = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if selection in {"0", "q", "quit", "exit"}:
            return 0
        if selection == "8":
            continue
        alias = MENU_OPTIONS.get(selection)
        if alias is None:
            print("Invalid selection. Choose a number from 0 to 8.", file=sys.stderr)
            continue
        send_command(alias)


def main() -> int:
    parser = argparse.ArgumentParser(description="View and control sculpture audio playback")
    parser.add_argument(
        "action",
        nargs="?",
        choices=("status", *COMMANDS),
        help="omit to open the interactive menu",
    )
    args = parser.parse_args()
    if args.action is None:
        return interactive_menu()
    if args.action == "status":
        print_status()
        return 0
    return 0 if send_command(args.action) else 1


if __name__ == "__main__":
    raise SystemExit(main())
