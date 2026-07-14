from __future__ import annotations

from pathlib import Path

import pytest

from siren_app.config import ConfigError, load_config
from siren_app.status import gather_status


def write_config(path: Path, extra: str = "") -> Path:
    path.write_text(
        """
project:
  name: "public-sculpture-audio"
paths:
  app_dir: "/tmp/sculpture"
audio:
  file: "/tmp/sculpture/audio/ambient.wav"
  loop: true
  player: "mpv"
schedule:
  timezone: "America/Denver"
logging:
  level: "INFO"
wittypi:
  enabled: false
healthcheck:
  disk_free_warn_mb: 500
""".strip()
        + extra,
        encoding="utf-8",
    )
    return path


def test_load_config_valid_yaml(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path / "sculpture.yaml"))

    assert config.get("project.name") == "public-sculpture-audio"
    assert config.get("audio.player") == "mpv"


def test_load_config_missing_required_value_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("project:\n  name: test\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="missing required keys"):
        load_config(path)


def test_audio_status_reports_missing_file(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path / "sculpture.yaml"))

    status = gather_status(config)

    assert status["audio"]["file_exists"] is False
    assert "does not exist" in status["audio"]["error"]
