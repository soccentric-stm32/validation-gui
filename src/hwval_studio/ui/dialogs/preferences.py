"""Preferences window with immediate-apply tabs (SRS section 15)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.config import Preferences, TestPreset
from hwval_studio.firmware.openocd import find_openocd, openocd_version, version_supported
from hwval_studio.ui.widgets import ToggleSwitch


def _line_edit(value: str, placeholder: str = "") -> QLineEdit:
    edit = QLineEdit(value)
    edit.setPlaceholderText(placeholder)
    return edit


class PreferencesDialog(QDialog):
    database_changed = Signal(str)

    def __init__(self, preferences: Preferences, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle("Preferences")
        self.resize(660, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_general()
        self._build_connection()
        self._build_tests()
        self._build_firmware()
        self._build_history()
        self._build_operator()
        bottom = QHBoxLayout()
        note = QLabel("Changes apply immediately.")
        note.setObjectName("Secondary")
        bottom.addWidget(note)
        bottom.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Accent")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        layout.addLayout(bottom)

    # -- helpers -------------------------------------------------------
    def _page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 14, 16, 14)
        heading = QLabel(title)
        heading.setObjectName("Heading")
        outer.addWidget(heading)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignRight)
        outer.addLayout(form)
        outer.addStretch(1)
        self.tabs.addTab(page, title)
        return page, outer

    @staticmethod
    def _form(outer: QVBoxLayout) -> QFormLayout:
        return outer.itemAt(1).layout()  # type: ignore[return-value]

    def _folder_widget(self, value: str, kind: str, on_change) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        edit = _line_edit(value)
        edit.editingFinished.connect(lambda: on_change(edit.text().strip()))
        row.addWidget(edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse(edit, kind, on_change))
        row.addWidget(browse)
        return holder

    def _browse(self, edit: QLineEdit, kind: str, on_change) -> None:
        if kind == "dir":
            path = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text() or str(Path.home()))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choose file", edit.text() or str(Path.home()))
        if path:
            edit.setText(path)
            on_change(path)

    # -- tabs ----------------------------------------------------------
    def _build_general(self) -> None:
        page, outer = self._page("General")
        form = outer.itemAt(1).layout()
        start_operator = ToggleSwitch("Start in operator mode")
        start_operator.setChecked(self.preferences.start_in_operator_mode)
        start_operator.toggled.connect(lambda value: setattr(self.preferences, "start_in_operator_mode", value))
        form.addRow("Start-up", start_operator)
        show_log = ToggleSwitch("Show the log console on start")
        show_log.setChecked(self.preferences.show_log_on_start)
        show_log.toggled.connect(lambda value: setattr(self.preferences, "show_log_on_start", value))
        form.addRow("Log", show_log)
        confirm_quit = ToggleSwitch("Confirm before quitting during a run")
        confirm_quit.setChecked(self.preferences.confirm_quit_during_run)
        confirm_quit.toggled.connect(lambda value: setattr(self.preferences, "confirm_quit_during_run", value))
        form.addRow("Quit", confirm_quit)

    def _build_connection(self) -> None:
        page, outer = self._page("Connection")
        form = outer.itemAt(1).layout()
        default_port = _line_edit(self.preferences.default_port, "e.g. /dev/ttyACM0 or COM3")
        default_port.editingFinished.connect(lambda: setattr(self.preferences, "default_port", default_port.text().strip()))
        form.addRow("Default port", default_port)
        auto = ToggleSwitch("Auto-connect to the last used port at start-up")
        auto.setChecked(self.preferences.auto_connect)
        auto.toggled.connect(lambda value: setattr(self.preferences, "auto_connect", value))
        form.addRow("Auto-connect", auto)
        fast = ToggleSwitch("Use 921600 baud for bulk transfers")
        fast.setChecked(self.preferences.fast_baud)
        fast.toggled.connect(lambda value: setattr(self.preferences, "fast_baud", value))
        form.addRow("Fast baud", fast)
        form.addRow("Last port", QLabel(self.preferences.last_port or "—"))

    def _build_tests(self) -> None:
        page, outer = self._page("Tests")
        form = outer.itemAt(1).layout()
        preset = self.preferences.test_preset
        self.test_levels: dict[str, QCheckBox] = {}
        levels_widget = QWidget()
        levels_row = QHBoxLayout(levels_widget)
        levels_row.setContentsMargins(0, 0, 0, 0)
        for level in ("S", "L", "E"):
            box = QCheckBox(level)
            box.setChecked(level in set(preset.levels.replace(" ", "").split(",")))
            box.toggled.connect(self._save_test_preset)
            levels_row.addWidget(box)
            self.test_levels[level] = box
        levels_row.addStretch(1)
        form.addRow("Default levels", levels_widget)
        self.test_operator = ToggleSwitch("Allow operator tests by default")
        self.test_operator.setChecked(preset.allow_operator)
        self.test_operator.toggled.connect(self._save_test_preset)
        form.addRow("Operator tests", self.test_operator)
        self.test_repeat = QSpinBox()
        self.test_repeat.setRange(1, 9999)
        self.test_repeat.setValue(max(1, preset.repeat))
        self.test_repeat.valueChanged.connect(self._save_test_preset)
        form.addRow("Repeat count", self.test_repeat)
        self.test_until_fail = ToggleSwitch("Repeat until the first failure")
        self.test_until_fail.setChecked(preset.until_fail)
        self.test_until_fail.toggled.connect(self._save_test_preset)
        form.addRow("Until fail", self.test_until_fail)
        form.addRow("Destructive tests", QLabel("Off by default and reset after every run (TST-022)."))

    def _save_test_preset(self) -> None:
        levels = ",".join(level for level, box in self.test_levels.items() if box.isChecked()) or "S"
        preset = TestPreset(
            levels=levels,
            allow_operator=self.test_operator.isChecked(),
            allow_destructive=False,
            repeat=self.test_repeat.value(),
            until_fail=self.test_until_fail.isChecked(),
        )
        self.preferences.test_preset = preset

    def _build_firmware(self) -> None:
        page, outer = self._page("Firmware")
        form = outer.itemAt(1).layout()
        self.openocd_edit = _line_edit(self.preferences.openocd_path, "openocd or an absolute path")
        self.openocd_edit.editingFinished.connect(self._save_openocd)
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.openocd_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_openocd)
        path_layout.addWidget(browse)
        check = QPushButton("Check")
        check.clicked.connect(self._check_openocd)
        path_layout.addWidget(check)
        form.addRow("OpenOCD", path_row)
        self.openocd_status = QLabel()
        self.openocd_status.setObjectName("Secondary")
        form.addRow("Status", self.openocd_status)
        self._refresh_openocd_status()
        folder = self._folder_widget(
            self.preferences.image_folder,
            "dir",
            lambda value: setattr(self.preferences, "image_folder", value),
        )
        form.addRow("Image folder", folder)
        auto_activate = ToggleSwitch("Activate and reboot automatically after upload")
        auto_activate.setChecked(self.preferences.auto_activate)
        auto_activate.toggled.connect(lambda value: setattr(self.preferences, "auto_activate", value))
        form.addRow("After upload", auto_activate)

    def _browse_openocd(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the OpenOCD executable", self.openocd_edit.text())
        if path:
            self.openocd_edit.setText(path)
            self._save_openocd()

    def _save_openocd(self) -> None:
        self.preferences.openocd_path = self.openocd_edit.text().strip()
        self._refresh_openocd_status()

    def _check_openocd(self) -> None:
        self._refresh_openocd_status(verbose=True)

    def _refresh_openocd_status(self, verbose: bool = False) -> None:
        executable = find_openocd(self.preferences.openocd_path)
        if not executable:
            self.openocd_status.setText("Not found; put OpenOCD on PATH or browse to the executable.")
            if verbose:
                QMessageBox.warning(self, "OpenOCD", "OpenOCD was not found. Install version 0.12 or newer.")
            return
        try:
            version = openocd_version(executable)
        except Exception as exc:
            self.openocd_status.setText(f"Cannot run: {exc}")
            return
        supported = version_supported(version)
        self.openocd_status.setText(f"{version} at {executable}" + ("" if supported else " — too old (need ≥ 0.12)"))
        if verbose and not supported:
            QMessageBox.warning(self, "OpenOCD", "OpenOCD 0.12 or newer is required.")

    def _build_history(self) -> None:
        page, outer = self._page("History")
        form = outer.itemAt(1).layout()
        # A database is a file, but the user usually chooses a folder; use a
        # dedicated line edit with a file dialog instead.
        db_row = QWidget()
        db_layout = QHBoxLayout(db_row)
        db_layout.setContentsMargins(0, 0, 0, 0)
        self.db_edit = _line_edit(self.preferences.database_path, "Leave empty for the default application-data location")
        self.db_edit.editingFinished.connect(lambda: self._set_database_path(self.db_edit.text().strip()))
        db_layout.addWidget(self.db_edit, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_database)
        db_layout.addWidget(choose)
        form.addRow("Database", db_row)
        retention = QSpinBox()
        retention.setRange(0, 3650)
        retention.setSpecialValueText("Keep all")
        retention.setValue(self.preferences.retention_days)
        retention.valueChanged.connect(lambda value: setattr(self.preferences, "retention_days", value))
        form.addRow("Retention", retention)
        export_folder = self._folder_widget(
            self.preferences.auto_export_folder,
            "dir",
            lambda value: setattr(self.preferences, "auto_export_folder", value),
        )
        form.addRow("Auto-export folder", export_folder)
        purge = QPushButton("Purge older runs now")
        purge.clicked.connect(self._purge)
        form.addRow("Maintenance", purge)

    def _choose_database(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "History database",
            self.db_edit.text() or str(Path.home() / "hwval-history.sqlite"),
            "SQLite (*.sqlite *.db);;All files (*)",
        )
        if path:
            self.db_edit.setText(path)
            self._set_database_path(path)

    def _set_database_path(self, path: str) -> None:
        self.preferences.database_path = path
        self.database_changed.emit(path)

    def _purge(self) -> None:
        days = self.preferences.retention_days
        if days <= 0:
            QMessageBox.information(self, "Retention", "Retention is set to keep all runs.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Purge history")
        box.setText(f"Delete runs older than {days} days?")
        box.setInformativeText("Deletion is permanent.")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            QMessageBox.information(self, "Retention", "The history page applies retention at start-up and when runs are deleted.")

    def _build_operator(self) -> None:
        page, outer = self._page("Operator")
        form = outer.itemAt(1).layout()
        preset = self.preferences.operator_preset
        levels_widget = QWidget()
        levels_row = QHBoxLayout(levels_widget)
        levels_row.setContentsMargins(0, 0, 0, 0)
        self.operator_levels: dict[str, QCheckBox] = {}
        for level in ("S", "L", "E"):
            box = QCheckBox(level)
            box.setChecked(level in set(preset.levels.replace(" ", "").split(",")))
            box.toggled.connect(self._save_operator_preset)
            levels_row.addWidget(box)
            self.operator_levels[level] = box
        levels_row.addStretch(1)
        form.addRow("Run selection levels", levels_widget)
        self.operator_allow = ToggleSwitch("Allow operator tests")
        self.operator_allow.setChecked(preset.allow_operator)
        self.operator_allow.toggled.connect(self._save_operator_preset)
        form.addRow("Operator tests", self.operator_allow)
        form.addRow("Destructive tests", QLabel("Never allowed in operator mode."))
        self.pin_edit = QLineEdit(self.preferences.operator_pin)
        self.pin_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_edit.setPlaceholderText("Optional PIN to leave operator mode")
        self.pin_edit.editingFinished.connect(lambda: setattr(self.preferences, "operator_pin", self.pin_edit.text()))
        form.addRow("Exit PIN", self.pin_edit)
        auto_export = ToggleSwitch("Export each operator run automatically")
        auto_export.setChecked(self.preferences.operator_auto_export)
        auto_export.toggled.connect(lambda value: setattr(self.preferences, "operator_auto_export", value))
        form.addRow("Auto-export", auto_export)
        self.names = QListWidget()
        self.names.addItems(self.preferences.operator_names)
        self.names.setMaximumHeight(110)
        form.addRow("Operator names", self.names)
        buttons = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add_operator_name)
        buttons.addWidget(add)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_operator_name)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        form.addRow("", QWidget())
        outer.addLayout(buttons)

    def _save_operator_preset(self) -> None:
        levels = ",".join(level for level, box in self.operator_levels.items() if box.isChecked()) or "S"
        self.preferences.operator_preset = TestPreset(
            levels=levels,
            allow_operator=self.operator_allow.isChecked(),
            allow_destructive=False,
        )

    def _add_operator_name(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Operator name", "Name:")
        if ok and name.strip():
            self.names.addItem(name.strip())
            self._save_names()

    def _remove_operator_name(self) -> None:
        for item in self.names.selectedItems():
            self.names.takeItem(self.names.row(item))
        self._save_names()

    def _save_names(self) -> None:
        self.preferences.operator_names = [self.names.item(index).text() for index in range(self.names.count())]
