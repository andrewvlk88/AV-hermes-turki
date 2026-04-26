"""Shared logger module for turk-price-intelligence."""

import logging
import sys


def setup_logger(name: str = "turk_pi") -> logging.Logger:
    """Set up the root logger with a console handler."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.WARNING)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the turk_pi namespace."""
    return logging.getLogger(f"turk_pi.{name}")
