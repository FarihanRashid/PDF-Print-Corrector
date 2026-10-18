"""
logger.py

Thin wrapper around the stdlib logging module that writes a rolling
log.txt next to the executable, recording every conversion (input,
output, offsets, timing) and every error, per the spec's logging
requirement.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from utils.constants import LOG_FILE_NAME


def _log_dir() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.access(base, os.W_OK):
        return base
    fallback = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "PDFPrintCorrector")
    os.makedirs(fallback, exist_ok=True)
    return fallback


_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("pdf_offset_corrector")
    logger.setLevel(logging.INFO)

    log_path = os.path.join(_log_dir(), LOG_FILE_NAME)
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    _logger = logger
    return logger


def log_conversion(input_path: str, output_path: str, h_mm: float, v_mm: float, rot_deg: float, elapsed_s: float) -> None:
    get_logger().info(
        "CONVERTED input=%s output=%s h=%.2fmm v=%.2fmm rot=%.2fdeg time=%.2fs",
        input_path, output_path, h_mm, v_mm, rot_deg, elapsed_s,
    )


def log_error(input_path: str, message: str) -> None:
    get_logger().error("FAILED input=%s reason=%s", input_path, message)


def log_info(message: str) -> None:
    get_logger().info(message)
