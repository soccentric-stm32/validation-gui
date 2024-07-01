"""Collapsible log console with level filter, search, copy and hex dump (WIN-007)."""

from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import SearchBox

LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
LEVEL_COLORS = {
    "DEBUG": COLORS["muted"],
    "INFO": COLORS["secondary"],
    "WARN": COLORS["warning"],
    "ERROR": COLORS["fail"],
}


class LogConsole(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entries: list[tuple[str, str, str]] = []
        self.show_hex = False
        self.min_level = "INFO"
        self.query = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(10, 4, 10, 4)
        bar_layout.setSpacing(6)
        title = QLabel("Log")
        title.setStyleSheet("font-weight: 700;")
        bar_layout.addWidget(title)
        self.level = QComboBox()
        self.level.addItems(["DEBUG", "INFO", "WARN", "ERROR"])
        self.level.setCurrentText("INFO")
        self.level.currentTextChanged.connect(self._set_level)
        bar_layout.addWidget(self.level)
        self.search = SearchBox("Filter log…")
        self.search.setMaximumWidth(240)
        self.search.textChanged.connect(self._set_query)
        bar_layout.addWidget(self.search)
        bar_layout.addStretch(1)
        self.hex_button = QPushButton("Hex")
        self.hex_button.setCheckable(True)
        self.hex_button.setToolTip("Show raw frame hex dumps at debug level")
        self.hex_button.toggled.connect(self._toggle_hex)
        bar_layout.addWidget(self.hex_button)
        copy_button = QPushButton(icon("save", COLORS["secondary"], 14), "Copy")
        copy_button.clicked.connect(self.copy)
        bar_layout.addWidget(copy_button)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear)
        bar_layout.addWidget(clear_button)
        layout.addWidget(bar)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.document().setMaximumBlockCount(5000)
        self.view.setObjectName("LogView")
        self.view.setFont(QFont("JetBrains Mono", 9))
        self.view.setStyleSheet(
            f"background: {COLORS['surface_alt']}; border: none; border-top: 1px solid {COLORS['separator']};"
            "padding: 5px;"
        )
        layout.addWidget(self.view, 1)
        self.setMinimumHeight(90)
        self.setMaximumHeight(240)

    # -- configuration -------------------------------------------------
    def _set_level(self, level: str) -> None:
        self.min_level = level
        self._rebuild()

    def _set_query(self, query: str) -> None:
        self.query = query.strip().lower()
        self._rebuild()

    def _toggle_hex(self, enabled: bool) -> None:
        self.show_hex = enabled
        self._rebuild()

    # -- logging -------------------------------------------------------
    def log(self, level: str, text: str) -> None:
        level = level.upper()
        if level not in LEVEL_ORDER:
            level = "INFO"
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.entries.append((timestamp, level, text))
        if len(self.entries) > 5000:
            del self.entries[:1000]
        if self._visible(level, text):
            self._append_html(timestamp, level, text)

    def debug(self, text: str) -> None:
        self.log("DEBUG", text)

    def info(self, text: str) -> None:
        self.log("INFO", text)

    def warn(self, text: str) -> None:
        self.log("WARN", text)

    def error(self, text: str) -> None:
        self.log("ERROR", text)

    def log_frame(self, direction: str, data: bytes) -> None:
        if not self.show_hex:
            return
        hex_text = " ".join(f"{byte:02X}" for byte in data)
        self.log("DEBUG", f"{direction} {len(data)} B: {hex_text}")

    def _visible(self, level: str, text: str) -> bool:
        if LEVEL_ORDER.get(level, 1) < LEVEL_ORDER.get(self.min_level, 1):
            return False
        return not (self.query and self.query not in text.lower())

    @staticmethod
    def _line_html(timestamp: str, level: str, text: str) -> str:
        color = LEVEL_COLORS.get(level, COLORS["secondary"])
        escaped = html.escape(text).replace(" ", "&nbsp;")
        return (
            f'<span style="color:{COLORS["muted"]}">{timestamp}</span> '
            f'<span style="color:{color};font-weight:600">{level:5s}</span> '
            f'<span style="color:{COLORS["text"]}">{escaped}</span>'
        )

    def _append_html(self, timestamp: str, level: str, text: str) -> None:
        self.view.append(self._line_html(timestamp, level, text))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _rebuild(self) -> None:
        lines = [
            self._line_html(timestamp, level, text)
            for timestamp, level, text in self.entries
            if self._visible(level, text)
        ]
        self.view.setHtml("<br>".join(lines))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # -- actions -------------------------------------------------------
    def copy(self) -> None:
        cursor = self.view.textCursor()
        if cursor.hasSelection():
            self.view.copy()
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(
            "\n".join(
                f"{timestamp} {level:5s} {text}"
                for timestamp, level, text in self.entries
                if self._visible(level, text)
            )
        )

    def clear(self) -> None:
        self.entries.clear()
        self.view.clear()

    def set_collapsed(self, collapsed: bool) -> None:
        self.view.setVisible(not collapsed)
        self.setMaximumHeight(34 if collapsed else 220)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            for timestamp, level, text in self.entries:
                handle.write(f"{timestamp} {level:5s} {text}\n")
