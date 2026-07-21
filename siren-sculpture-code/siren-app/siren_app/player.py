from __future__ import annotations

import argparse
import json
import logging
import math
import os
import secrets
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from siren_app.config import AppConfig, ConfigError, _parse_time, load_config
from siren_app.logging_config import setup_logging


logger = logging.getLogger(__name__)

COMMAND_FILE = Path(os.environ.get("SCULPTURE_COMMAND_FILE", "/run/sculpture-audio-controller/command"))
STATUS_FILE = Path(os.environ.get("SCULPTURE_STATUS_FILE", "/run/sculpture-audio-controller/status.json"))
PLAYBACK_WINDOW_FILE = Path(os.environ.get("SCULPTURE_PLAYBACK_WINDOW_FILE", "/var/lib/sculpture/playback-window.json"))
CLOCK_TRUST_FILE = Path(os.environ.get("SCULPTURE_CLOCK_TRUST_FILE", "/run/sculpture-clock-trusted"))
AUDIO_DEVICE_FILE = Path(
    os.environ.get("SCULPTURE_AUDIO_DEVICE_FILE", "/run/sculpture-audio-controller/audio-device")
)


@dataclass
class PlayerStatus:
    state: str
    file: str
    file_exists: bool
    file_size_mb: float | None
    loop: bool
    volume_percent: int | None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "file": self.file,
            "file_exists": self.file_exists,
            "file_size_mb": self.file_size_mb,
            "loop": self.loop,
            "volume_percent": self.volume_percent,
            "error": self.error,
        }


@dataclass(frozen=True)
class QueuedAudioCommand:
    command_id: str | None
    command: str



