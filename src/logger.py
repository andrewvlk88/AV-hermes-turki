"""Shared logger module for turk-price-intelligence."""

import logging
import sys
from pathlib import Path


def setup_logger(name: str = "turk_pi", log_file: str | None = None) -> logging.Logger:
    """Set up the root logger with console and optional file handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)  # Capture everything up to INFO level
    
    # Remove existing handlers to avoid duplicates on re-setup
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        
    # Console handler (standard error)
    console_handler = logging.StreamHandler(sys.stderr)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    
    # File handler (if requested)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the turk_pi namespace."""
    return logging.getLogger(f"turk_pi.{name}")
