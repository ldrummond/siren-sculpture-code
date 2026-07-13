from __future__ import annotations

from pathlib import Path

import pytest

from siren_app.config import ConfigError, load_config


def write_config(path: Path, extra: str = "") -> Path:
    path.write_text(
        """
project:
  name: "public-sculpture-audio"
paths:
  app_dir: "/tmp/sculpture"
  audio_dir: "/tmp/sculpture/audio"
  log_dir: "/tmp/sculpture/logs"
runtime:
  user: "pi"
  group: "audio"
audio:
  file: "/tmp/sculpture/audio/ambient.wav"
  loop: true
  player: "mpv"
schedule:
  start_time: "07:30"
  stop_time: "19:30"
  timezone: "America/Denver"
logging:
  level: "INFO"
  file: "/tmp/sculpture/logs/sculpture.log"
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
