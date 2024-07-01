"""Demo application control (SRS section 11)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.protocol.generated.hwlink.LedId import LedId
from hwval_studio.protocol.generated.hwlink.LedPattern import LedPattern
from hwval_studio.ui.pages.base import ScrollPage, SectionCard, StatRow
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import KeyValueGrid, LedIndicator

PATTERNS = ["OFF", "ON", "BLINK", "HEARTBEAT", "FAST", "CHASE", "MORSE_SOS"]
PATTERN_VALUES = {name: getattr(LedPattern, name) for name in PATTERNS}


class LedControl(QWidget):
    changed = Signal(int, int, int)

    def __init__(self, led: int, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.led = led
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        top = QHBoxLayout()
        self.indicator = LedIndicator(title)
        top.addWidget(self.indicator)
        top.addStretch(1)
        self.pattern = QComboBox()
        self.pattern.addItems(PATTERNS)
        self.pattern.setCurrentText("HEARTBEAT" if led == 1 else "OFF")
        self.pattern.currentTextChanged.connect(self._changed)
        top.addWidget(self.pattern)
        layout.addLayout(top)
        bottom = QHBoxLayout()
        label = QLabel("Period")
        label.setObjectName("Secondary")
        bottom.addWidget(label)
        self.period = QSlider(Qt.Orientation.Horizontal)
        self.period.setRange(50, 5000)
        self.period.setSingleStep(10)
        self.period.setPageStep(100)
        self.period.setValue(1000)
        self.period.valueChanged.connect(self._changed_slider)
        self._slider_timer = QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.setInterval(150)
        self._slider_timer.timeout.connect(self._changed)
        bottom.addWidget(self.period, 1)
        self.period_label = QLabel("1000 ms")
        self.period_label.setObjectName("Secondary")
        self.period_label.setFixedWidth(64)
        bottom.addWidget(self.period_label)
        layout.addLayout(bottom)

    def _changed_slider(self, value: int) -> None:
        self.period_label.setText(f"{value} ms")
        # Debounce: a drag emits one valueChanged per tick; sending a
        # SetLed request for each would flood the link.
        self._slider_timer.start()

    def _changed(self) -> None:
        self.changed.emit(self.led, PATTERN_VALUES.get(self.pattern.currentText(), 0), self.period.value())

    def set_state(self, pattern: str, period_ms: int) -> None:
        self.pattern.blockSignals(True)
        self.period.blockSignals(True)
        self.pattern.setCurrentText(pattern if pattern in PATTERNS else "OFF")
        self.period.setValue(max(50, min(5000, int(period_ms or 1000))))
        self.period_label.setText(f"{self.period.value()} ms")
        self.pattern.blockSignals(False)
        self.period.blockSignals(False)
        self.indicator.set_pattern(pattern, self.period.value())


class DemoPage(ScrollPage):
    refresh_requested = Signal()
    led_requested = Signal(int, int, int)
    led_all_requested = Signal(int, int)
    clear_fault_requested = Signal()
    reset_requested = Signal()
    bootloader_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Demo App", "LEDs, button events, health and faults", "demo", parent)
        self.status: dict[str, Any] | None = None

        refresh = QPushButton(icon("refresh", COLORS["secondary"], 14), "Refresh")
        refresh.clicked.connect(self.refresh_requested.emit)
        self.add_action(refresh)

        self.stats = StatRow(
            [
                ("Uptime", "—"),
                ("Slot", "—"),
                ("Trial", "—"),
                ("Health", "—"),
                ("Button", "—"),
            ]
        )
        self.add_card(self.stats)

        status_card = SectionCard("Status")
        self.status_grid = KeyValueGrid()
        status_card.add_widget(self.status_grid)
        self.add_card(status_card)

        leds_card = SectionCard("LEDs", "mirrors LD1/LD2/LD3 on the board")
        leds_row = QWidget()
        leds_layout = QHBoxLayout(leds_row)
        leds_layout.setContentsMargins(0, 0, 0, 0)
        leds_layout.setSpacing(14)
        self.led1 = LedControl(LedId.LD1, "LD1 · green")
        self.led2 = LedControl(LedId.LD2, "LD2 · blue")
        self.led3 = LedIndicator("LD3 · red (fault)")
        for control in (self.led1, self.led2):
            control.changed.connect(self.led_requested.emit)
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addWidget(control)
            leds_layout.addWidget(holder, 1)
        led3_holder = QWidget()
        led3_layout = QVBoxLayout(led3_holder)
        led3_layout.setContentsMargins(0, 0, 0, 0)
        led3_layout.addWidget(self.led3)
        led3_layout.addWidget(QLabel("Reserved for faults"))
        leds_layout.addWidget(led3_holder, 1)
        leds_card.add_widget(leds_row)
        all_row = QHBoxLayout()
        all_label = QLabel("All LEDs")
        all_label.setObjectName("Secondary")
        all_row.addWidget(all_label)
        self.all_pattern = QComboBox()
        self.all_pattern.addItems(PATTERNS)
        all_row.addWidget(self.all_pattern)
        self.all_period = QSlider(Qt.Orientation.Horizontal)
        self.all_period.setRange(50, 5000)
        self.all_period.setValue(1000)
        all_row.addWidget(self.all_period, 1)
        self.all_period_label = QLabel("1000 ms")
        self.all_period_label.setObjectName("Secondary")
        self.all_period.valueChanged.connect(lambda value: self.all_period_label.setText(f"{value} ms"))
        all_row.addWidget(self.all_period_label)
        apply_all = QPushButton("Apply to all")
        apply_all.clicked.connect(
            lambda: self.led_all_requested.emit(PATTERN_VALUES.get(self.all_pattern.currentText(), 0), self.all_period.value())
        )
        all_row.addWidget(apply_all)
        leds_card.add_layout(all_row)
        self.add_card(leds_card)

        tasks_card = SectionCard("Tasks", "stack high-water marks")
        self.tasks_table = QTableWidget(0, 4)
        self.tasks_table.setHorizontalHeaderLabels(["Task", "Priority", "State", "Stack high-water"])
        self.tasks_table.verticalHeader().setVisible(False)
        self.tasks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tasks_table.horizontalHeader().setStretchLastSection(True)
        self.tasks_table.setMaximumHeight(180)
        tasks_card.add_widget(self.tasks_table)
        self.add_card(tasks_card)

        fault_card = SectionCard("Reset and fault")
        self.fault_grid = KeyValueGrid()
        fault_card.add_widget(self.fault_grid)
        self.add_card(fault_card)

        actions = QHBoxLayout()
        clear = QPushButton(icon("check", COLORS["pass"], 14), "Clear Fault")
        clear.clicked.connect(self.clear_fault_requested.emit)
        actions.addWidget(clear)
        reset = QPushButton(icon("power", COLORS["secondary"], 14), "Reset")
        reset.clicked.connect(self.reset_requested.emit)
        actions.addWidget(reset)
        boot = QPushButton(icon("flash", COLORS["secondary"], 14), "Enter Bootloader")
        boot.clicked.connect(self.bootloader_requested.emit)
        actions.addWidget(boot)
        actions.addStretch(1)
        holder = QWidget()
        holder.setLayout(actions)
        self.add_card(holder)
        self.add_stretch()

    def set_status(self, status: dict[str, Any] | None) -> None:
        self.status = status
        if not status:
            self.stats.set_value("Uptime", "—")
            self.stats.set_value("Slot", "—")
            self.stats.set_value("Trial", "—")
            self.stats.set_value("Health", "—")
            self.stats.set_value("Button", "—")
            self.status_grid.set_items({})
            return
        self.stats.set_value("Uptime", self._uptime(status.get("uptime_ms", 0)))
        self.stats.set_value("Slot", status.get("slot_name", "—"))
        self.stats.set_value(
            "Trial",
            status.get("trial_name", "—"),
            COLORS["pass"] if status.get("trial_name") == "CONFIRMED" else COLORS["warning"],
        )
        self.stats.set_value(
            "Health",
            status.get("health_name", "—"),
            COLORS["pass"] if status.get("health_name") == "PASSED" else COLORS["fail"],
        )
        self.status_grid.set_items(
            {
                "Firmware": f"{status.get('firmware_name', '')} {status.get('version', '')}",
                "Git commit": status.get("commit") or "—",
                "Build time": status.get("build_time") or "—",
                "Chip UID": f"{int(status.get('uid', 0)):024X}",
                "Slot": status.get("slot_name", "—"),
                "Trial state": f"{status.get('trial_name', '—')} ({status.get('trial_count', 0)} trial starts)",
                "Reset cause": status.get("reset_cause_text") or f"0x{int(status.get('reset_cause', 0)):08X}",
                "Heap free": f"{int(status.get('heap_free', 0)):,} bytes",
                "Heap minimum": f"{int(status.get('heap_min_free', 0)):,} bytes",
                "Protocol": f"{status.get('protocol_major')}.{status.get('protocol_minor')}",
            }
        )
        for control, led_id in ((self.led1, LedId.LD1), (self.led2, LedId.LD2), (self.led3, LedId.LD3)):
            entry = next((led for led in status.get("leds", []) if led.get("led") == led_id), None)
            if entry:
                if control is self.led3:
                    control.set_pattern(entry.get("pattern_name", "OFF"), int(entry.get("period_ms", 500)))
                else:
                    control.set_state(entry.get("pattern_name", "OFF"), int(entry.get("period_ms", 500)))
        tasks = status.get("tasks") or []
        self.tasks_table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            for column, value in enumerate(
                [task.get("name", ""), task.get("priority", ""), task.get("state", ""), task.get("stack_high_water", "")]
            ):
                self.tasks_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.tasks_table.resizeColumnsToContents()
        fault = status.get("fault") or {}
        if fault.get("present"):
            self.fault_grid.set_items(
                {
                    "Fault": fault.get("reason", "present"),
                    "Task": fault.get("task") or "—",
                    "Location": f"{fault.get('file', '')}:{fault.get('line', 0)}",
                    "CFSR / HFSR": f"0x{int(fault.get('cfsr', 0)):08X} / 0x{int(fault.get('hfsr', 0)):08X}",
                    "MMFAR / BFAR": f"0x{int(fault.get('mmfar', 0)):08X} / 0x{int(fault.get('bfar', 0)):08X}",
                    "PC / LR": f"0x{int(fault.get('pc', 0)):08X} / 0x{int(fault.get('lr', 0)):08X}",
                }
            )
            self.fault_grid.setStyleSheet(f"color: {COLORS['fail']};")
        else:
            self.fault_grid.set_items({"Fault": "none", "Reset cause": status.get("reset_cause_text") or "—"})
            self.fault_grid.setStyleSheet("")

    @staticmethod
    def _uptime(value: Any) -> str:
        try:
            seconds = int(value) // 1000
        except (TypeError, ValueError):
            return "—"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{secs:02d}"

    def button_event(self, event: dict[str, Any]) -> None:
        self.stats.set_value(
            "Button",
            f"B1 {event.get('press_name', '')}",
            COLORS["accent"],
        )
        self.led1.set_state(
            str(event.get("pattern_name", "OFF")),
            int(event.get("period_ms", 1000) or 1000),
        )
