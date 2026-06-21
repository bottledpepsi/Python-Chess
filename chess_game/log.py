"""Structured logging to a rotating file.

Diagnostics must never rely on stdout: under a ``pyinstaller --windowed``
build, stdout is discarded entirely.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs

_LOGGER_NAME = "python_chess"
_configured = False


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure (once) and return the package logger.

    Backed by a RotatingFileHandler (1 MB, 3 backups) in the platform's
    user log directory. Safe to call multiple times — configuration only
    happens once per process.
    """
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    log_dir = Path(platformdirs.user_log_dir("python-chess", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "python-chess.log"

    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s :: %(message)s"
    )
    handler.setFormatter(formatter)

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    _configured = True
    return logger


def get_logger() -> logging.Logger:
    """Return the package logger, configuring it with defaults if needed."""
    if not _configured:
        return configure_logging()
    return logging.getLogger(_LOGGER_NAME)
