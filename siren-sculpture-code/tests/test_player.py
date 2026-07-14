from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from siren_app.player import AudioPlayer, is_clock_trusted, playback_window_command, queue_command, read_playback_window, write_playback_window


class FakeConfig:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = values or {"schedule.timezone": "America/Denver"}

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def test_build_command_uses_runtime_volume(tmp_path: Path) -> None:
    audio = tmp_path / "tone.wav"
    audio.write_bytes(b"data")
    player = AudioPlayer(
        FakeConfig(
            {
                "audio.file": str(audio),
                "audio.player": "mpv",
                "audio.loop": True,
                "audio.extra_args": ["--no-video"],
                "audio.volume_percent": 80,
            }
        )  # type: ignore[arg-type]
    )

    player.set_volume(35)

    assert "--volume=35" in player.build_command()


def test_build_command_uses_selected_alsa_device(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "tone.wav"
    audio.write_bytes(b"data")
    device_file = tmp_path / "audio-device"
    device_file.write_text("plughw:CARD=Device,DEV=0\n", encoding="utf-8")
    monkeypatch.setattr("siren_app.player.AUDIO_DEVICE_FILE", device_file)

    player = AudioPlayer(
        FakeConfig(
            {
                "audio.file": str(audio),
                "audio.player": "mpv",
                "audio.loop": True,
                "audio.extra_args": ["--no-video", "--ao=alsa"],
            }
        )  # type: ignore[arg-type]
    )

    command = player.build_command()

    assert "--audio-device=alsa/plughw:CARD=Device,DEV=0" in command
    assert "--ao=alsa" not in command


def test_queue_command_accepts_mode_controls_and_volume(tmp_path: Path, monkeypatch) -> None:
    command_file = tmp_path / "command"
    monkeypatch.setattr("siren_app.player.COMMAND_FILE", command_file)

    queue_command("testing_mode")
    assert command_file.read_text(encoding="utf-8") == "testing_mode\n"

    queue_command("play_sculpture")
    assert command_file.read_text(encoding="utf-8") == "play_sculpture\n"

    queue_command("test_restart")
    assert command_file.read_text(encoding="utf-8") == "test_restart\n"

    queue_command("volume:55")
    assert command_file.read_text(encoding="utf-8") == "volume:55\n"


def test_read_playback_window_defaults_to_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("siren_app.player.PLAYBACK_WINDOW_FILE", tmp_path / "window.json")

    window = read_playback_window(FakeConfig())  # type: ignore[arg-type]

    assert window["enabled"] is False
    assert window["active"] is False
    assert window["start_time"] is None


def test_write_playback_window_persists_normalized_times(tmp_path: Path, monkeypatch) -> None:
    window_file = tmp_path / "window.json"
    monkeypatch.setattr("siren_app.player.PLAYBACK_WINDOW_FILE", window_file)

    write_playback_window({"enabled": True, "start_time": "8:00", "stop_time": "21:00"}, FakeConfig())  # type: ignore[arg-type]

    assert json.loads(window_file.read_text(encoding="utf-8")) == {
        "enabled": True,
        "start_time": "08:00",
        "stop_time": "21:00",
        "timezone": "America/Denver",
    }


def test_read_playback_window_reports_active_range(tmp_path: Path, monkeypatch) -> None:
    window_file = tmp_path / "window.json"
    monkeypatch.setattr("siren_app.player.PLAYBACK_WINDOW_FILE", window_file)
    window_file.write_text(
        json.dumps({"enabled": True, "start_time": "08:00", "stop_time": "21:00", "timezone": "America/Denver"}),
        encoding="utf-8",
    )

    active = read_playback_window(FakeConfig(), datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("America/Denver")))  # type: ignore[arg-type]
    inactive = read_playback_window(FakeConfig(), datetime(2026, 7, 13, 22, 0, tzinfo=ZoneInfo("America/Denver")))  # type: ignore[arg-type]

    assert active["active"] is True
    assert inactive["active"] is False


def test_read_playback_window_supports_overnight_range(tmp_path: Path, monkeypatch) -> None:
    window_file = tmp_path / "window.json"
    monkeypatch.setattr("siren_app.player.PLAYBACK_WINDOW_FILE", window_file)
    window_file.write_text(
        json.dumps({"enabled": True, "start_time": "21:00", "stop_time": "08:00", "timezone": "America/Denver"}),
        encoding="utf-8",
    )

    active = read_playback_window(FakeConfig(), datetime(2026, 7, 13, 23, 0, tzinfo=ZoneInfo("America/Denver")))  # type: ignore[arg-type]
    inactive = read_playback_window(FakeConfig(), datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("America/Denver")))  # type: ignore[arg-type]

    assert active["active"] is True
    assert inactive["active"] is False


def test_queue_command_accepts_playback_window_payload(tmp_path: Path, monkeypatch) -> None:
    command_file = tmp_path / "command"
    monkeypatch.setattr("siren_app.player.COMMAND_FILE", command_file)

    command = playback_window_command({"enabled": True, "start_time": "08:00", "stop_time": "21:00"})
    queue_command(command)

    assert command_file.read_text(encoding="utf-8") == command + "\n"


def test_clock_trust_requires_runtime_marker_when_wittypi_is_enabled(tmp_path: Path, monkeypatch) -> None:
    trust_file = tmp_path / "clock-trusted"
    monkeypatch.setattr("siren_app.player.CLOCK_TRUST_FILE", trust_file)
    config = FakeConfig({"wittypi.enabled": True})

    assert is_clock_trusted(config) is False  # type: ignore[arg-type]

    trust_file.touch()

    assert is_clock_trusted(config) is True  # type: ignore[arg-type]


def test_clock_trust_does_not_require_marker_without_wittypi(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("siren_app.player.CLOCK_TRUST_FILE", tmp_path / "missing")

    assert is_clock_trusted(FakeConfig({"wittypi.enabled": False})) is True  # type: ignore[arg-type]
