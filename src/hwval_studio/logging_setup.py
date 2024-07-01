"""Rotating file logging and uncaught-exception handling (GNFR-005)."""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from hwval_studio.config import log_dir


def setup_logging(level: str = "INFO") -> logging.Logger:
    directory = log_dir()
    logger = logging.getLogger("hwval_studio")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if logger.handlers:
        return logger
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = RotatingFileHandler(
        directory / "hwval-studio.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def install_exception_hook(logger: logging.Logger) -> None:
    def handle(exc_type: type[BaseException], exc_value: BaseException, tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, tb))
        logger.error("uncaught exception\n%s", text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                box = QMessageBox()
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("HWVAL Studio error")
                box.setText("An unexpected error occurred. The details have been written to the log file.")
                box.setDetailedText(text)
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
                box.exec()
        except Exception:
            pass

    sys.excepthook = handle


def log_folder() -> Path:
    return log_dir()
