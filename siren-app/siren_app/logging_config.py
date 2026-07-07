from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from siren_app.config import AppConfig


def setup_logging(config: AppConfig) -> None:
    level_name = str(config.get("logging.level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)

    log_file = Path(str(config.get("logging.file", "/var/log/sculpture/sculpture.log")))
    max_mb = int(config.get("logging.max_mb", 10) or 10)
    backups = int(config.get("logging.backups", 5) or 5)
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_mb * 1024 * 1024,
            backupCount=backups,
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        root.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning("File logging unavailable at %s: %s", log_file, exc)
