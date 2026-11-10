"""Firmware update over UART (SRS section 9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QWidget,
)

from hwval_studio.config import Preferences
from hwval_studio.core.client import Identity
from hwval_studio.firmware import FirmwareImage, ImageError, compare_versions, parse_image
from hwval_studio.ui.pages.base import ScrollPage, SectionCard
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import KeyValueGrid, StatusPill


class SlotCard(SectionCard):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(name, parent=parent)
        self.name = name
        self.pill = StatusPill("NOT RUN", "EMPTY")
        self.header.addWidget(self.pill)
        self.grid = KeyValueGrid()
        self.add_widget(self.grid)

    def set_slot(self, slot: dict[str, Any] | None, active: bool) -> None:
        if not slot:
            self.grid.set_items({"State": "Empty"})
            self.pill.set_state("NOT RUN", "EMPTY")
            return
        if not slot.get("present"):
            state = "EMPTY"
            state_key = "N/A"
        elif slot.get("rejected"):
            state = "REJECTED"
            state_key = "FAIL"
        elif slot.get("pending"):
            state = "PENDING"
            state_key = "SKIP"
        elif slot.get("confirmed"):
            state = "CONFIRMED"
            state_key = "PASS"
        elif slot.get("valid"):
            state = "VALID"
            state_key = "INFO"
        else:
            state = "INVALID"
            state_key = "FAIL"
        if active:
            state += " · ACTIVE"
        self.pill.set_state(state_key, state)
        commit = slot.get("git_commit") or "—"
        self.grid.set_items(
            {
                "Version": slot.get("version_text", "—"),
                "Name": slot.get("name") or "—",
                "Build time": self._time(slot.get("build_timestamp", 0)),
                "Git commit": commit[:12],
                "Size": f"{int(slot.get('image_size', 0)):,} bytes",
                "Sequence": slot.get("sequence", 0),
                "Trial count": slot.get("trial_count", 0),
                "Detail": slot.get("detail") or "—",
            }
        )

    @staticmethod
    def _time(value: Any) -> str:
        try:
            from datetime import datetime

            stamp = int(value)
            if not stamp:
                return "—"
            return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return "—"


class UpdatePage(ScrollPage):
    update_requested = Signal(object, bool)
    cancel_requested = Signal()
    bootloader_requested = Signal()
    provision_requested = Signal()
    refresh_requested = Signal()
    activate_requested = Signal()

    def __init__(self, preferences: Preferences, parent: QWidget | None = None) -> None:
        super().__init__("Update (UART)", "A/B bootloader update over the ST-LINK VCP", "update", parent)
        self.preferences = preferences
        self.identity: Identity | None = None
        self.boot_info: dict[str, Any] | None = None
        self.image: FirmwareImage | None = None
        self._busy = False
        self.setAcceptDrops(True)

        refresh = QPushButton(icon("refresh", COLORS["secondary"], 14), "Refresh")
        refresh.clicked.connect(self.refresh_requested.emit)
        self.add_action(refresh)

        self.slots_row = QWidget()
        slots_layout = QHBoxLayout(self.slots_row)
        slots_layout.setContentsMargins(0, 0, 0, 0)
        slots_layout.setSpacing(10)
        self.slot_a = SlotCard("Slot A")
        self.slot_b = SlotCard("Slot B")
        slots_layout.addWidget(self.slot_a, 1)
        slots_layout.addWidget(self.slot_b, 1)
        self.add_card(self.slots_row)

        self.notice_card = SectionCard("UART update")
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("Secondary")
        self.notice_card.add_widget(self.notice)
        self.boot_button = QPushButton(icon("flash", COLORS["secondary"], 14), "Enter Bootloader")
        self.boot_button.clicked.connect(self.bootloader_requested.emit)
        self.notice_card.body.addWidget(self.boot_button)
        self.provision_button = QPushButton("Provision Product Configuration…")
        self.provision_button.clicked.connect(self.provision_requested.emit)
        self.notice_card.body.addWidget(self.provision_button)
        self.add_card(self.notice_card)

        self.file_card = SectionCard("Image file", "drag and drop a .img file here")
        file_row = QHBoxLayout()
        self.file_label = QLabel("No image selected")
        self.file_label.setObjectName("Secondary")
        self.file_label.setWordWrap(True)
        file_row.addWidget(self.file_label, 1)
        browse = QPushButton(icon("folder", COLORS["secondary"], 14), "Choose…")
        browse.clicked.connect(self.choose_file)
        file_row.addWidget(browse)
        self.file_card.add_layout(file_row)
        self.image_grid = KeyValueGrid()
        self.file_card.add_widget(self.image_grid)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600;")
        self.file_card.add_widget(self.warning_label)
        self.warning_label.hide()
        self.add_card(self.file_card)

        self.progress_card = SectionCard("Progress")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_card.add_widget(self.progress)
        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("Secondary")
        self.progress_card.add_widget(self.progress_label)
        controls = QHBoxLayout()
        self.activate = QCheckBox("Activate and reboot after verification")
        self.activate.setChecked(preferences.auto_activate)
        controls.addWidget(self.activate)
        controls.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        controls.addWidget(self.cancel_button)
        self.update_button = QPushButton(icon("update", "#FFFFFF", 14), "Update Firmware")
        self.update_button.setObjectName("Accent")
        self.update_button.clicked.connect(self.request_update)
        controls.addWidget(self.update_button)
        self.progress_card.add_layout(controls)
        self.add_card(self.progress_card)
        self.add_stretch()
        self.set_role(0)

    # -- state ---------------------------------------------------------
    def set_role(self, role: int) -> None:
        self.role = role
        self.slots_row.setVisible(role == 2)
        if role == 1:
            self.notice.setText(
                "HWVAL is running in the <b>bench configuration</b> (single-bank flash). "
                "A UART update needs the product configuration (dual-bank flash with BOOT). "
                "Use Tools › Provision Product Configuration to install BOOT and switch the option bytes. "
                "All flash contents will be lost."
            )
            self.boot_button.hide()
            self.provision_button.show()
            self.file_card.setEnabled(False)
            self.progress_card.setEnabled(False)
        elif role == 2:
            self.notice.setText(
                "The bootloader is ready. Choose a <code>.img</code> file, check the header fields, then update. "
                "Only the inactive slot is written; the device verifies CRC32 before activation."
            )
            self.boot_button.hide()
            self.provision_button.hide()
            self.file_card.setEnabled(True)
            self.progress_card.setEnabled(True)
        elif role == 3:
            self.notice.setText(
                "The demo application is running. Starting an update asks it to enter the bootloader and reconnects "
                "automatically before uploading."
            )
            self.boot_button.show()
            self.provision_button.hide()
            self.file_card.setEnabled(True)
            self.progress_card.setEnabled(True)
        else:
            self.notice.setText("Connect to BOOT or DEMO to update firmware over UART.")
            self.boot_button.hide()
            self.provision_button.hide()
            self.file_card.setEnabled(False)
            self.progress_card.setEnabled(False)
        self.update_button.setEnabled(role in (2, 3) and self.image is not None and not self._busy)

    def set_identity(self, identity: Identity | None) -> None:
        self.identity = identity
        self.set_role(identity.role if identity else 0)

    def set_boot_info(self, info: dict[str, Any] | None) -> None:
        self.boot_info = info
        if not info:
            self.slot_a.set_slot(None, False)
            self.slot_b.set_slot(None, False)
            return
        active = info.get("active_slot")
        for slot in info.get("slots", []):
            card = self.slot_a if slot.get("slot") == 1 else self.slot_b
            card.set_slot(slot, slot.get("slot") == active)
        self._update_warnings()

    # -- file ----------------------------------------------------------
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a bootloader image",
            self.preferences.last_folder("image"),
            "Firmware images (*.img);;All files (*)",
        )
        if path:
            self.preferences.set_last_folder("image", str(Path(path).parent))
            self.load_image(path)

    def load_image(self, path: str | Path) -> None:
        try:
            image = parse_image(path)
        except ImageError as exc:
            QMessageBox.critical(self, "Invalid image", str(exc))
            return
        self.image = image
        self.file_label.setText(str(image.path))
        self.image_grid.set_items(
            {
                "Name": image.name or "—",
                "Version": image.version_text,
                "Size": f"{image.size:,} bytes",
                "CRC32": f"0x{image.crc32:08X}",
                "Load address": f"0x{int(image.header.get('load_address', 0)):08X}",
                "Entry address": f"0x{int(image.header.get('entry_address', 0)):08X}",
                "Build time": SlotCard._time(image.header.get("build_timestamp", 0)),
                "Git commit": bytes(image.header.get("git_commit", b"")).hex()[:12] or "—",
                "SHA-256": image.sha256[:32] + "…",
            }
        )
        self.file_label.setToolTip(image.sha256)
        self._update_warnings()
        self.update_button.setEnabled(self.role in (2, 3) and not self._busy)

    def _update_warnings(self) -> None:
        warnings: list[str] = []
        if self.image is not None:
            warnings.extend(self.image.warnings)
            if self.boot_info:
                active = next(
                    (slot for slot in self.boot_info.get("slots", []) if slot.get("slot") == self.boot_info.get("active_slot")),
                    None,
                )
                if active:
                    warnings.extend(compare_versions(self.image, active))
        self.warning_label.setText("\n".join(f"⚠ {warning}" for warning in warnings))
        self.warning_label.setVisible(bool(warnings))

    # -- update --------------------------------------------------------
    def request_update(self) -> None:
        if self.image is None:
            QMessageBox.information(self, "Update", "Choose a .img file first.")
            return
        warnings: list[str] = list(self.image.warnings)
        if self.boot_info:
            active = next(
                (slot for slot in self.boot_info.get("slots", []) if slot.get("slot") == self.boot_info.get("active_slot")),
                None,
            )
            if active:
                warnings.extend(compare_versions(self.image, active))
        if warnings:
            box = QMessageBox(self)
            box.setWindowTitle("Confirm firmware update")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("The image differs from the active slot. Continue?")
            box.setInformativeText("\n".join(f"• {warning}" for warning in warnings))
            box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
        self.set_busy(True)
        self.update_requested.emit(self.image, self.activate.isChecked())

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update_button.setEnabled(not busy and self.role in (2, 3) and self.image is not None)
        self.cancel_button.setEnabled(busy)
        self.file_card.setEnabled(not busy)
        self.activate.setEnabled(not busy)

    def set_state(self, state: str) -> None:
        if state == "updating":
            self.set_busy(True)
            self.progress_label.setText("Starting update…")
        elif state == "uploading":
            self.progress_label.setText("Uploading…")
        elif state == "waiting for confirmation":
            self.progress_label.setText("Waiting for the application to confirm…")
        elif state == "entering bootloader":
            self.progress_label.setText("Entering bootloader…")
        elif state == "cancelling":
            self.progress_label.setText("Cancelling…")
        elif state == "idle":
            if not self._busy:
                self.progress_label.setText("Ready")

    def show_progress(self, done: int, total: int, speed: float) -> None:
        percent = int(done * 100 / total) if total else 0
        self.progress.setValue(percent)
        eta = ""
        if speed > 0 and total > done:
            eta = f" · {int((total - done) / speed)} s remaining"
        self.progress_label.setText(
            f"{done:,} / {total:,} bytes ({percent}%) · {speed / 1024:.1f} KB/s{eta}"
        )

    def show_finished(self, payload: dict[str, Any]) -> None:
        self.set_busy(False)
        self.progress.setValue(100)
        result = payload.get("result", {})
        image = payload.get("image")
        watch = payload.get("watch") or {}
        if result.get("success"):
            text = f"Update verified, CRC 0x{int(result.get('image_crc32', 0)):08X}."
            if self.activate.isChecked():
                trial = watch.get("trial_name", "UNKNOWN")
                text += f" Application state: {trial}."
                if watch.get("error"):
                    text += f" (confirmation watch: {watch['error']})"
            self.progress_label.setText(text)
        else:
            self.progress_label.setText(f"Update failed: {result.get('error_name', '')} {result.get('detail', '')}")
        if image:
            self.file_label.setText(str(image.path))

    def show_failed(self, message: str) -> None:
        self.set_busy(False)
        self.progress_label.setText(f"Update failed: {message}")
        QMessageBox.critical(self, "Firmware update failed", message)

    # -- drag and drop -------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.load_image(url.toLocalFile())
                break
        event.acceptProposedAction()
