from __future__ import annotations

import logging
from pathlib import Path

from siren_app.config import AppConfig
from siren_app.logging_config import setup_logging


def test_setup_logging_uses_one_console_handler() -> None:
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]
    config = AppConfig(data={"logging": {"level": "WARNING"}}, path=Path("sculpture.yaml"))

    try:
        setup_logging(config)

        assert root.level == logging.WARNING
        assert len(root.handlers) == 1
        assert type(root.handlers[0]) is logging.StreamHandler
    finally:
        root.handlers.clear()
        root.handlers.extend(original_handlers)
        root.setLevel(original_level)
