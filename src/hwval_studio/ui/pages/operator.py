"""Simplified operator mode screen (SRS section 14)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.config import TestPreset
from hwval_studio.core.client import Identity
from hwval_studio.ui.pages.base import Card
from hwval_studio.ui.theme import COLORS, icon


class OperatorView(QWidget):
    run_requested = Signal(str)
    abort_requested = Signal()
    exit_requested = Signal()

    def __init__(self, preset: TestPreset, operator_names: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.preset = preset
        self._running = False
        self._identity: Identity | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(18)

        header = QHBoxLayout()
        glyph = QLabel()
        glyph.setPixmap(icon("chip", COLORS["accent"], 42).pixmap(42, 42))
        header.addWidget(glyph)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("HWVAL Studio · Operator")
        title.setStyleSheet("font-size: 30px; font-weight: 800;")
        self.identity_label = QLabel("Connect a board to begin")
        self.identity_label.setObjectName("Secondary")
        self.identity_label.setStyleSheet("font-size: 15px;")
        title_box.addWidget(title)
        title_box.addWidget(self.identity_label)
        header.addLayout(title_box)
        header.addStretch(1)
        exit_button = QPushButton("Exit Operator Mode")
        exit_button.clicked.connect(self.exit_requested.emit)
        header.addWidget(exit_button)
        layout.addLayout(header)

        identity_card = Card()
        identity_layout = QHBoxLayout(identity_card)
        identity_layout.setContentsMargins(18, 12, 18, 12)
        name_label = QLabel("Operator")
        name_label.setObjectName("Secondary")
        name_label.setStyleSheet("font-size: 15px;")
        identity_layout.addWidget(name_label)
        self.operator_name = QComboBox()
        self.operator_name.setEditable(True)
        self.operator_name.setMinimumWidth(240)
        self.operator_name.setStyleSheet("font-size: 17px; padding: 7px 10px;")
        self.operator_name.addItems(operator_names)
        if operator_names:
            self.operator_name.setCurrentIndex(0)
        identity_layout.addWidget(self.operator_name)
        identity_layout.addStretch(1)
        self.selection_label = QLabel("")
        self.selection_label.setObjectName("Secondary")
        identity_layout.addWidget(self.selection_label)
        layout.addWidget(identity_card)

        self.status_card = Card()
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(28, 22, 28, 22)
        status_layout.setSpacing(8)
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 24px; font-weight: 700;")
        self.current_test = QLabel("")
        self.current_test.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_test.setObjectName("Secondary")
        self.current_test.setStyleSheet("font-size: 17px;")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(12)
        self.progress.setTextVisible(False)
        self.result = QLabel("")
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result.setStyleSheet("font-size: 54px; font-weight: 900;")
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.current_test)
        status_layout.addWidget(self.progress)
        status_layout.addWidget(self.result)
        layout.addWidget(self.status_card, 1)

        self.failed_card = Card()
        failed_layout = QVBoxLayout(self.failed_card)
        failed_layout.setContentsMargins(18, 12, 18, 12)
        failed_title = QLabel("Failed tests")
        failed_title.setObjectName("Heading")
        failed_layout.addWidget(failed_title)
        self.failed_list = QLabel("—")
        self.failed_list.setWordWrap(True)
        self.failed_list.setStyleSheet(f"color: {COLORS['fail']}; font-size: 15px;")
        failed_layout.addWidget(self.failed_list)
        self.failed_card.hide()
        layout.addWidget(self.failed_card)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.run_button = QPushButton(icon("play", "#FFFFFF", 22), "RUN TEST SUITE")
        self.run_button.setObjectName("LargeAction")
        self.run_button.setMinimumWidth(360)
        self.run_button.clicked.connect(self._run)
        buttons.addWidget(self.run_button)
        self.abort_button = QPushButton("Abort")
        self.abort_button.setObjectName("Danger")
        self.abort_button.setMinimumHeight(52)
        self.abort_button.setEnabled(False)
        self.abort_button.clicked.connect(self.abort_requested.emit)
        buttons.addWidget(self.abort_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.set_identity(None)
        self.set_preset(preset)

    def set_preset(self, preset: TestPreset) -> None:
        self.preset = preset
        levels = preset.levels.replace(",", " / ")
        self.selection_label.setText(
            f"Levels {levels} · operator tests {'on' if preset.allow_operator else 'off'} · destructive never"
        )

    def set_identity(self, identity: Identity | None) -> None:
        self._identity = identity
        if identity is None:
            self.identity_label.setText("No board connected")
            self.run_button.setEnabled(False)
            return
        self.identity_label.setText(
            f"{identity.firmware_name} {identity.version} · {identity.role_name} · UID {identity.uid_hex}"
        )
        self.run_button.setEnabled(identity.role == 1 and not self._running)

    def _run(self) -> None:
        name = self.operator_name.currentText().strip()
        if not name:
            self.status_label.setText("Enter the operator name first")
            return
        self.run_requested.emit(name)

    def start_run(self, total: int = 0) -> None:
        self._running = True
        self.run_button.setEnabled(False)
        self.abort_button.setEnabled(True)
        self.result.setText("")
        self.failed_card.hide()
        self.status_label.setText("Running…")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.current_test.setText(f"0 of {total}" if total else "")

    def test_started(self, data: dict[str, Any], title: str = "") -> None:
        index = int(data.get("index", 0)) + 1
        total = int(data.get("total", 0))
        self.current_test.setText(f"{index} of {total} · {data.get('id', '')} {title}")
        if total:
            self.progress.setValue(int(100 * (index - 1) / total))

    def test_result(self, result: dict[str, Any], title: str = "") -> None:
        verdict = str(result.get("result_name", result.get("result", "")))
        if verdict == "FAIL":
            self.result.setText("FAIL")
            self.result.setStyleSheet(f"font-size: 54px; font-weight: 900; color: {COLORS['fail']};")
        elif verdict == "PASS":
            self.result.setText("PASS")
            self.result.setStyleSheet(f"font-size: 54px; font-weight: 900; color: {COLORS['pass']};")
        elif verdict == "SKIP":
            self.result.setText("SKIP")
            self.result.setStyleSheet(f"font-size: 54px; font-weight: 900; color: {COLORS['skip']};")

    def run_finished(self, payload: dict[str, Any]) -> None:
        self._running = False
        self.run_button.setEnabled(self._identity is not None and self._identity.role == 1)
        self.abort_button.setEnabled(False)
        counts = payload.get("counts", {})
        failed = [result for result in payload.get("results", []) if str(result.get("result_name")) == "FAIL"]
        overall = payload.get("overall", "FAIL")
        if overall == "PASS":
            self.status_label.setText(
                f"TEST SUITE PASSED · {counts.get('pass', 0)} passed · {counts.get('skip', 0)} skipped"
            )
            self.result.setText("PASS")
            self.result.setStyleSheet(f"font-size: 54px; font-weight: 900; color: {COLORS['pass']};")
            self.failed_card.hide()
            self.progress.setValue(100)
        else:
            self.status_label.setText(
                f"TEST SUITE FAILED · {counts.get('fail', 0)} failed · {counts.get('pass', 0)} passed"
            )
            self.result.setText("FAIL")
            self.result.setStyleSheet(f"font-size: 54px; font-weight: 900; color: {COLORS['fail']};")
            lines = []
            for result in failed:
                lines.append(
                    f"• {result.get('id')} — {result.get('reason') or 'failed'}"
                )
            self.failed_list.setText("\n".join(lines) or "—")
            self.failed_card.show()
        self.current_test.setText("")
        if failed:
            self.result.setToolTip("\n".join(result.get("id", "") for result in failed))

    def aborting(self) -> None:
        self.status_label.setText("Aborting…")
        self.abort_button.setEnabled(False)

    def run_failed(self, message: str) -> None:
        self._running = False
        self.run_button.setEnabled(self._identity is not None and self._identity.role == 1)
        self.abort_button.setEnabled(False)
        self.status_label.setText("Run failed")
        self.result.setText("ERROR")
        self.result.setStyleSheet(f"font-size: 54px; font-weight: 900; color: {COLORS['fail']};")
        self.current_test.setText(message)
