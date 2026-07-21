from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import siren_app.player as player_module
from siren_app.player import (
    AudioPlayer,
    is_clock_trusted,
    next_sculpture_sync_boundary,
    playback_window_command,
    queue_command,
    read_playback_window,
    write_playback_window,
)


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
    command_ids = iter(("first-command", "rejected-command", "second-command"))
    monkeypatch.setattr(player_module.secrets, "token_hex", lambda _length: next(command_ids))

    command_id = queue_command("testing_mode")
    assert json.loads(command_file.read_text(encoding="utf-8")) == {
        "id": command_id,
        "command": "testing_mode",
    }

    with pytest.raises(ValueError, match="another audio command is still pending"):
        queue_command("play_sculpture")

    queued = player_module._read_command()
    assert queued == player_module.QueuedAudioCommand(command_id, "testing_mode")
    player_module._complete_command(queued)
    assert not command_file.exists()

    next_command_id = queue_command("volume:55")
    assert next_command_id == "second-command"


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
    command_id = queue_command(command)

    assert json.loads(command_file.read_text(encoding="utf-8")) == {
        "id": command_id,
        "command": command,
    }


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


@pytest.mark.parametrize(
    ("now", "expected"),
    (
        ((17, 8, 1), (17, 15, 0)),
        ((17, 13, 0), (17, 15, 0)),
        ((17, 13, 1), (17, 20, 0)),
        ((17, 18, 0), (17, 20, 0)),
    ),
)
def test_next_sculpture_sync_boundary_keeps_two_minute_lead_time(
    now: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> None:
    timezone = ZoneInfo("America/Denver")
    current = datetime(2026, 7, 19, *now, tzinfo=timezone)

    boundary = datetime.fromtimestamp(next_sculpture_sync_boundary(current.timestamp()), tz=timezone)

    assert boundary == datetime(2026, 7, 19, *expected, tzinfo=timezone)


def test_next_sculpture_sync_boundary_does_not_reuse_current_mark() -> None:
    now = datetime(2026, 7, 19, 17, 5, tzinfo=ZoneInfo("America/Denver"))

    boundary = datetime.fromtimestamp(
        next_sculpture_sync_boundary(now.timestamp()),
        tz=ZoneInfo("America/Denver"),
    )

    assert boundary == datetime(2026, 7, 19, 17, 10, tzinfo=ZoneInfo("America/Denver"))


def test_next_sculpture_sync_boundary_rejects_disabled_interval() -> None:
    try:
        next_sculpture_sync_boundary(0, 0)
    except ValueError as exc:
        assert str(exc) == "Sculpture sync interval must be greater than zero"
    else:
        raise AssertionError("Expected a disabled sync interval to be rejected")


def test_next_sculpture_sync_boundary_rejects_negative_lead_time() -> None:
    with pytest.raises(ValueError, match="lead time cannot be negative"):
        next_sculpture_sync_boundary(0, 300, -1)


def test_autoplay_publishes_acknowledgement_before_completing_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StopSupervisor(Exception):
        pass

    class FakePlayer:
        def __init__(self, _config: object):
            self.running = False
            self.volume_percent = 80

        def resume(self) -> bool:
            self.running = True
            return True

        def start(self) -> bool:
            self.running = True
            return True

        def stop(self) -> None:
            self.running = False

        def pause(self) -> None:
            self.running = False

        def restart(self) -> bool:
            self.running = True
            return True

        def set_volume(self, volume: int) -> bool:
            self.volume_percent = volume
            return True

        def is_running(self) -> bool:
            return self.running

        def check_process(self) -> None:
            return None

        def status(self) -> object:
            state = "playing" if self.running else "stopped"
            return SimpleNamespace(as_dict=lambda: {"state": state, "file": "audio.wav"})

    queued = player_module.QueuedAudioCommand("abc123", "test_play")
    statuses: list[dict[str, object]] = []
    completed: list[player_module.QueuedAudioCommand] = []
    commands = iter((queued,))

    monkeypatch.setattr(player_module, "load_config", lambda: FakeConfig({
        "audio.sculpture_sync_interval_seconds": 0,
        "audio.sculpture_sync_lead_time_seconds": 0,
    }))
    monkeypatch.setattr(player_module, "setup_logging", lambda _config: None)
    monkeypatch.setattr(player_module, "AudioPlayer", FakePlayer)
    monkeypatch.setattr(player_module, "_read_command", lambda: next(commands, None))
    monkeypatch.setattr(player_module, "_complete_command", completed.append)
    monkeypatch.setattr(player_module, "read_playback_window", lambda _config: {"enabled": False, "active": False})
    monkeypatch.setattr(player_module, "is_clock_trusted", lambda _config: True)
    monkeypatch.setattr(player_module, "_write_status", lambda status: statuses.append(dict(status)))
    monkeypatch.setattr(player_module.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(player_module.time, "sleep", lambda _seconds: (_ for _ in ()).throw(StopSupervisor))
    monkeypatch.setattr(player_module, "COMMAND_FILE", tmp_path / "command")
    monkeypatch.setattr(player_module, "STATUS_FILE", tmp_path / "status.json")

    with pytest.raises(StopSupervisor):
        player_module.run_autoplay()

    assert statuses[-1]["last_command_id"] == "abc123"
    assert statuses[-1]["last_command"] == "test_play"
    assert statuses[-1]["state"] == "playing"
    assert completed == [queued]


def test_untrusted_clock_falls_back_to_autoplay_without_scheduled_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StopSupervisor(Exception):
        pass

    class FakePlayer:
        def __init__(self, _config: object):
            self.running = False
            self.volume_percent = 80

        def start(self) -> bool:
            self.running = True
            return True

        def stop(self) -> None:
            self.running = False

        def restart(self) -> bool:
            raise AssertionError("an untrusted clock must not schedule a synchronization restart")

        def set_volume(self, volume: int) -> bool:
            self.volume_percent = volume
            return True

        def is_running(self) -> bool:
            return self.running

        def check_process(self) -> None:
            return None

        def status(self) -> object:
            state = "playing" if self.running else "stopped"
            return SimpleNamespace(as_dict=lambda: {"state": state})

    statuses: list[dict[str, object]] = []
    config = FakeConfig(
        {
            "audio.sculpture_sync_interval_seconds": 300,
            "audio.sculpture_sync_lead_time_seconds": 120,
        }
    )
    monkeypatch.setattr(player_module, "load_config", lambda: config)
    monkeypatch.setattr(player_module, "setup_logging", lambda _config: None)
    monkeypatch.setattr(player_module, "AudioPlayer", FakePlayer)
    monkeypatch.setattr(player_module, "_read_command", lambda: None)
    monkeypatch.setattr(
        player_module,
        "read_playback_window",
        lambda _config: {"enabled": True, "active": False},
    )
    monkeypatch.setattr(player_module, "is_clock_trusted", lambda _config: False)
    monkeypatch.setattr(player_module, "_write_status", lambda status: statuses.append(dict(status)))
    monkeypatch.setattr(player_module.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(player_module.time, "sleep", lambda _seconds: (_ for _ in ()).throw(StopSupervisor))
    monkeypatch.setattr(player_module, "COMMAND_FILE", tmp_path / "command")
    monkeypatch.setattr(player_module, "STATUS_FILE", tmp_path / "status.json")

    with pytest.raises(StopSupervisor):
        player_module.run_autoplay()

    assert statuses[-1]["state"] == "playing"
    assert statuses[-1]["clock_trusted"] is False
    assert statuses[-1]["sync_restart_at"] is None


@pytest.mark.parametrize(
    ("commands", "initial_time"),
    (
        ([], 2.4),
        (["pause_sculpture", "play_sculpture"], -2.6),
        (["testing_mode", "test_play", "sculpture_mode"], -7.6),
    ),
)
def test_sculpture_playback_restarts_once_at_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    commands: list[str],
    initial_time: float,
) -> None:
    class StopSupervisor(Exception):
        pass

    class FakePlayer:
        instance: "FakePlayer"

        def __init__(self, _config: object):
            self.running = False
            self.start_calls = 0
            self.restart_calls = 0
            self.volume_percent = 80
            FakePlayer.instance = self

        def start(self) -> bool:
            self.running = True
            self.start_calls += 1
            return True

        def stop(self) -> None:
            self.running = False

        def pause(self) -> None:
            self.running = False

        def resume(self) -> bool:
            return self.start()

        def restart(self) -> bool:
            self.running = True
            self.restart_calls += 1
            return True

        def set_volume(self, volume: int) -> bool:
            self.volume_percent = volume
            return True

        def is_running(self) -> bool:
            return self.running

        def check_process(self) -> None:
            return None

        def status(self) -> object:
            state = "playing" if self.running else "stopped"
            return SimpleNamespace(as_dict=lambda: {"state": state})

    queued_commands = iter(commands)
    clock = [initial_time]
    statuses: list[dict[str, object]] = []

    def read_command() -> str | None:
        return next(queued_commands, None)

    def sleep(seconds: float) -> None:
        clock[0] += seconds
        if FakePlayer.instance.restart_calls:
            raise StopSupervisor

    config = FakeConfig(
        {
            "audio.sculpture_sync_interval_seconds": 5,
            "audio.sculpture_sync_lead_time_seconds": 2,
        }
    )
    monkeypatch.setattr(player_module, "load_config", lambda: config)
    monkeypatch.setattr(player_module, "setup_logging", lambda _config: None)
    monkeypatch.setattr(player_module, "AudioPlayer", FakePlayer)
    monkeypatch.setattr(player_module, "_read_command", read_command)
    monkeypatch.setattr(
        player_module,
        "read_playback_window",
        lambda _config: {"enabled": True, "active": True},
    )
    monkeypatch.setattr(player_module, "is_clock_trusted", lambda _config: True)
    monkeypatch.setattr(player_module, "_write_status", lambda status: statuses.append(dict(status)))
    monkeypatch.setattr(player_module.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(player_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(player_module.time, "sleep", sleep)
    monkeypatch.setattr(player_module, "COMMAND_FILE", tmp_path / "command")
    monkeypatch.setattr(player_module, "STATUS_FILE", tmp_path / "status.json")

    with pytest.raises(StopSupervisor):
        player_module.run_autoplay()

    assert FakePlayer.instance.start_calls == 1
    assert FakePlayer.instance.restart_calls == 1
    assert clock[0] == pytest.approx(10.0)
    assert statuses[-1]["sync_restart_at"] is None
    assert datetime.fromisoformat(str(statuses[-1]["last_sync_restart_at"])).timestamp() == 5
