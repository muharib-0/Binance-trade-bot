"""
Logging configuration for the Primetrade Trading Bot.

Sets up dual-output logging:
  - File handler → logs/trading_bot.log  (DEBUG level, rotating, full detail)
  - Console handler → stderr             (INFO level, summaries only)

Key security guarantee: API keys and signatures are NEVER written to any log.
The client layer only passes sanitised parameters to the logger.

Usage:
    from bot.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("Something happened")
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from bot.config import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"  # ISO 8601

_MAX_BYTES   = 5 * 1024 * 1024  # 5 MB per log file
_BACKUP_COUNT = 3               # Keep 3 rotated log files

# Regex to catch any stray credential-like strings (hex 40+ chars = typical HMAC)
_REDACT_PATTERN = re.compile(r"[0-9a-fA-F]{40,}")

# ---------------------------------------------------------------------------
# Sanitising log filter
# ---------------------------------------------------------------------------

class _RedactSecretsFilter(logging.Filter):
    """
    Logging filter that redacts long hex strings from log records.

    This is a defence-in-depth measure. The client layer already avoids
    logging credentials, but this filter catches any accidental leakage
    (e.g., if a full response body containing a signature slips through).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _REDACT_PATTERN.sub("[REDACTED]", record.msg)
        if record.args:
            record.args = tuple(
                _REDACT_PATTERN.sub("[REDACTED]", str(a)) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        return True  # Always allow the (now-sanitised) record through


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    """
    Configure the root logger with file and console handlers.

    Called once at module import time. Subsequent calls to get_logger()
    return child loggers that inherit from the root configuration.
    """
    root_logger = logging.getLogger("bot")
    root_logger.setLevel(logging.DEBUG)  # Capture everything at root level

    # Avoid duplicate handlers if this module is imported multiple times
    if root_logger.handlers:
        return

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    secret_filter = _RedactSecretsFilter()

    # ── File Handler (DEBUG level — full detail for audit trail) ──────────
    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(secret_filter)

    # ── Console Handler (INFO level — summaries only, not noisy) ─────────
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(secret_filter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the 'bot' namespace.

    All modules should use this instead of logging.getLogger() directly
    to ensure the logging configuration is always applied.

    Args:
        name: Typically __name__ from the calling module.

    Returns:
        A configured Logger instance.

    Example:
        logger = get_logger(__name__)
        logger.info("Order placed successfully")
    """
    _setup_logging()  # Idempotent — safe to call multiple times
    return logging.getLogger(name)
