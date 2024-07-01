"""Operator prompt sheet (TST-030/031/032/033)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.ui.theme import COLORS, icon


class OperatorPromptDialog(QDialog):
    answered = Signal(int, str)
    timed_out = Signal(int)

    def __init__(self, prompt: dict[str, Any], parent: QWidget | None = None, *, operator_mode: bool = False) -> None:
        super().__init__(parent)
        self.prompt = prompt
        self.prompt_id = int(prompt.get("prompt_id", 0))
        self.operator_mode = operator_mode
        self._answered = False
        self.setWindowTitle("Operator action required")
        self.setModal(True)
        self.setMinimumWidth(560 if operator_mode else 480)
        self.setWindowFlag(Qt.WindowType.Sheet, True) if parent is not None else None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        kind = str(prompt.get("kind_name", "YES_NO"))
        icon_name = {
            "BUTTON": "button",
            "EQUIPMENT": "usb",
            "DESTRUCTIVE": "warning",
            "LINE": "console",
        }.get(kind, "help")
        top = QHBoxLayout()
        glyph = QLabel()
        glyph.setPixmap(icon(icon_name, COLORS["accent"], 42 if operator_mode else 30).pixmap(42 if operator_mode else 30, 42 if operator_mode else 30))
        top.addWidget(glyph)
        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        test_label = QLabel(str(prompt.get("test_id", "")))
        test_label.setObjectName("Secondary")
        title = QLabel("Operator action required")
        title.setObjectName("PageTitle")
        text_box.addWidget(test_label)
        text_box.addWidget(title)
        top.addLayout(text_box)
        top.addStretch(1)
        layout.addLayout(top)
        message = QLabel(str(prompt.get("text", "")))
        message.setWordWrap(True)
        message.setStyleSheet(f"font-size: {'18px' if operator_mode else '14px'};")
        layout.addWidget(message)
        self.countdown = QLabel()
        self.countdown.setObjectName("Secondary")
        if operator_mode:
            self.countdown.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.countdown)
        self.line_edit: QLineEdit | None = None
        answers = [part.strip() for part in str(prompt.get("answers", "")).replace(";", ",").split(",") if part.strip()]
        if kind == "LINE":
            self.line_edit = QLineEdit()
            self.line_edit.setPlaceholderText("Enter the answer")
            layout.addWidget(self.line_edit)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for answer in answers or ["yes", "no", "skip"]:
            label = answer.capitalize()
            button = QPushButton(label)
            if answer.lower() in {"yes", "ok", "pass", "confirm"}:
                button.setObjectName("Accent")
            if operator_mode:
                button.setStyleSheet("font-size: 17px; padding: 12px 24px;")
            button.clicked.connect(lambda _checked=False, value=answer: self._answer(value))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.remaining = max(1, int(prompt.get("timeout_s", 20)))
        self._update_countdown()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

    def _update_countdown(self) -> None:
        self.countdown.setText(f"Time remaining: {self.remaining} s")

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            if not self._answered:
                self._answered = True
                self.timed_out.emit(self.prompt_id)
                self.reject()
            return
        self._update_countdown()

    def _answer(self, answer: str) -> None:
        if self.line_edit is not None:
            answer = self.line_edit.text().strip() or answer
        if self._answered:
            return
        self._answered = True
        self.timer.stop()
        self.answered.emit(self.prompt_id, answer)
        self.accept()

    def close_on_button(self, event: dict[str, Any]) -> None:
        """TST-032: close a button prompt when HWVAL reports the press."""
        if str(self.prompt.get("kind_name")) == "BUTTON" and not self._answered:
            self._answered = True
            self.timer.stop()
            self.answered.emit(self.prompt_id, "yes")
            self.accept()

    def close_on_done(self, event: dict[str, Any]) -> None:
        """TST-032: close when HWVAL reports the prompt is done."""
        if self._answered or int(event.get("prompt_id", -1)) != self.prompt_id:
            return
        self._answered = True
        self.timer.stop()
        self.accept()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)
