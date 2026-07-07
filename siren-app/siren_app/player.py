from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siren_app.config import AppConfig, ConfigError, is_within_schedule, load_config
from siren_app.logging_config import setup_logging


logger = logging.getLogger(__name__)

COMMAND_FILE = Path(os.environ.get("SCULPTURE_COMMAND_FILE", "/tmp/sculpture-audio-controller/command"))
STATUS_FILE = Path(os.environ.get("SCULPTURE_STATUS_FILE", "/tmp/sculpture-audio-controller/status.json"))


@dataclass
class PlayerStatus:
    state: str
    file: str
    file_exists: bool
    file_size_mb: float | None
    loop: bool
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "file": self.file,
            "file_exists": self.file_exists,
            "file_size_mb": self.file_size_mb,
            "loop": self.loop,
            "error": self.error,
        }


class AudioPlayer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.last_error: str | None = None
        self._paused = False

    @property
    def audio_file(self) -> Path:
        return Path(str(self.config.get("audio.file")))

    def build_command(self) -> list[str]:
        command = [str(self.config.get("audio.player", "mpv"))]
        command.extend(str(arg) for arg in self.config.get("audio.extra_args", []) or [])
        if self.config.get("audio.loop", True) and not any(str(arg).startswith("--loop-file") for arg in command):
            command.append("--loop-file=inf")
        volume = self.config.get("audio.volume_percent")
        if volume is not None:
            command.append(f"--volume={int(volume)}")
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
        command = _read_command()
        if command:
            logger.info("Received audio command: %s", command)
            if command == "play":
                manual_override = True
                manual_paused = False
                player.resume()
            elif command == "pause":
                manual_override = True
                manual_paused = True
                player.pause()
            elif command == "stop":
                manual_override = False
                manual_paused = False
                player.stop()
            elif command == "restart":
                manual_override = True
                manual_paused = False
                player.restart()
            elif command == "resume_normal":
                manual_override = False
                manual_paused = False
                logger.info("Resuming normal schedule-guarded playback")
            else:
                logger.warning("Ignoring unknown audio command: %s", command)

        guard_enabled = bool(config.get("schedule.use_app_schedule_guard", True))
        active = is_within_schedule(config) if guard_enabled else True
        player.check_process()

        if (active or manual_override) and not manual_paused:
            if not player.is_running():
                player.start()
        else:
            if player.is_running():
                logger.info("Outside active schedule; stopping playback")
                player.stop()

        status = player.status().as_dict()
        status["manual_override"] = manual_override
        status["manual_paused"] = manual_paused
        status["supervisor_mode"] = "manual" if manual_override else "schedule"
        _write_status(status)
        time.sleep(5)

    _write_status(player.status().as_dict())
    logger.info("Sculpture audio supervisor stopped")
    return 0


def queue_command(command: str) -> None:
    if command not in {"play", "pause", "stop", "restart", "resume_normal"}:
        raise ValueError(f"Unsupported audio command: {command}")
    COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMMAND_FILE.write_text(command + "\n", encoding="utf-8")


def read_published_status() -> dict[str, Any] | None:
    if not STATUS_FILE.exists():
        return None
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_command() -> str | None:
    if not COMMAND_FILE.exists():
        return None
    try:
        command = COMMAND_FILE.read_text(encoding="utf-8").strip()
        COMMAND_FILE.unlink()
        return command
    except OSError as exc:
        logger.warning("Unable to read command file %s: %s", COMMAND_FILE, exc)
        return None


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
