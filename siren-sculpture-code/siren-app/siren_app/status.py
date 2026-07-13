from __future__ import annotations

import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is optional at runtime.
    psutil = None

from siren_app.config import AppConfig
from siren_app.player import AudioPlayer, read_playback_window, read_published_status
from siren_app.wittypi import get_wittypi_status


def gather_status(config: AppConfig, player: AudioPlayer | None = None) -> dict[str, Any]:
    errors: list[str] = []
    audio_status = player.status().as_dict() if player else _audio_file_status(config)
    disk_path = Path(str(config.get("paths.app_dir", "/")))
    disk = shutil.disk_usage(str(disk_path if disk_path.exists() else Path("/")))
    clock = _clock_status(config, errors)

    return {
        "project": str(config.get("project.name")),
        "audio": audio_status,
        "system": {
            "hostname": platform.node(),
            "uptime_seconds": _uptime_seconds(),
            "disk_free_mb": round(disk.free / 1024 / 1024),
            "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else [0, 0, 0],
        },
        "clock": clock,
        "wittypi": get_wittypi_status(config),
        "errors": errors,
    }


def _audio_file_status(config: AppConfig) -> dict[str, Any]:
    path = Path(str(config.get("audio.file")))
    exists = path.exists()
    published = read_published_status()
    if published and published.get("file") == str(path):
        published["file_exists"] = exists
        published["file_size_mb"] = round(path.stat().st_size / 1024 / 1024, 1) if exists else None
        published.setdefault("playback_window", read_playback_window(config))
        return published
    return {
        "state": "unknown",
        "file": str(path),
        "file_exists": exists,
        "file_size_mb": round(path.stat().st_size / 1024 / 1024, 1) if exists else None,
        "loop": bool(config.get("audio.loop", True)),
        "error": None if exists else f"Audio file does not exist: {path}",
        "playback_window": read_playback_window(config),
    }


def _uptime_seconds() -> int | None:
    if psutil:
        try:
            return round(datetime.now().timestamp() - psutil.boot_time())
        except Exception:
            pass
    try:
        return round(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def _clock_status(config: AppConfig, errors: list[str]) -> dict[str, Any]:
    now = datetime.now().astimezone()
    rtc_time = _read_rtc_time()
    drift_seconds = None
    clock_ok = True
    if rtc_time:
        drift_seconds = abs(round((now - rtc_time).total_seconds()))
        warn_after = int(config.get("healthcheck.clock_drift_warn_seconds", 120) or 120)
        clock_ok = drift_seconds <= warn_after
    return {
        "system_time": now.isoformat(timespec="seconds"),
        "rtc_time": rtc_time.isoformat(timespec="seconds") if rtc_time else None,
        "clock_ok": clock_ok,
        "drift_seconds": drift_seconds,
    }


def _read_rtc_time() -> datetime | None:
    try:
        result = subprocess.run(
            ["hwclock", "--show", "--iso"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone()
    except ValueError:
        return None
