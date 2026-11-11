"""Run history browser (SRS section 12)."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from hwval_studio.config import Preferences
from hwval_studio.persistence.database import HistoryStore
from hwval_studio.persistence.reports import export_run
from hwval_studio.ui.charts import RunTrendChart, points_from_runs
from hwval_studio.ui.dialogs.history_dialogs import CompareDialog, RunDetailDialog
from hwval_studio.ui.pages.base import Page
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import SearchBox


class HistoryPage(Page):
    runs_changed = Signal()

    def __init__(self, store: HistoryStore, preferences: Preferences, parent: QWidget | None = None) -> None:
        super().__init__("History", "Every run is stored locally in SQLite", "history", parent)
        self.store = store
        self.preferences = preferences
        self._test_filter = ""

        toolbar = QWidget()
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        self.board_filter = SearchBox("Board UID…")
        self.board_filter.setMaximumWidth(190)
        self.board_filter.textChanged.connect(self.refresh)
        bar.addWidget(self.board_filter)
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("yyyy-MM-dd")
        today = datetime.now(UTC).date()
        self.from_date.setDate(QDate(today.year, today.month, today.day).addMonths(-1))
        self.from_date.setToolTip("From date")
        bar.addWidget(self.from_date)
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("yyyy-MM-dd")
        self.to_date.setDate(QDate(today.year, today.month, today.day))
        self.to_date.setToolTip("To date")
        bar.addWidget(self.to_date)
        self.result_filter = QComboBox()
        self.result_filter.addItems(["All results", "PASS", "FAIL", "SKIP", "N/A"])
        self.result_filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.result_filter)
        self.fw_filter = SearchBox("Firmware version…")
        self.fw_filter.setMaximumWidth(160)
        self.fw_filter.textChanged.connect(self.refresh)
        bar.addWidget(self.fw_filter)
        self.mode_filter = QComboBox()
        self.mode_filter.addItems(["All modes", "ENGINEER", "OPERATOR", "CLI", "IMPORTED"])
        self.mode_filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.mode_filter)
        bar.addStretch(1)
        refresh = QPushButton(icon("refresh", COLORS["secondary"], 14), "Refresh")
        refresh.clicked.connect(self.refresh)
        bar.addWidget(refresh)
        self.body.addWidget(toolbar)
        self.test_filter_label = QLabel()
        self.test_filter_label.setObjectName("Secondary")
        self.test_filter_label.hide()
        clear_filter = QPushButton("Clear test filter")
        clear_filter.clicked.connect(self.clear_test_filter)
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.test_filter_label)
        filter_row.addWidget(clear_filter)
        filter_row.addStretch(1)
        self.test_filter_row = QWidget()
        self.test_filter_row.setLayout(filter_row)
        self.test_filter_row.hide()
        self.body.addWidget(self.test_filter_row)

        self.chart = RunTrendChart()
        self.body.addWidget(self.chart)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Board", "Firmware", "Selection", "PASS", "FAIL", "SKIP", "N/A", "Overall"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda *_: self.open_selected())
        self.body.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.open_button = QPushButton(icon("eye", COLORS["secondary"], 14), "Open")
        self.open_button.clicked.connect(self.open_selected)
        actions.addWidget(self.open_button)
        self.compare_button = QPushButton("Compare")
        self.compare_button.clicked.connect(self.compare_selected)
        actions.addWidget(self.compare_button)
        self.export_button = QPushButton(icon("export", COLORS["secondary"], 14), "Export…")
        self.export_button.clicked.connect(self.export_selected)
        actions.addWidget(self.export_button)
        self.label_button = QPushButton("Label Board…")
        self.label_button.clicked.connect(self.label_selected)
        actions.addWidget(self.label_button)
        self.delete_button = QPushButton(icon("trash", COLORS["fail"], 14), "Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Secondary")
        actions.addWidget(self.count_label)
        self.body.addLayout(actions)
        self.refresh()

    # -- data ----------------------------------------------------------
    def refresh(self) -> None:
        result = self.result_filter.currentText()
        if result == "All results":
            result = ""
        mode = self.mode_filter.currentText()
        if mode == "All modes":
            mode = ""
        try:
            runs = self.store.list_runs(
                uid=self.board_filter.text().strip(),
                date_from=self.from_date.date().toString("yyyy-MM-dd"),
                date_to=self.to_date.date().toString("yyyy-MM-dd"),
                overall=result,
                fw_version=self.fw_filter.text().strip(),
                mode=mode,
                test_id=self._test_filter,
            )
        except Exception as exc:
            QMessageBox.critical(self, "History", str(exc))
            return
        self.chart.set_points(points_from_runs(runs))
        self.table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            selection = run.get("selection") or ""
            try:
                import json

                data = json.loads(selection)
                if data.get("ids"):
                    selection_text = ", ".join(data["ids"][:4]) + ("…" if len(data["ids"]) > 4 else "")
                elif data.get("groups"):
                    selection_text = "groups: " + ", ".join(data["groups"][:4])
                else:
                    selection_text = "all"
            except Exception:
                selection_text = str(selection)[:40]
            values = [
                str(run.get("started_at", "")).replace("T", " "),
                run.get("device_label") or run.get("uid", ""),
                f"{run.get('fw_name') or ''} {run.get('fw_version') or ''}".strip(),
                selection_text,
                run.get("n_pass", 0),
                run.get("n_fail", 0),
                run.get("n_skip", 0),
                run.get("n_na", 0),
                run.get("overall") or run.get("status"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, run.get("id"))
                if column == 8:
                    if value == "PASS":
                        item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(COLORS["pass"]))
                    elif value == "FAIL":
                        item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(COLORS["fail"]))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.count_label.setText(f"{len(runs)} run(s) · {self.store.database_size() / 1024:.0f} KB")
        self.test_filter_row.setVisible(bool(self._test_filter))
        if self._test_filter:
            self.test_filter_label.setText(f"Showing runs containing test {self._test_filter}")

    def focus_test(self, test_id: str) -> None:
        self._test_filter = test_id
        self.refresh()

    def clear_test_filter(self) -> None:
        self._test_filter = ""
        self.refresh()

    def selected_ids(self) -> list[int]:
        ids: list[int] = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item is not None:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value is not None:
                    ids.append(int(value))
        return ids

    # -- actions -------------------------------------------------------
    def open_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            QMessageBox.information(self, "History", "Select a run first.")
            return
        dialog = RunDetailDialog(self.store, ids[0], self)
        dialog.exec()

    def compare_selected(self) -> None:
        ids = self.selected_ids()
        if len(ids) != 2:
            QMessageBox.information(self, "Compare runs", "Select exactly two runs to compare.")
            return
        dialog = CompareDialog(self.store, ids[0], ids[1], self)
        dialog.exec()

    def export_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            QMessageBox.information(self, "Export", "Select a run first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Export run report", self.preferences.last_folder("export"))
        if not folder:
            return
        self.preferences.set_last_folder("export", folder)
        try:
            for run_id in ids:
                export_run(self.store, run_id, folder)
            QMessageBox.information(self, "Export", f"Exported {len(ids)} run(s) to {folder}")
        except Exception as exc:
            QMessageBox.critical(self, "Export", str(exc))

    def label_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            QMessageBox.information(self, "Label board", "Select a run first.")
            return
        run = self.store.get_run(ids[0])
        if run is None:
            return
        label, ok = QInputDialog.getText(self, "Label board", "Board label:", text=run.get("device_label") or "")
        if ok:
            self.store.set_device_label(str(run.get("uid")), label)
            self.refresh()

    def delete_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            QMessageBox.information(self, "Delete", "Select one or more runs first.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete runs")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Delete {len(ids)} run(s) from the history?")
        box.setInformativeText("Deletion is permanent and cannot be undone.")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.store.delete_runs(ids)
            self.refresh()
            self.runs_changed.emit()
