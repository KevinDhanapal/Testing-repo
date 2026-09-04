"""Structured logging for the review engine."""
from __future__ import annotations

import logging
import os
from typing import Optional

LOGGER_NAME = "cragent"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"


def setup_logging(log_file: Optional[str] = None, level: str = "INFO", verbose: bool = False) -> logging.Logger:
    """Configure the package logger: file handler always, console when verbose."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else getattr(logging, str(level).upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(_FORMAT)
    if log_file:
        try:
            directory = os.path.dirname(os.path.abspath(log_file))
            if directory:
                os.makedirs(directory, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            logger.addHandler(file_handler)
        except OSError:
            pass  # a read-only workspace must not break scanning

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logger.addHandler(console)
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
