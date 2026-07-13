from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from siren_app.config import AppConfig


logger = logging.getLogger(__name__)


def is_wittypi_installed(config: AppConfig) -> bool:
    return Path(str(config.get("wittypi.software_dir", "/home/admin/wittypi"))).exists()


def get_recent_wittypi_logs(config: AppConfig, lines: int = 20) -> list[str]:
    software_dir = Path(str(config.get("wittypi.software_dir", "/home/admin/wittypi")))
    candidates = [
        software_dir / "wittyPi.log",
        software_dir / "wittypi.log",
        Path("/var/log/wittypi.log"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            except OSError as exc:
                logger.warning("Unable to read Witty Pi log %s: %s", path, exc)
                return []
    return []


def get_wittypi_status(config: AppConfig) -> dict[str, Any]:
    return {
        "enabled": bool(config.get("wittypi.enabled", False)),
        "detected": is_wittypi_installed(config),
        "voltage": None,
        "current": None,
        "last_log_lines": get_recent_wittypi_logs(config),
    }


def apply_schedule(config: AppConfig, schedule_file: str | None = None) -> bool:
    source = Path(schedule_file or str(config.get("wittypi.schedule_file")))
    software_dir = Path(str(config.get("wittypi.software_dir", "/home/admin/wittypi")))
    if not source.exists():
        logger.error("Witty Pi schedule source not found: %s", source)
        return False
    if not software_dir.exists():
        logger.error("Witty Pi software directory not found: %s", software_dir)
        return False

    target = software_dir / source.name
    if target.exists():
        backup = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup)
        logger.info("Backed up existing Witty Pi schedule %s to %s", target, backup)
    shutil.copy2(source, target)
    logger.info("Copied Witty Pi schedule %s to %s", source, target)
    return True


def sync_system_time_to_rtc(config: AppConfig) -> bool:
    return _run_witty_command(config, ["sudo", "hwclock", "-w"])


def sync_rtc_to_system_time(config: AppConfig) -> bool:
    return _run_witty_command(config, ["sudo", "hwclock", "-s"])


def _run_witty_command(config: AppConfig, command: list[str]) -> bool:
    if not bool(config.get("wittypi.enabled", False)):
        logger.warning("Witty Pi integration disabled; command skipped: %s", command)
        return False
    logger.info("Running Witty Pi time command: %s", " ".join(command))
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.error("Witty Pi command failed: %s", exc)
        return False
