from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from siren_app.config import is_within_schedule, load_config
from siren_app.status import gather_status
from tests.test_config import write_config


def test_schedule_inside_active_window(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path / "sculpture.yaml"))
    now = datetime(2026, 7, 3, 12, 0, tzinfo=ZoneInfo("America/Denver"))

    assert is_within_schedule(config, now) is True


def test_schedule_outside_active_window(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path / "sculpture.yaml"))
    now = datetime(2026, 7, 3, 22, 0, tzinfo=ZoneInfo("America/Denver"))

    assert is_within_schedule(config, now) is False


def test_audio_status_reports_missing_file(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path / "sculpture.yaml"))
    status = gather_status(config)

    assert status["audio"]["file_exists"] is False
    assert "does not exist" in status["audio"]["error"]
