from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


DEFAULT_CONFIG_PATH = "/opt/sculpture/siren-app/config/sculpture.yaml"

REQUIRED_KEYS = (
    "project.name",
    "paths.app_dir",
    "audio.file",
    "audio.loop",
    "audio.player",
    "schedule.timezone",
    "logging.level",
    "wittypi.enabled",
    "healthcheck.disk_free_warn_mb",
)


class ConfigError(RuntimeError):
    """Raised when configuration cannot be loaded or validated."""


@dataclass(frozen=True)
class AppConfig:
    data: dict[str, Any]
    path: Path

    def get(self, dotted_key: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    config_path = Path(path or os.environ.get("SCULPTURE_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Unable to read configuration file {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration file {config_path} must contain a YAML mapping")

    missing = [key for key in REQUIRED_KEYS if _deep_get(raw, key) is None]
    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Configuration file {config_path} is missing required keys: {joined}")

    _validate_timezone(raw, "schedule.timezone")
    return AppConfig(data=raw, path=config_path)


def _deep_get(data: dict[str, Any], dotted_key: str) -> Any:
    value: Any = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _parse_time(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ConfigError(f"Invalid schedule time '{value}'. Expected HH:MM") from exc


def _validate_timezone(data: dict[str, Any], dotted_key: str) -> None:
    value = _deep_get(data, dotted_key)
    if not isinstance(value, str):
        raise ConfigError(f"{dotted_key} must be a timezone string")
    try:
        ZoneInfo(value)
    except Exception as exc:
        raise ConfigError(f"Invalid timezone '{value}'") from exc
