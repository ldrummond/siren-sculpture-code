from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from siren_app.config import AppConfig


logger = logging.getLogger(__name__)

UTILITY_FUNCTIONS = frozenset({"get_temperature", "get_rtc_time"})
RTC_TIME_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
TEMPERATURE_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:\u00b0|deg|C|$)", re.IGNORECASE)
CLOCK_TRUST_FILE = Path(os.environ.get("SCULPTURE_CLOCK_TRUST_FILE", "/run/sculpture-clock-trusted"))
CLOCK_SOURCE_FILE = Path(os.environ.get("SCULPTURE_CLOCK_SOURCE_FILE", "/run/sculpture-clock-source.json"))


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
    temperature_c = read_temperature_c(config)
    rtc_time = read_rtc_time(config)
    return {
        "enabled": bool(config.get("wittypi.enabled", False)),
        "detected": is_wittypi_installed(config),
        "temperature_c": temperature_c,
        "temperature_f": round(temperature_c * 1.8 + 32, 1) if temperature_c is not None else None,
        "rtc_time": rtc_time.isoformat(timespec="seconds") if rtc_time else None,
        "voltage": None,
        "current": None,
        "last_log_lines": get_recent_wittypi_logs(config),
    }


def read_temperature_c(config: AppConfig) -> float | None:
    output = _run_utility_function(config, "get_temperature")
    if not output:
        return None
    match = TEMPERATURE_PATTERN.search(output)
    if not match:
        return None
    try:
        return round(float(match.group(1)), 3)
    except ValueError:
        return None


def read_rtc_time(config: AppConfig) -> datetime | None:
    output = _run_utility_function(config, "get_rtc_time")
    if not output or output == "N/A":
        return None
    match = RTC_TIME_PATTERN.search(output)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").astimezone()
    except ValueError:
        return None


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


def set_system_and_rtc_time(config: AppConfig, epoch_seconds: float, source: str = "ble-client") -> dict[str, Any]:
    if not bool(config.get("wittypi.enabled", False)):
        raise RuntimeError("Witty Pi integration is disabled")

    target = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    if not 2020 <= target.year <= 2099:
        raise ValueError("time must be between 2020 and 2099")

    software_dir = Path(str(config.get("wittypi.software_dir", "/home/admin/wittypi")))
    if not (software_dir / "utilities.sh").exists():
        raise RuntimeError(f"Witty Pi utilities not found: {software_dir / 'utilities.sh'}")

    system_time_changed = False
    try:
        CLOCK_TRUST_FILE.unlink(missing_ok=True)
        _run_checked(["timedatectl", "set-ntp", "false"])
        _run_checked(["date", "--utc", f"--set=@{int(epoch_seconds)}"])
        system_time_changed = True
        _run_checked(
            ["bash", "-lc", "source ./utilities.sh >/dev/null 2>&1 && system_to_rtc"],
            cwd=software_dir,
        )

        rtc_time = read_rtc_time(config)
        if rtc_time is None:
            raise RuntimeError("Witty Pi RTC did not return a valid time after synchronization")
        system_time = datetime.now().astimezone()
        drift_seconds = abs(round(system_time.timestamp() - rtc_time.timestamp()))
        if drift_seconds > 10:
            raise RuntimeError(f"Witty Pi RTC verification failed: {drift_seconds} seconds from system time")

        CLOCK_TRUST_FILE.touch()
        source_payload = {
            "source": source,
            "system_time": system_time.isoformat(timespec="seconds"),
            "rtc_time": rtc_time.isoformat(timespec="seconds"),
        }
        source_temp = CLOCK_SOURCE_FILE.with_suffix(".tmp")
        source_temp.write_text(json.dumps(source_payload, separators=(",", ":")), encoding="utf-8")
        source_temp.replace(CLOCK_SOURCE_FILE)
        return {**source_payload, "drift_seconds": drift_seconds}
    except Exception:
        if system_time_changed:
            CLOCK_TRUST_FILE.unlink(missing_ok=True)
        raise
    finally:
        try:
            subprocess.run(
                ["timedatectl", "set-ntp", "true"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Unable to restore NTP after clock update: %s", exc)


def _run_utility_function(config: AppConfig, function_name: str) -> str | None:
    if function_name not in UTILITY_FUNCTIONS:
        raise ValueError(f"Unsupported Witty Pi utility function: {function_name}")

    software_dir = Path(str(config.get("wittypi.software_dir", "/home/admin/wittypi")))
    utilities_path = software_dir / "utilities.sh"
    if not utilities_path.exists():
        return None

    script = f"source ./utilities.sh >/dev/null 2>&1 && {function_name}"
    try:
        result = subprocess.run(
            ["bash", "-lc", script],
            check=False,
            capture_output=True,
            cwd=software_dir,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("Unable to run Witty Pi utility function %s: %s", function_name, exc)
        return None
    if result.returncode != 0:
        logger.debug(
            "Witty Pi utility function %s failed with code %s: %s",
            function_name,
            result.returncode,
            result.stderr.strip(),
        )
        return None
    return result.stdout.strip()


def _run_checked(command: list[str], cwd: Path | None = None) -> None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            cwd=cwd,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Unable to run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise RuntimeError(f"{command[0]} failed: {detail}")
