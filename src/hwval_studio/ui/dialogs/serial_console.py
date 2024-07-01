"""Serial console for text-CLI access (Appendix A LNK-002, CR-01)."""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.ui.theme import COLORS, icon


class SerialConsoleDialog(QDialog):
    def __init__(self, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Serial Console")
        self.resize(760, 500)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Raw text console. HWVAL starts in its text CLI; use <b>Enter Text Mode</b> to return to it "
            "from HWLINK. Use the close button and reconnect to return to HWLINK."
        )
        note.setWordWrap(True)
        note.setObjectName("Secondary")
        layout.addWidget(note)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("JetBrains Mono", 9))
        self.view.setStyleSheet(
            f"background: {COLORS['surface_alt']}; border: 1px solid {COLORS['separator']}; border-radius: 6px;"
        )
        layout.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Command (e.g. help, info, mode script)…")
        self.input.returnPressed.connect(self.send)
        row.addWidget(self.input, 1)
        send = QPushButton(icon("play", COLORS["secondary"], 14), "Send")
        send.clicked.connect(self.send)
        row.addWidget(send)
        self.text_mode = QPushButton("Enter Text Mode")
        self.text_mode.clicked.connect(self.enter_text_mode)
        row.addWidget(self.text_mode)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.view.clear)
        row.addWidget(clear)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        controller.serial_bytes.connect(self.append_bytes)
        controller.disconnected.connect(lambda _reason: self.append_line("[disconnected]"))
        if controller.worker is None:
            self.append_line("[no serial connection]")

    def append_bytes(self, data: bytes) -> None:
        text = data.decode("utf-8", "replace")
        if not text:
            return
        cursor = self.view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def append_line(self, text: str) -> None:
        self.view.append(html.escape(text))

    def send(self) -> None:
        text = self.input.text()
        if not text:
            return
        if self.controller.worker is None:
            self.append_line("[no serial connection]")
            return
        try:
            self.controller.worker.write((text + "\r").encode())
            self.append_line(f"> {text}")
            self.input.clear()
        except Exception as exc:
            self.append_line(f"[write failed: {exc}]")

    def enter_text_mode(self) -> None:
        self.controller.enter_text_mode()
        self.append_line("[requested text mode]")
