"""The debug UART side terminal in the main window."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hwval_studio.config import Preferences
from hwval_studio.persistence.database import HistoryStore
from hwval_studio.ui.main_window import MainWindow
from hwval_studio.ui.theme import apply_theme


@pytest.fixture(scope="module")
def app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def test_terminal_shows_lines_and_toggles(app: QApplication, tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    window = MainWindow(Preferences(), store, auto_connect=False)
    window.resize(1400, 850)
    window.show()
    app.processEvents()
    assert window.terminal.isVisible()
    assert window.terminal.width() >= 330
    window.terminal.feed("task 1 LED: blinks")
    assert "task 1 LED" in window.terminal.text()
    window._toggle_terminal(False)
    assert not window.terminal.isVisible()
    assert not window.terminal_action.isChecked()
    window._toggle_terminal(True)
    assert window.terminal.isVisible()
    window.close()
