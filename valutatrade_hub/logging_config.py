"""Configuration for rotated, human-readable action logs."""

import logging
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

LOGGER_NAME = "valutatrade.actions"


def configure_logging() -> logging.Logger:
    """Configure and return the dedicated action logger once."""
    logger = logging.getLogger(LOGGER_NAME)
    settings = SettingsLoader()
    logger.setLevel(settings.get("log_level"))
    logger.propagate = False
    if not logger.handlers:
        log_file = settings.log_file
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_file,
            maxBytes=settings.get("log_max_bytes"),
            backupCount=settings.get("log_backup_count"),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def configure_parser_logging() -> logging.Logger:
    """Configure a separate size-rotated journal for parser operations."""
    logger = logging.getLogger("valutatrade.parser")
    settings = SettingsLoader()
    logger.setLevel(settings.get("log_level"))
    logger.propagate = False
    if not logger.handlers:
        log_file = settings._absolute(
            settings.get("parser_log_file", "logs/parser.log")
        )
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_file,
            maxBytes=settings.get("log_max_bytes"),
            backupCount=settings.get("log_backup_count"),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(levelname)s %(asctime)s %(message)s"))
        logger.addHandler(handler)
    return logger
