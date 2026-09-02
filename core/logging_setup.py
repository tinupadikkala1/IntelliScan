"""Centralised logging configuration for IntelliVault.

Logs are written both to ``logs/intellivault.log`` and to the console so the
application can be debugged during development. Optionally a database handler
persists WARNING+ records into the ``logs`` table.
"""

from __future__ import annotations

import logging
import os

LOGGER_NAME = "intellivault"


class _DBLogHandler(logging.Handler):
    def __init__(self, repository, level=logging.WARNING):
        super().__init__(level)
        self.repository = repository

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.repository.add_log(
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
            )
        except Exception:
            # Never let logging break the app.
            pass


def setup_logging(level: int = logging.INFO, log_dir: str | None = None) -> logging.Logger:
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "intellivault.log")

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(module)s: %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger


def attach_db_handler(repository, level: int = logging.WARNING) -> None:
    """Attach a database-backed handler to the intellivault logger."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in logger.handlers:
        if isinstance(handler, _DBLogHandler):
            return  # already attached
    logger.addHandler(_DBLogHandler(repository, level))


def get_logger(name: str | None = None) -> logging.Logger:
    if name is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
