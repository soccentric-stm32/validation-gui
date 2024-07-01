"""Run details, comparison and print dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtGui import QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.persistence.database import HistoryStore
from hwval_studio.persistence.reports import (
    export_run_json,
    export_run_markdown,
    markdown_report,
)
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import KeyValueGrid, ResultTable


class RunDetailDialog(QDialog):
    def __init__(self, store: HistoryStore, run_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.run_id = run_id
        self.setWindowTitle(f"Run {run_id}")
        self.resize(1100, 720)
        run = store.get_run(run_id)
        if run is None:
            raise ValueError(f"run {run_id} not found")
        results = store.get_results(run_id)
        layout = QVBoxLayout(self)
        header = QLabel(f"Run {run_id} · {run.get('started_at')} · {run.get('overall') or run.get('status')}")
        header.setObjectName("PageTitle")
        layout.addWidget(header)
        grid = KeyValueGrid()
        grid.set_items(
            {
                "Board UID": run.get("uid"),
                "Device label": run.get("device_label") or "—",
                "DEV_ID / REV_ID": f"0x{int(run.get('dev_id') or 0):03X} / 0x{int(run.get('rev_id') or 0):04X}",
                "Firmware": f"{run.get('fw_name') or ''} {run.get('fw_version') or ''} ({run.get('fw_commit') or ''})",
                "GUI": run.get("gui_version"),
                "Mode": run.get("mode"),
                "Operator": run.get("operator_name") or "—",
                "Started": run.get("started_at"),
                "Finished": run.get("finished_at") or "—",
                "Status": run.get("status"),
                "Totals": f"{run.get('n_pass', 0)} PASS · {run.get('n_fail', 0)} FAIL · {run.get('n_skip', 0)} SKIP · {run.get('n_na', 0)} N/A",
                "Selection": run.get("selection"),
            }
        )
        layout.addWidget(grid)
        table = ResultTable()
        table.set_rows([self._to_row(result) for result in results])
        table.set_catalogue(store.load_catalogue(str(run.get("fw_version") or "")))
        layout.addWidget(table, 1)
        buttons = QHBoxLayout()
        open_json = QPushButton(icon("export", COLORS["secondary"], 14), "Export JSON…")
        open_json.clicked.connect(self.export_json)
        buttons.addWidget(open_json)
        open_md = QPushButton(icon("export", COLORS["secondary"], 14), "Export Markdown…")
        open_md.clicked.connect(self.export_markdown)
        buttons.addWidget(open_md)
        print_button = QPushButton(icon("print", COLORS["secondary"], 14), "Print Report…")
        print_button.clicked.connect(lambda: print_report(self, run, results))
        buttons.addWidget(print_button)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    @staticmethod
    def _to_row(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "test_id": result.get("test_id"),
            "id": result.get("test_id"),
            "group": result.get("group_code"),
            "result": result.get("result"),
            "duration_ms": result.get("duration_ms"),
            "reason": result.get("reason"),
            "reqs": result.get("reqs"),
            "measured": {
                "text": result.get("measured_text") or "",
                "value": result.get("measured_value"),
                "unit": result.get("measured_unit") or "",
            },
            "limits": {
                "text": result.get("limits_text") or "",
                "min": result.get("limit_min"),
                "max": result.get("limit_max"),
                "unit": result.get("limit_unit") or "",
            },
            "iteration": result.get("iteration", 1),
        }

    def _default_folder(self) -> str:
        return str(Path.home())

    def export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export run as JSON", self._default_folder(), "JSON (*.json)")
        if path:
            export_run_json(self.store, self.run_id, path)
            QMessageBox.information(self, "Export", f"Saved {path}")

    def export_markdown(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export run as Markdown", self._default_folder(), "Markdown (*.md)")
        if path:
            export_run_markdown(self.store, self.run_id, path)
            QMessageBox.information(self, "Export", f"Saved {path}")


class CompareDialog(QDialog):
    def __init__(
        self,
        store: HistoryStore,
        left_run: int,
        right_run: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Compare run {left_run} and run {right_run}")
        self.resize(980, 680)
        from hwval_studio.persistence.reports import compare_runs

        rows = compare_runs(store, left_run, right_run)
        layout = QVBoxLayout(self)
        header = QLabel(f"Run {left_run} ↔ run {right_run} · {sum(row['changed'] for row in rows)} changed result(s)")
        header.setObjectName("PageTitle")
        layout.addWidget(header)
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(["Test", "Left run", "Right run", "Changed"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        for index, row in enumerate(rows):
            values = [row["test_id"], row["left"], row["right"], "yes" if row["changed"] else ""]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if row["changed"]:
                    item.setBackground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(COLORS["skip_soft"]))
                    item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(COLORS["text"]))
                table.setItem(index, column, item)
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


_SHARED_PRINTER: QPrinter | None = None


def shared_printer() -> QPrinter:
    """One printer object so Page Setup applies to the next print."""
    global _SHARED_PRINTER
    if _SHARED_PRINTER is None:
        _SHARED_PRINTER = QPrinter(QPrinter.PrinterMode.HighResolution)
        _SHARED_PRINTER.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    return _SHARED_PRINTER


def print_report(parent: QWidget, run: dict[str, Any], results: list[dict[str, Any]]) -> None:
    printer = shared_printer()
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle("Print report")
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return
    document = QTextDocument()
    document.setMarkdown(markdown_report(run, results))
    document.setPageSize(printer.pageRect(QPrinter.Unit.DevicePixel).size())
    document.print_(printer)