def read_playback_window(config: AppConfig, now: Any | None = None) -> dict[str, Any]:
    timezone = str(config.get("schedule.timezone", "UTC"))
    window = {
        "enabled": False,
        "start_time": None,
        "stop_time": None,
        "timezone": timezone,
        "active": False,
        "error": None,
    }
    if not PLAYBACK_WINDOW_FILE.exists():
        return window
    try:
        payload = json.loads(PLAYBACK_WINDOW_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        window["error"] = f"Unable to read playback window: {exc}"
        return window
    if not isinstance(payload, dict):
        window["error"] = "Playback window file must contain a JSON object"
        return window
    window["enabled"] = bool(payload.get("enabled", False))
    window["start_time"] = payload.get("start_time")
    window["stop_time"] = payload.get("stop_time")
    window["timezone"] = str(payload.get("timezone") or timezone)
    if not window["enabled"]:
        return window
    try:
        window["active"] = _is_time_in_range(
            str(window["start_time"]),
            str(window["stop_time"]),
            str(window["timezone"]),
            now,
        )
    except Exception as exc:
        window["active"] = False
        window["error"] = str(exc)
    return window


def write_playback_window(payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    if not payload.get("enabled", True):
        window = {
            "enabled": False,
            "start_time": None,
            "stop_time": None,
            "timezone": str(config.get("schedule.timezone", "UTC")),
        }
    else:
        start_time = _validate_time_string(payload.get("start_time"), "start_time")
        stop_time = _validate_time_string(payload.get("stop_time"), "stop_time")
        timezone = str(payload.get("timezone") or config.get("schedule.timezone", "UTC"))
        _validate_timezone_name(timezone)
        window = {
            "enabled": True,
            "start_time": start_time,
            "stop_time": stop_time,
            "timezone": timezone,
        }
    PLAYBACK_WINDOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAYBACK_WINDOW_FILE.write_text(json.dumps(window, indent=2, sort_keys=True), encoding="utf-8")
    return read_playback_window(config)


def playback_window_command(payload: dict[str, Any]) -> str:
    return "playback_window:" + json.dumps(payload, separators=(",", ":"), sort_keys=True)


def is_clock_trusted(config: AppConfig) -> bool:
    if not bool(config.get("wittypi.enabled", False)):
        return True
    return CLOCK_TRUST_FILE.exists()


def _validate_time_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    try:
        parsed = _parse_time(value.strip())
    except Exception as exc:
        raise ValueError(f"{field_name} must be HH:MM") from exc
    return parsed.strftime("%H:%M")


def _validate_timezone_name(timezone_name: str) -> None:
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"Invalid timezone: {timezone_name}") from exc


def _is_time_in_range(start_time: str, stop_time: str, timezone_name: str, now: Any | None = None) -> bool:
    from zoneinfo import ZoneInfo

    timezone = ZoneInfo(timezone_name)
    current = now.astimezone(timezone) if now else time_datetime_now(timezone)
    start = _parse_time(start_time)
    stop = _parse_time(stop_time)
    current_time = current.time()
    if start <= stop:
        return start <= current_time < stop
    return current_time >= start or current_time < stop


def time_datetime_now(timezone: Any) -> Any:
    return datetime.now(timezone)


def next_sculpture_sync_boundary(
    now: float,
    interval_seconds: int = 300,
    lead_time_seconds: int = 120,
) -> float:
    if interval_seconds <= 0:
        raise ValueError("Sculpture sync interval must be greater than zero")
    if lead_time_seconds < 0:
        raise ValueError("Sculpture sync lead time cannot be negative")
    return math.ceil((now + lead_time_seconds) / interval_seconds) * interval_seconds


class AudioPlayer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.last_error: str | None = None
        self._paused = False
        configured_volume = config.get("audio.volume_percent")
        self.volume_percent = int(configured_volume) if configured_volume is not None else None
        self.alsa_device = self._read_selected_audio_device()

    @staticmethod
    def _read_selected_audio_device() -> str | None:
        try:
            device = AUDIO_DEVICE_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.warning("Audio device selection file does not exist: %s", AUDIO_DEVICE_FILE)
            return None
        except OSError as exc:
            logger.warning("Unable to read audio device selection file %s: %s", AUDIO_DEVICE_FILE, exc)
            return None
        return device or None

    @property
    def audio_file(self) -> Path:
        return Path(str(self.config.get("audio.file")))

    def build_command(self) -> list[str]:
        command = [str(self.config.get("audio.player", "mpv"))]
        extra_args = [str(arg) for arg in self.config.get("audio.extra_args", []) or []]
        if self.alsa_device:
            extra_args = [arg for arg in extra_args if not arg.startswith("--ao=")]
        command.extend(extra_args)
        if self.alsa_device and not any(arg.startswith("--audio-device=") for arg in command):
            command.append(f"--audio-device=alsa/{self.alsa_device}")
        if self.config.get("audio.loop", True) and not any(str(arg).startswith("--loop-file") for arg in command):
            command.append("--loop-file=inf")
        if self.volume_percent is not None:
            command.append(f"--volume={int(self.volume_percent)}")
        command.append(str(self.audio_file))
        return command

    def start(self) -> bool:
        if self.is_running():
            logger.info("Playback already running")
            return True
        if not self.audio_file.exists():
            self.last_error = f"Audio file does not exist: {self.audio_file}"
            logger.error(self.last_error)
            return False

        command = self.build_command()
        logger.info("Starting playback: %s", " ".join(command))
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._paused = False
            self.last_error = None
            return True
        except OSError as exc:
            self.last_error = f"Failed to start player: {exc}"
            logger.exception(self.last_error)
            self.process = None
            return False

    def stop(self) -> None:
        if not self.process:
            self._paused = False
            return
        if self.process.poll() is None:
            logger.info("Stopping playback")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Player did not exit after terminate; killing")
                self.process.kill()
                self.process.wait(timeout=5)
        self._capture_stderr()
        self.process = None
        self._paused = False

    def pause(self) -> None:
        # MVP behavior: pause is implemented as stop. Playback restarts from the
        # beginning when resumed; this avoids relying on mpv IPC in the field.
        logger.info("Pausing playback by stopping player process")
        self.stop()
        self._paused = True

    def resume(self) -> bool:
        logger.info("Resuming playback")
        self._paused = False
        return self.start()

    def restart(self) -> bool:
        logger.info("Restarting playback")
        self.stop()
        return self.start()

    def set_volume(self, volume_percent: int) -> bool:
        volume = max(0, min(100, int(volume_percent)))
        if volume == self.volume_percent:
            return True
        self.volume_percent = volume
        logger.info("Setting playback volume to %s%%", volume)
        if self.is_running():
            return self.restart()
        return True

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def check_process(self) -> int | None:
        if not self.process:
            return None
        return_code = self.process.poll()
        if return_code is not None:
            self._capture_stderr()
            logger.warning("Player process exited with code %s", return_code)
            self.process = None
            self._paused = False
        return return_code

    def status(self) -> PlayerStatus:
        self.check_process()
        file_exists = self.audio_file.exists()
        file_size_mb = round(self.audio_file.stat().st_size / 1024 / 1024, 1) if file_exists else None
        if self.is_running():
            state = "playing"
        elif self._paused:
            state = "paused"
        elif self.last_error:
            state = "error"
        else:
            state = "stopped"
        return PlayerStatus(
            state=state,
            file=str(self.audio_file),
            file_exists=file_exists,
            file_size_mb=file_size_mb,
            loop=bool(self.config.get("audio.loop", True)),
            volume_percent=self.volume_percent,
            error=self.last_error,
        )

    def _capture_stderr(self) -> None:
        if not self.process or not self.process.stderr:
            return
        try:
            output = self.process.stderr.read()
        except OSError:
            return
        if output:
            message = output.decode("utf-8", errors="replace").strip()
            if message:
                self.last_error = message[-1000:]
                logger.warning("Player stderr: %s", self.last_error)


def run_autoplay() -> int:
    config = load_config()
    setup_logging(config)
    player = AudioPlayer(config)
    stopping = False
    manual_override = False
    manual_paused = False
    normal_paused = False
    sync_restart_requested = True
    sync_restart_at: float | None = None
    last_command_id: str | None = None
    last_command: str | None = None
    sync_interval_seconds = int(config.get("audio.sculpture_sync_interval_seconds", 300) or 0)
    sync_lead_time_seconds = int(config.get("audio.sculpture_sync_lead_time_seconds", 120) or 0)
    COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)

    def handle_signal(signum: int, _frame: Any) -> None:
        nonlocal stopping
        logger.info("Received signal %s; shutting down audio supervisor", signum)
        stopping = True
        player.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    logger.info("Sculpture audio supervisor started")

    while not stopping:
        queued_command = _read_command()
        command = queued_command.command if isinstance(queued_command, QueuedAudioCommand) else queued_command
        if command:
            logger.info("Received audio command: %s", command)
            if command == "testing_mode":
                manual_override = True
                manual_paused = True
                normal_paused = False
                sync_restart_requested = False
                sync_restart_at = None
                logger.info("Entering testing mode")
                player.stop()
            elif command == "sculpture_mode":
                manual_override = False
                manual_paused = False
                normal_paused = False
                sync_restart_requested = True
                sync_restart_at = None
                logger.info("Entering sculpture mode")
            elif command == "test_play":
                manual_override = True
                manual_paused = False
                normal_paused = False
                sync_restart_requested = False
                sync_restart_at = None
                player.resume()
            elif command == "test_pause":
                manual_override = True
                manual_paused = True
                normal_paused = False
                sync_restart_requested = False
                sync_restart_at = None
                player.pause()
            elif command == "pause_sculpture":
                manual_override = False
                manual_paused = False
                normal_paused = True
                sync_restart_requested = False
                sync_restart_at = None
                player.stop()
            elif command == "test_restart":
                manual_override = True
                manual_paused = False
                normal_paused = False
                sync_restart_requested = False
                sync_restart_at = None
                player.restart()
            elif command == "play_sculpture":
                manual_override = False
                manual_paused = False
                normal_paused = False
                sync_restart_requested = True
                sync_restart_at = None
                logger.info("Resuming sculpture mode playback")
            elif command.startswith("volume:"):
                try:
                    volume = int(command.split(":", 1)[1])
                    volume_changed_during_sculpture = (
                        volume != player.volume_percent
                        and player.is_running()
                        and not manual_override
                        and not manual_paused
                        and not normal_paused
                    )
                    player.set_volume(volume)
                    if volume_changed_during_sculpture:
                        sync_restart_requested = True
                        sync_restart_at = None
                except ValueError:
                    logger.warning("Ignoring invalid volume command: %s", command)
            elif command.startswith("playback_window:"):
                try:
                    payload = json.loads(command.split(":", 1)[1])
                    if not isinstance(payload, dict):
                        raise ValueError("playback window payload must be an object")
                    write_playback_window(payload, config)
                except (json.JSONDecodeError, OSError, ValueError) as exc:
                    logger.warning("Ignoring invalid playback window command: %s", exc)
            else:
                logger.warning("Ignoring unknown audio command: %s", command)

        playback_window = read_playback_window(config)
        sculpture_window_active = bool(playback_window.get("enabled")) and bool(playback_window.get("active"))
        clock_trusted = is_clock_trusted(config)
        # An untrusted clock cannot safely decide whether a clock-based playback
        # window is active. Fall back to autoplay so a sculpture is not silent,
        # and resume window-based control as soon as the clock is trusted again.
        active = sculpture_window_active if clock_trusted else True
        if not clock_trusted:
            sync_restart_at = None
            sync_restart_requested = True
        player.check_process()
        logger.info("Sculpture Window Active: %s", sculpture_window_active)
        logger.info("Clock Trusted: %s", clock_trusted)

        should_play = not normal_paused and (active or manual_override) and not manual_paused
        sculpture_playing = should_play and not manual_override

        if sculpture_playing and sync_restart_at is not None and time.time() >= sync_restart_at:
            boundary = datetime.fromtimestamp(sync_restart_at).astimezone().isoformat(timespec="seconds")
            logger.info("Restarting sculpture playback at synchronization boundary %s", boundary)
            sync_restart_at = None
            if not player.restart():
                sync_restart_requested = True

        if should_play:
            if not player.is_running():
                sync_restart_at = None
                if player.start() and not manual_override:
                    sync_restart_requested = True
        else:
            sync_restart_at = None
            if player.is_running():
                logger.info("Playback is paused or outside active schedule; stopping playback")
                player.stop()

        if (
            sculpture_playing
            and clock_trusted
            and player.is_running()
            and sync_restart_requested
            and sync_restart_at is None
            and sync_interval_seconds > 0
        ):
            sync_restart_at = next_sculpture_sync_boundary(
                time.time(),
                sync_interval_seconds,
                sync_lead_time_seconds,
            )
            sync_restart_requested = False
            boundary = datetime.fromtimestamp(sync_restart_at).astimezone().isoformat(timespec="seconds")
            logger.info("Sculpture playback will synchronize at %s", boundary)

        status = player.status().as_dict()
        status["manual_override"] = manual_override
        status["manual_paused"] = manual_paused
        status["normal_paused"] = normal_paused
        status["control_mode"] = "testing" if manual_override or manual_paused else "sculpture"
        status["supervisor_mode"] = "manual" if manual_override else "normal_paused" if normal_paused else "schedule"
        status["playback_window"] = playback_window
        status["clock_trusted"] = clock_trusted
        status["sync_restart_at"] = (
            datetime.fromtimestamp(sync_restart_at).astimezone().isoformat(timespec="seconds")
            if sync_restart_at is not None
            else None
        )
        if isinstance(queued_command, QueuedAudioCommand) and queued_command.command_id:
            last_command_id = queued_command.command_id
            last_command = queued_command.command
        if last_command_id:
            status["last_command_id"] = last_command_id
            status["last_command"] = last_command
        _write_status(status)
        if isinstance(queued_command, QueuedAudioCommand):
            _complete_command(queued_command)
        sleep_seconds = 5.0
        if sync_restart_at is not None:
            sleep_seconds = max(0.05, min(sleep_seconds, sync_restart_at - time.time()))
        time.sleep(sleep_seconds)

    _write_status(player.status().as_dict())
    logger.info("Sculpture audio supervisor stopped")
    return 0


