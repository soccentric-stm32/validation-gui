"""Device overview: identity, clocks, option bytes, harness and boot slots."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from hwval_studio.core.client import Identity
from hwval_studio.ui.pages.base import ScrollPage, SectionCard, StatRow
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import KeyValueGrid

ROLE_TEXT = {
    1: "HWVAL hardware validation firmware",
    2: "A/B bootloader",
    3: "FreeRTOS demo application",
}


def _hz(value: int | float | None) -> str:
    if not value:
        return "—"
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.3f} MHz"
    if value >= 1_000:
        return f"{value / 1_000:.1f} kHz"
    return f"{value:.0f} Hz"


def _opt_bits(value: int, shift: int, mask: int = 1) -> int:
    return (value >> shift) & mask


class OverviewPage(ScrollPage):
    refresh_requested = Signal()
    harness_requested = Signal()
    reset_requested = Signal()
    bootloader_requested = Signal()
    provision_requested = Signal()
    activate_requested = Signal()
    diagnostics_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Device", "Identity, clocks, option bytes and harness", "overview", parent)
        self.identity: Identity | None = None
        self.device_info: dict[str, Any] | None = None
        self.harness: dict[str, Any] = {}
        self.boot_info: dict[str, Any] | None = None
        self.demo_status: dict[str, Any] | None = None

        refresh = QPushButton(icon("refresh", COLORS["secondary"], 14), "Refresh")
        refresh.clicked.connect(self.refresh_requested.emit)
        self.add_action(refresh)

        self.stats = StatRow(
            [
                ("Role", "—"),
                ("Firmware", "—"),
                ("Chip UID", "—"),
                ("Flash mode", "—"),
            ]
        )
        self.add_card(self.stats)

        self.identity_card = SectionCard("Identity")
        self.identity_grid = KeyValueGrid()
        self.identity_card.add_widget(self.identity_grid)
        self.add_card(self.identity_card)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        self.clocks_card = SectionCard("Clocks")
        self.clocks_grid = KeyValueGrid()
        self.clocks_card.add_widget(self.clocks_grid)
        row_layout.addWidget(self.clocks_card, 1)
        self.options_card = SectionCard("Option bytes")
        self.options_grid = KeyValueGrid()
        self.options_card.add_widget(self.options_grid)
        row_layout.addWidget(self.options_card, 1)
        self.add_card(row)

        self.harness_card = SectionCard("Harness", "wires fitted on the bench")
        harness_actions = QHBoxLayout()
        harness_actions.addStretch(1)
        harness_button = QPushButton(icon("refresh", COLORS["secondary"], 13), "Harness Check")
        harness_button.clicked.connect(self.harness_requested.emit)
        harness_actions.addWidget(harness_button)
        self.harness_card.add_layout(harness_actions)
        self.harness_table = QTableWidget(0, 5)
        self.harness_table.setHorizontalHeaderLabels(["Wire", "From", "To", "Used by", "Fitted"])
        self.harness_table.verticalHeader().setVisible(False)
        self.harness_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.harness_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.harness_table.horizontalHeader().setStretchLastSection(True)
        self.harness_table.setMaximumHeight(190)
        self.harness_card.add_widget(self.harness_table)
        self.add_card(self.harness_card)

        self.boot_card = SectionCard("Firmware slots")
        self.boot_grid = KeyValueGrid()
        self.boot_card.add_widget(self.boot_grid)
        self.boot_buttons = QHBoxLayout()
        self.boot_buttons.addStretch(1)
        self.activate_button = QPushButton("Activate pending")
        self.activate_button.clicked.connect(self.activate_requested.emit)
        self.boot_buttons.addWidget(self.activate_button)
        self.boot_card.add_layout(self.boot_buttons)
        self.add_card(self.boot_card)
        self.boot_card.hide()

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.diag_button = QPushButton(icon("info", COLORS["secondary"], 14), "Device Information")
        self.diag_button.clicked.connect(self.diagnostics_requested.emit)
        actions.addWidget(self.diag_button)
        self.reset_button = QPushButton(icon("power", COLORS["secondary"], 14), "Reset Device")
        self.reset_button.clicked.connect(self.reset_requested.emit)
        actions.addWidget(self.reset_button)
        self.boot_button = QPushButton(icon("flash", COLORS["secondary"], 14), "Enter Bootloader")
        self.boot_button.clicked.connect(self.bootloader_requested.emit)
        actions.addWidget(self.boot_button)
        self.provision_button = QPushButton("Provision Product Configuration…")
        self.provision_button.clicked.connect(self.provision_requested.emit)
        actions.addWidget(self.provision_button)
        actions.addStretch(1)
        holder = QWidget()
        holder.setLayout(actions)
        self.add_card(holder)
        self.add_stretch()

    # -- state ---------------------------------------------------------
    def set_identity(self, identity: Identity | None) -> None:
        self.identity = identity
        if identity is None:
            self.stats.set_value("Role", "—")
            self.stats.set_value("Firmware", "—")
            self.stats.set_value("Chip UID", "—")
            self.stats.set_value("Flash mode", "—")
            self.identity_grid.set_items({})
            self.subtitle_label.setText("Not connected")
            return
        self.stats.set_value("Role", identity.role_name)
        self.stats.set_value("Firmware", f"{identity.firmware_name} {identity.version}")
        self.stats.set_value("Chip UID", identity.uid_hex)
        self.stats.set_value("Flash mode", identity.flash_mode_name)
        self.subtitle_label.setText(f"{ROLE_TEXT.get(identity.role, identity.role_name)} · {identity.firmware_name} {identity.version}")
        self.identity_grid.set_items(
            {
                "Firmware": f"{identity.firmware_name} {identity.version}",
                "Git commit": identity.commit or "—",
                "Build time": identity.build_time or "—",
                "Role": identity.role_name,
                "Chip UID": identity.uid_hex,
                "DEV_ID / REV_ID": f"0x{identity.dev_id:03X} / 0x{identity.rev_id:04X}",
                "Flash mode": identity.flash_mode_name,
                "Protocol": f"{identity.protocol_major}.{identity.protocol_minor}",
                "Max frame": f"{identity.max_frame} bytes",
                "Detail": identity.detail or "—",
            }
        )
        self.diag_button.setVisible(identity.role == 1)
        self.reset_button.setVisible(identity.role != 0)
        self.boot_button.setVisible(identity.role == 3)
        self.provision_button.setVisible(identity.role == 1)
        self.harness_card.setVisible(identity.role == 1)

    def set_device_info(self, info: dict[str, Any] | None) -> None:
        self.device_info = info
        if not info:
            self.clocks_grid.set_items({})
            self.options_grid.set_items({})
            return
        self.clocks_grid.set_items(
            {
                "SYSCLK": _hz(info.get("sysclk_hz")),
                "HCLK": _hz(info.get("hclk_hz")),
                "PCLK1": _hz(info.get("pclk1_hz")),
                "PCLK2": _hz(info.get("pclk2_hz")),
                "APB1 timer": _hz(info.get("apb1_tim_hz")),
                "APB2 timer": _hz(info.get("apb2_tim_hz")),
                "PLLQ / 48 MHz": _hz(info.get("pllq_hz")),
                "Reset cause": info.get("reset_cause_text") or f"0x{int(info.get('reset_cause', 0)):08X}",
                "Uptime": self._uptime(info.get("uptime_ms", 0)),
            }
        )
        optcr = int(info.get("optcr", 0))
        optcr1 = int(info.get("optcr1", 0))
        self.options_grid.set_items(
            {
                "OPTCR": f"0x{optcr:08X}",
                "OPTCR1": f"0x{optcr1:08X}",
                "RDP": _opt_bits(optcr, 8, 0xFF),
                "nWRP bank 1": f"0x{_opt_bits(optcr, 16, 0xFFF):03X}",
                "nWRP bank 2": f"0x{_opt_bits(optcr1, 0, 0xFFF):03X}",
                "nDBOOT": _opt_bits(optcr, 28),
                "nDBANK": _opt_bits(optcr, 29),
                "Flash size": f"{info.get('flash_size_kb', 0)} KB",
                "Package": info.get("package") or "—",
            }
        )

    @staticmethod
    def _uptime(value: Any) -> str:
        try:
            seconds = int(value) // 1000
        except (TypeError, ValueError):
            return "—"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{secs:02d}"

    def set_harness(self, harness: dict[str, Any] | None) -> None:
        self.harness = harness or {}
        wires = self.harness.get("wires", [])
        self.harness_table.setRowCount(len(wires))
        for row, wire in enumerate(wires):
            values = [
                wire.get("name", ""),
                wire.get("pin_a", ""),
                wire.get("pin_b", ""),
                wire.get("used_by", ""),
                "✓ fitted" if wire.get("fitted") else "— missing",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 4:
                    item.setForeground(QColor(COLORS["pass"] if wire.get("fitted") else COLORS["skip"]))
                self.harness_table.setItem(row, column, item)
        self.harness_table.resizeColumnsToContents()
        self.harness_table.horizontalHeader().setStretchLastSection(True)

    def mark_missing_harness(self, tests: list[Any]) -> set[str]:
        missing: set[str] = set()
        for wire in self.harness.get("wires", []):
            if not wire.get("fitted"):
                for test_id in str(wire.get ("used_by", "")).replace(";", ",").split(","):
                    test_id = test_id.strip()
                    if test_id:
                        missing.add(test_id)
                for test in tests:
                    if wire.get("name") and wire.get("name") in str(getattr(test, "needs", "")):
                        missing.add(test.id)
        return missing

    def set_boot_info(self, info: dict[str, Any] | None) -> None:
        self.boot_info = info
        if not info:
            self.boot_card.hide()
            return
        self.boot_card.show()
        rows: dict[str, str] = {
            "Active slot": info.get("active_slot_name", "—"),
            "Last outcome": info.get("last_outcome_name", "—"),
            "Rejected slot": info.get("rejected_slot_name", "—"),
            "Flash mode": info.get("flash_mode_name", "—"),
        }
        for slot in info.get("slots", []):
            state = "empty"
            if slot.get("present"):
                state = "pending" if slot.get("pending") else ("confirmed" if slot.get("confirmed") else ("rejected" if slot.get("rejected") else "valid"))
            rows[f"Slot {slot.get('slot_name')}"] = (
                f"{slot.get('version_text', '')} {slot.get('name', '')} · {state} · {int(slot.get('image_size', 0)):,} B"
            )
        self.boot_grid.set_items(rows)
        has_pending = any(slot.get("pending") for slot in info.get("slots", []))
        self.activate_button.setVisible(has_pending)

    def set_role(self, role: int) -> None:
        self.boot_card.setVisible(role == 2)
        self.harness_card.setVisible(role == 1)
        self.diag_button.setVisible(role == 1)
        self.boot_button.setVisible(role == 3)
        self.provision_button.setVisible(role == 1)
