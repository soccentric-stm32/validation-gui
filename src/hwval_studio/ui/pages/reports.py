"""Reports: preview, export, print and import (SRS section 13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.config import Preferences
from hwval_studio.persistence.database import HistoryStore
from hwval_studio.persistence.reports import (
    export_run_json,
    export_run_markdown,
    import_hwtest_json,
    markdown_report,
)
from hwval_studio.ui.dialogs.history_dialogs import print_report
from hwval_studio.ui.pages.base import Page
from hwval_studio.ui.theme import COLORS, icon


class ReportsPage(Page):
    exported = Signal(str)
    opened = Signal(str)

    def __init__(self, store: HistoryStore, preferences: Preferences, parent: QWidget | None = None) -> None:
        super().__init__("Reports", "Preview, export, print and import results", "reports", parent)
        self.store = store
        self.preferences = preferences
        self.current_run_id: int | None = None

        split = QHBoxLayout()
        split.setSpacing(10)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Board", "Firmware", "Overall"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._preview_selected)
        left_layout.addWidget(self.table, 1)
        left.setMaximumWidth(380)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        right_layout.addWidget(self.preview, 1)
        split.addWidget(right, 1)
        self.body.addLayout(split, 1)

        actions = QHBoxLayout()
        refresh = QPushButton(icon("refresh", COLORS["secondary"], 14), "Refresh")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        export_json = QPushButton(icon("export", COLORS["secondary"], 14), "Export JSON…")
        export_json.clicked.connect(self.export_json)
        actions.addWidget(export_json)
        export_md = QPushButton(icon("export", COLORS["secondary"], 14), "Export Markdown…")
        export_md.clicked.connect(self.export_markdown)
        actions.addWidget(export_md)
        export_history = QPushButton("Export Run History…")
        export_history.clicked.connect(self.export_history)
        actions.addWidget(export_history)
        import_button = QPushButton(icon("import", COLORS["secondary"], 14), "Import Results…")
        import_button.clicked.connect(self.import_results)
        actions.addWidget(import_button)
        open_button = QPushButton("Open Report…")
        open_button.clicked.connect(self.open_report)
        actions.addWidget(open_button)
        print_button = QPushButton(icon("print", COLORS["secondary"], 14), "Print Report…")
        print_button.clicked.connect(self.print_selected)
        actions.addWidget(print_button)
        actions.addStretch(1)
        self.body.addLayout(actions)
        self.refresh()

    # -- data ----------------------------------------------------------
    def refresh(self) -> None:
        runs = self.store.list_runs(limit=1000)
        self.table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            values = [
                str(run.get("started_at", "")).replace("T", " "),
                run.get("device_label") or run.get("uid", ""),
                f"{run.get('fw_name') or ''} {run.get('fw_version') or ''}".strip(),
                run.get("overall") or run.get("status"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, run.get("id"))
                if column == 3 and value == "PASS":
                    item.setForeground(QColor(COLORS["pass"]))
                if column == 3 and value == "FAIL":
                    item.setForeground(QColor(COLORS["fail"]))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        if runs and self.current_run_id is None:
            self.table.selectRow(0)

    def current_run(self) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        if self.current_run_id is None:
            return None
        run = self.store.get_run(self.current_run_id)
        if run is None:
            return None
        return run, self.store.get_results(self.current_run_id)

    def _preview_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return
        self.current_run_id = int(item.data(Qt.ItemDataRole.UserRole))
        data = self.current_run()
        if data is None:
            return
        run, results = data
        self.preview.setMarkdown(markdown_report(run, results))

    # -- actions -------------------------------------------------------
    def export_json(self) -> None:
        if self.current_run() is None:
            QMessageBox.information(self, "Export", "Select a run first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export report as JSON",
            str(Path(self.preferences.last_folder("export")) / "report.json"),
            "JSON (*.json)",
        )
        if path:
            export_run_json(self.store, int(self.current_run_id or 0), path)
            self.preferences.set_last_folder("export", str(Path(path).parent))
            self.exported.emit(path)
            QMessageBox.information(self, "Export", f"Saved {path}")

    def export_markdown(self) -> None:
        if self.current_run() is None:
            QMessageBox.information(self, "Export", "Select a run first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export report as Markdown",
            str(Path(self.preferences.last_folder("export")) / "report.md"),
            "Markdown (*.md)",
        )
        if path:
            export_run_markdown(self.store, int(self.current_run_id or 0), path)
            self.preferences.set_last_folder("export", str(Path(path).parent))
            self.exported.emit(path)
            QMessageBox.information(self, "Export", f"Saved {path}")

    def export_history(self) -> None:
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Export run history",
            str(Path(self.preferences.last_folder("export")) / "hwval-history"),
            "CSV (*.csv);;JSON (*.json)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".json") or "JSON" in selected:
                if not path.lower().endswith(".json"):
                    path += ".json"
                self.store.export_runs_json(path)
            else:
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                self.store.export_runs_csv(path)
            self.preferences.set_last_folder("export", str(Path(path).parent))
            QMessageBox.information(self, "Export", f"Saved {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export", str(exc))

    def import_results(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import hwtest.py results",
            self.preferences.last_folder("export"),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            run_id = import_hwtest_json(self.store, path)
            self.preferences.set_last_folder("export", str(Path(path).parent))
            self.current_run_id = run_id
            self.refresh()
            self._select_run(run_id)
            QMessageBox.information(self, "Import", f"Imported results as run {run_id}.")
        except Exception as exc:
            QMessageBox.critical(self, "Import", str(exc))

    def _select_run(self, run_id: int) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == run_id:
                self.table.selectRow(row)
                break

    def open_report(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open report",
            self.preferences.last_folder("export"),
            "Reports (*.json *.md);;All files (*)",
        )
        if path:
            self.show_report_file(path)

    def show_report_file(self, path: str | Path) -> None:
        p = Path(path)
        try:
            if p.suffix.lower() == ".json":
                raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                if "results" in raw and "meta" in raw:
                    meta = raw.get("meta") or {}
                    lines = [
                        "# Imported report",
                        "",
                        f"chip UID: `{meta.get('uid')}`  ",
                        f"firmware: {meta.get('version')} (git {meta.get('git')})  ",
                        f"date: {meta.get('date')}  ",
                        f"selector: `{meta.get('selector')}`  ",
                        "",
                        "| ID | result | ms | measured | limits | reason |",
                        "|---|---|---|---|---|---|",
                    ]
                    for result in raw.get("results") or []:
                        lines.append(
                            f"| {result.get('id')} | {result.get('result')} | {result.get('duration_ms', '')} | "
                            f"{result.get('measured', '')} | {result.get('limits', '')} | {result.get('reason', '')} |"
                        )
                    self.preview.setMarkdown("\n".join(lines))
                else:
                    self.preview.setPlainText(json.dumps(raw, indent=2))
            else:
                self.preview.setMarkdown(p.read_text(encoding="utf-8", errors="replace"))
            self.preferences.set_last_folder("export", str(p.parent))
            self.opened.emit(str(p))
        except Exception as exc:
            QMessageBox.critical(self, "Open report", str(exc))

    def print_selected(self) -> None:
        data = self.current_run()
        if data is None:
            QMessageBox.information(self, "Print", "Select a run first.")
            return
        run, results = data
        print_report(self, run, results)

    def show_markdown(self, text: str) -> None:
        self.preview.setMarkdown(text)
