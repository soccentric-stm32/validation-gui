"""Bundled help, user guide, test catalogue and licences (MNU-012)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from hwval_studio import APP_NAME, __version__
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import SearchBox


def _read_doc(name: str) -> str:
    candidates = [
        Path(__file__).resolve().parents[2] / "docs" / name,
        Path(__file__).resolve().parents[4] / "docs" / name,
        Path.cwd() / "docs" / name,
    ]
    for path in candidates:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return f"# {name}\n\nThe document is not bundled in this build."


KEYBOARD_SHORTCUTS = """# Keyboard shortcuts

macOS is shown; on Windows and Linux use Ctrl instead of ⌘ and Alt instead of ⌥.

| Action | Shortcut |
|---|---|
| Connect / Disconnect | ⌘K / ⇧⌘K |
| Run Selected | ⌘R |
| Run Group | ⌥⌘R |
| Run All… | ⇧⌘R |
| Abort | ⌘. |
| Find | ⌘F |
| Find Next | ⌘G |
| Preferences | ⌘, |
| Show/Hide Sidebar | ⌃⌘S (Ctrl+Alt+S elsewhere) |
| Show/Hide Log | ⇧⌘L |
| Operator Mode | ⇧⌘O |
| Firmware Update | ⇧⌘U |
| Export Report | ⇧⌘E |
| Zoom In / Out / Actual Size | ⌘+ / ⌘− / ⌘0 |
| Close Window / Quit | ⌘W / ⌘Q |
"""


class HelpWindow(QDialog):
    def __init__(self, parent: QWidget | None = None, tab: str = "guide") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Help")
        self.resize(940, 720)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        glyph = QLabel()
        glyph.setPixmap(icon("help", COLORS["accent"], 28).pixmap(28, 28))
        header.addWidget(glyph)
        title = QLabel(f"{APP_NAME} {__version__}")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.search = SearchBox("Find in page…")
        self.search.setMaximumWidth(230)
        header.addWidget(self.search)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.user_guide = self._browser(_read_doc("USER_GUIDE.md"))
        self.catalogue = self._browser(_read_doc("TEST_CATALOGUE.md"))
        self.shortcuts = self._browser(KEYBOARD_SHORTCUTS)
        self.licences = self._browser(_read_doc("THIRD_PARTY.md"))
        self.tabs.addTab(self._tab(self.user_guide), "User Guide")
        self.tabs.addTab(self._tab(self.catalogue), "Test Catalogue")
        self.tabs.addTab(self._tab(self.shortcuts), "Keyboard Shortcuts")
        self.tabs.addTab(self._tab(self.licences), "Licences")
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._search)
        index = {"guide": 0, "catalogue": 1, "shortcuts": 2, "licences": 3}.get(tab, 0)
        self.tabs.setCurrentIndex(index)

    @staticmethod
    def _browser(markdown: str) -> QTextBrowser:
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(markdown)
        return browser

    @staticmethod
    def _tab(widget: QWidget) -> QWidget:
        return widget

    def _search(self, query: str) -> None:
        browser = self.tabs.currentWidget()
        if isinstance(browser, QTextBrowser):
            if not query:
                browser.moveCursor(QTextCursor.MoveOperation.Start)
                return
            if not browser.find(query):
                cursor = browser.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                browser.setTextCursor(cursor)
                browser.find(query)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from hwval_studio.version import BUILD_DATE, GIT_COMMIT, VERSION

        self.setWindowTitle(f"About {APP_NAME}")
        self.setFixedWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(icon("chip", COLORS["accent"], 58).pixmap(58, 58))
        glyph.setAlignment(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(glyph)
        title = QLabel(APP_NAME)
        title.setObjectName("PageTitle")
        title.setAlignment(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        version = QLabel(f"Version {VERSION} · built {BUILD_DATE}" + (f" · {GIT_COMMIT}" if GIT_COMMIT else ""))
        version.setAlignment(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignCenter)
        version.setObjectName("Secondary")
        layout.addWidget(version)
        details = QLabel(
            "<p style='text-align:center'>HWVAL Studio is the host GUI for the NUCLEO-F767ZI "
            "hardware validation platform. It runs HWVAL tests over UART, updates applications "
            "through the A/B bootloader, flashes firmware over SWD and controls the demo application.</p>"
            "<p style='text-align:center'><b>Protocol HWLINK 1.1</b> · Python / PySide6 / FlatBuffers / SQLite</p>"
            "<p style='text-align:center;color:#6E6E73'>MIT licence © 2026 Sandesh Ghimire.<br>"
            "PySide6 is LGPL-3.0; pyserial is BSD-3-Clause; FlatBuffers is Apache-2.0.<br>"
            "Icons are original line icons; see the Licences tab in Help.</p>"
        )
        details.setWordWrap(True)
        details.setOpenExternalLinks(True)
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