def queue_command(command: str) -> str:
    allowed_commands = {
        "testing_mode",
        "sculpture_mode",
        "test_play",
        "test_pause",
        "test_restart",
        "play_sculpture",
        "pause_sculpture",
    }
    if command not in allowed_commands and not command.startswith("volume:") and not command.startswith("playback_window:"):
        raise ValueError(f"Unsupported audio command: {command}")
    COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    command_id = secrets.token_hex(6)
    payload = json.dumps({"id": command_id, "command": command}, separators=(",", ":")) + "\n"
    temporary_file = COMMAND_FILE.with_name(f".{COMMAND_FILE.name}.{command_id}.tmp")
    try:
        temporary_file.write_text(payload, encoding="utf-8")
        try:
            os.link(temporary_file, COMMAND_FILE)
        except FileExistsError as exc:
            raise ValueError("another audio command is still pending") from exc
    finally:
        temporary_file.unlink(missing_ok=True)
    return command_id


def read_published_status() -> dict[str, Any] | None:
    if not STATUS_FILE.exists():
        return None
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_command() -> QueuedAudioCommand | None:
    if not COMMAND_FILE.exists():
        return None
    try:
        raw = COMMAND_FILE.read_text(encoding="utf-8").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return QueuedAudioCommand(None, raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("command"), str):
            raise ValueError("audio command file has an invalid payload")
        command_id = payload.get("id")
        return QueuedAudioCommand(str(command_id) if command_id else None, payload["command"])
    except ValueError as exc:
        logger.warning("Discarding invalid command file %s: %s", COMMAND_FILE, exc)
        COMMAND_FILE.unlink(missing_ok=True)
        return None
    except OSError as exc:
        logger.warning("Unable to read command file %s: %s", COMMAND_FILE, exc)
        return None


def _complete_command(queued_command: QueuedAudioCommand) -> None:
    try:
        current = _read_command()
        if current == queued_command:
            COMMAND_FILE.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Unable to complete command file %s: %s", COMMAND_FILE, exc)


def _write_status(status: dict[str, Any]) -> None:
    payload = dict(status)
    payload["updated_at"] = time.time()
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.warning("Unable to write status file %s: %s", STATUS_FILE, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sculpture audio player")
    parser.add_argument("--autoplay", action="store_true", help="Run as a schedule-aware playback supervisor")
    args = parser.parse_args()

    try:
        if args.autoplay:
            return run_autoplay()
        config = load_config()
        setup_logging(config)
        player = AudioPlayer(config)
        return 0 if player.start() else 1
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
