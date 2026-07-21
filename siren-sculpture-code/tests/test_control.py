from __future__ import annotations

from siren_app import control


def test_format_status_reports_clock_fallback_and_playback_details(monkeypatch) -> None:
    monkeypatch.setattr(control, "_display_timestamp", lambda _value: "recently")
    output = control.format_status(
        {
            "state": "playing",
            "control_mode": "sculpture",
            "normal_paused": False,
            "clock_trusted": False,
            "playback_window": {
                "enabled": True,
                "active": False,
                "start_time": "08:00",
                "stop_time": "20:00",
                "timezone": "America/Denver",
            },
            "volume_percent": 75,
            "file": "/opt/sculpture/audio.wav",
            "sync_restart_at": None,
            "updated_at": 1,
        },
        "active",
    )

    assert "Audio service:      active" in output
    assert "Mode:               Sculpture Mode" in output
    assert "Playback:           playing" in output
    assert "OUT OF SYNC - fallback autoplay" in output
    assert "08:00 to 20:00 America/Denver (inactive now)" in output
    assert "Volume:             75%" in output


def test_send_command_waits_for_matching_acknowledgement(monkeypatch) -> None:
    statuses = iter((None, {"last_command_id": "command-1"}))
    queued: list[str] = []
    monkeypatch.setattr(control, "queue_command", lambda command: queued.append(command) or "command-1")
    monkeypatch.setattr(control, "read_published_status", lambda: next(statuses))
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)

    assert control.send_command("pause", timeout_seconds=1) is True
    assert queued == ["pause_sculpture"]


def test_menu_lists_numbered_sculpture_controls(capsys) -> None:
    control.print_menu()

    output = capsys.readouterr().out
    assert "1) Pause Sculpture Mode" in output
    assert "2) Play Sculpture Mode" in output
    assert "7) Return to Sculpture Mode" in output
    assert "0) Exit" in output
