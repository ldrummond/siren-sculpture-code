from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

from siren_app.config import ConfigError, load_config
from siren_app.logging_config import setup_logging
from siren_app.status import gather_status


logger = logging.getLogger(__name__)


def main() -> int:
    try:
        config = load_config()
        setup_logging(config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    logger.info("Running sculpture health check")
    serious_errors: list[str] = []
    warnings: list[str] = []

    audio_file = Path(str(config.get("audio.file")))
    if not audio_file.exists():
        serious_errors.append(f"Missing audio file: {audio_file}")

    disk = shutil.disk_usage(str(config.get("paths.app_dir", "/")))
    free_mb = round(disk.free / 1024 / 1024)
    warn_mb = int(config.get("healthcheck.disk_free_warn_mb", 500) or 500)
    if free_mb < warn_mb:
        warnings.append(f"Low disk space: {free_mb} MB free")

    status = gather_status(config)
    if not status["clock"]["clock_ok"]:
        if not status["clock"]["clock_trusted"]:
            warnings.append("Clock is not trusted; scheduled sculpture playback is disabled")
        else:
            warnings.append(f"Clock drift warning: {status['clock']['drift_seconds']} seconds")
    if config.get("wittypi.enabled", False) and not status["wittypi"]["detected"]:
        warnings.append("Witty Pi software directory not detected")

    for warning in warnings:
        logger.warning(warning)
    for error in serious_errors:
        logger.error(error)

    if serious_errors:
        return 1
    logger.info("Health check completed with %s warning(s)", len(warnings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
