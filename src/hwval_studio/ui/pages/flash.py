"""Flashing and provisioning over SWD (SRS section 10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from hwval_studio.config import Preferences
from hwval_studio.firmware.openocd import install_hint
from hwval_studio.ui.pages.base import ScrollPage, SectionCard
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import KeyValueGrid

FLASH_FILTER = "Firmware (*.elf *.hex *.bin);;All files (*)"


def _hex(value: Any, width: int = 8) -> str:
    try:
        return f"0x{int(value):0{width}X}"
    except (TypeError, ValueError):
        return "—"


class FlashPage(ScrollPage):
    info_requested = Signal()
    openocd_check_requested = Signal()
    flash_requested = Signal(str)
    provision_requested = Signal(str)
    restore_requested = Signal(object)
    options_requested = Signal()
    provision_completed = Signal()

    def __init__(self, preferences: Preferences, parent: QWidget | None = None) -> None:
        super().__init__("Flash (SWD)", "OpenOCD flashing and product/bench provisioning", "flash", parent)
        self.preferences = preferences
        self.info: dict[str, Any] | None = None
        self._busy = False

        self.openocd_card = SectionCard("OpenOCD")
        self.openocd_grid = KeyValueGrid()
        self.openocd_card.add_widget(self.openocd_grid)
        row = QHBoxLayout()
        check = QPushButton(icon("refresh", COLORS["secondary"], 14), "Check OpenOCD")
        check.clicked.connect(self.openocd_check_requested.emit)
        row.addWidget(check)
        row.addStretch(1)
        self.openocd_card.add_layout(row)
        self.openocd_card.body.addWidget(
            QLabel(
                "OpenOCD is started for each operation and stopped afterwards so the ST-LINK is never held. "
                "Only nDBANK and nDBOOT are written; RDP, WRP and BOOT_ADD are never changed by this application."
            )
        )
        self.add_card(self.openocd_card)

        self.target_card = SectionCard("Target")
        self.target_grid = KeyValueGrid()
        self.target_card.add_widget(self.target_grid)
        detect = QPushButton(icon("search", COLORS["secondary"], 14), "Detect ST-LINK and Target")
        detect.clicked.connect(self.info_requested.emit)
        read_options = QPushButton("Read Option Bytes")
        read_options.clicked.connect(self.options_requested.emit)
        buttons = QHBoxLayout()
        buttons.addWidget(detect)
        buttons.addWidget(read_options)
        buttons.addStretch(1)
        self.target_card.add_layout(buttons)
        self.add_card(self.target_card)

        self.ops_card = SectionCard("Operations", "every flash-changing operation needs confirmation")
        flash_row = QHBoxLayout()
        self.hwval_path = QLabel("No HWVAL image selected")
        self.hwval_path.setObjectName("Secondary")
        self.hwval_path.setWordWrap(True)
        flash_row.addWidget(self.hwval_path, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.choose_hwval)
        flash_row.addWidget(choose)
        self.flash_button = QPushButton(icon("flash", "#FFFFFF", 14), "Flash HWVAL")
        self.flash_button.setObjectName("Accent")
        self.flash_button.clicked.connect(self.confirm_flash)
        flash_row.addWidget(self.flash_button)
        self.ops_card.add_layout(flash_row)

        boot_row = QHBoxLayout()
        self.boot_path = QLabel("No boot.hex selected")
        self.boot_path.setObjectName("Secondary")
        self.boot_path.setWordWrap(True)
        boot_row.addWidget(self.boot_path, 1)
        choose_boot = QPushButton("Choose…")
        choose_boot.clicked.connect(self.choose_boot)
        boot_row.addWidget(choose_boot)
        self.provision_button = QPushButton("Provision Product Configuration…")
        self.provision_button.setObjectName("Danger")
        self.provision_button.clicked.connect(self.confirm_provision)
        boot_row.addWidget(self.provision_button)
        self.ops_card.add_layout(boot_row)

        restore_row = QHBoxLayout()
        self.restore_note = QLabel("Restore single-bank flash (optionally reflash HWVAL).")
        self.restore_note.setObjectName("Secondary")
        self.restore_note.setWordWrap(True)
        restore_row.addWidget(self.restore_note, 1)
        self.restore_button = QPushButton("Restore Bench Configuration…")
        self.restore_button.clicked.connect(self.confirm_restore)
        restore_row.addWidget(self.restore_button)
        self.ops_card.add_layout(restore_row)
        self.ops_card.body.addWidget(
            QLabel(
                "Provision: nDBANK=0, nDBOOT=1, mass erase, program and verify boot.hex, reset. "
                "Restore bench: nDBANK=1, mass erase, optionally flash HWVAL."
            )
        )
        self.add_card(self.ops_card)

        self.output_card = SectionCard("OpenOCD output")
        self.output_label = QLabel("No operation yet.")
        self.output_label.setObjectName("Mono")
        self.output_label.setWordWrap(True)
        self.output_label.setTextInteractionFlags(self.output_label.textInteractionFlags() | __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.TextInteractionFlag.TextSelectableByMouse)
        self.output_label.setMaximumHeight(220)
        self.output_label.setAlignment(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignTop | __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignLeft)
        self.output_card.add_widget(self.output_label)
        self.add_card(self.output_card)
        self.add_stretch()
        self._auto_detect()
        self.set_info(None)

    def _auto_detect(self) -> None:
        from hwval_studio.firmware.openocd import find_openocd, openocd_version

        executable = find_openocd(self.preferences.openocd_path)
        if executable:
            try:
                self.set_openocd(executable, openocd_version(executable))
            except Exception:
                self.set_openocd(executable, "")
        else:
            self.set_openocd(None)

    # -- state ---------------------------------------------------------
    def set_openocd(self, path: str | None, version: str = "") -> None:
        if path:
            self.openocd_grid.set_items({"Executable": path, "Version": version or "—", "Required": "≥ 0.12"})
        else:
            self.openocd_grid.set_items({"Executable": "not found", "Required": "≥ 0.12"})
        self.flash_button.setEnabled(bool(path) and not self._busy)
        self.provision_button.setEnabled(bool(path) and not self._busy)
        self.restore_button.setEnabled(bool(path) and not self._busy)

    def set_info(self, info: dict[str, Any] | None) -> None:
        self.info = info
        if not info:
            self.target_grid.set_items({"Target": "not detected"})
            return
        options = info.get("options") or {}
        self.target_grid.set_items(
            {
                "Probe": info.get("probe", "stlink"),
                "Target": info.get("target", "stm32f7x"),
                "DEV_ID": f"0x{int(info.get('dev_id', 0)):03X}",
                "REV_ID": f"0x{int(info.get('rev_id', 0)):04X}",
                "Flash size": f"{int(info.get('flash_size_kb', 0))} KB",
                "OPTCR": _hex(info.get("optcr")),
                "OPTCR1": _hex(info.get("optcr1")),
                "RDP": options.get("RDP", "—"),
                "nDBANK / nDBOOT": f"{options.get('nDBANK', '—')} / {options.get('nDBOOT', '—')}",
                "Flash mode": options.get("flash_mode", "—"),
                "WRP bank 1 / 2": f"0x{int(options.get('WRP_BANK1', 0)):03X} / 0x{int(options.get('WRP_BANK2', 0)):03X}",
            }
        )
        self.preferences.set("firmware/last_target", {"dev_id": info.get("dev_id"), "flash_kb": info.get("flash_size_kb")})

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.flash_button.setEnabled(not busy and bool(self.info))
        self.provision_button.setEnabled(not busy)
        self.restore_button.setEnabled(not busy)

    def show_output(self, line: str) -> None:
        current = self.output_label.text()
        if current == "No operation yet.":
            current = ""
        lines = (current + "\n" + line).splitlines()
        if len(lines) > 400:
            lines = lines[-400:]
        self.output_label.setText("\n".join(lines))

    def show_finished(self, operation: str, result: dict[str, Any]) -> None:
        self.set_busy(False)
        if result.get("dev_id") is not None:
            self.set_info(result)
        self.show_output(f"✓ {operation} completed")
        if operation.lower().startswith("provision"):
            self.provision_completed.emit()

    def show_failed(self, message: str) -> None:
        self.set_busy(False)
        self.show_output(f"✗ {message}")

    def show_options(self, result: dict[str, Any]) -> None:
        options = result.get("options") or {}
        lines = "\n".join(f"{key}: {value}" for key, value in options.items())
        QMessageBox.information(self, "Option bytes", lines or "No option bytes were returned.")

    # -- file pickers --------------------------------------------------
    def choose_hwval(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose the HWVAL image",
            self.preferences.last_folder("firmware"),
            FLASH_FILTER,
        )
        if path:
            self.hwval_path.setText(path)
            self.preferences.set_last_folder("firmware", str(Path(path).parent))

    def choose_boot(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose boot.hex",
            self.preferences.last_folder("boot"),
            FLASH_FILTER,
        )
        if path:
            self.boot_path.setText(path)
            self.preferences.set_last_folder("boot", str(Path(path).parent))

    def _hwval_file(self) -> str | None:
        text = self.hwval_path.text()
        return text if Path(text).is_file() else None

    def _boot_file(self) -> str | None:
        text = self.boot_path.text()
        return text if Path(text).is_file() else None

    # -- confirmation dialogs -----------------------------------------
    def confirm_flash(self) -> None:
        path = self._hwval_file()
        if not path:
            QMessageBox.information(self, "Flash HWVAL", "Choose an HWVAL .elf, .hex or .bin file first.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Flash HWVAL")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Flash HWVAL and switch to single-bank flash?")
        box.setInformativeText(
            f"File: {path}\n\n"
            "If nDBANK needs to change, the whole flash will be erased. "
            "All existing bootloader and application contents will be lost."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.set_busy(True)
            self.flash_requested.emit(path)

    def confirm_provision(self) -> None:
        path = self._boot_file()
        if not path:
            QMessageBox.information(self, "Provision", "Choose boot.hex first.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Provision product configuration")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText("Provision this board for production?")
        box.setInformativeText(
            f"boot.hex: {path}\n\n"
            "This sets nDBANK=0 and nDBOOT=1 (dual-bank), mass-erases the entire flash, "
            "then programs and verifies the bootloader. All flash contents will be lost. "
            "RDP, WRP and BOOT_ADD are not changed."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.set_busy(True)
            self.provision_requested.emit(path)

    def confirm_restore(self) -> None:
        path = self._hwval_file()
        box = QMessageBox(self)
        box.setWindowTitle("Restore bench configuration")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText("Restore the single-bank bench configuration?")
        extra = f"\n\nHWVAL image: {path}" if path else "\n\nNo HWVAL image selected; flash will be left erased."
        box.setInformativeText(
            "This sets nDBANK=1, mass-erases the entire flash, and optionally flashes HWVAL." + extra
        )
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.set_busy(True)
            self.restore_requested.emit(path)

    def show_hint(self) -> None:
        QMessageBox.warning(self, "OpenOCD missing", install_hint())
