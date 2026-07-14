from __future__ import annotations

import logging

from siren_app.config import AppConfig


def setup_logging(config: AppConfig) -> None:
    level_name = str(config.get("logging.level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = "%(levelname)s [%(name)s] %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)
