"""Test table, live run controls and details pane (SRS section 8)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolButton,
    QWidget,
)

from hwval_studio.core.client import Selection, TestCase, TestGroup
from hwval_studio.protocol.codec import verdict_text
from hwval_studio.ui.pages.base import Page, SectionCard, StatRow
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import KeyValueGrid, ResultTable, ToggleSwitch

CATEGORY_ORDER = [
    "CPU & System",
    "Memory",
    "Clocks & Power",
    "GPIO & Board I/O",
    "Analog",
    "Timers",
    "Communication",
    "Connectivity",
    "Graphics & Media",
    "Other Peripherals",
    "Board",
]


def _selection_from_rows(rows: list[dict[str, Any]], *, group: str | None, levels: str, operator: bool, destructive: bool, repeat: int, until_fail: bool) -> Selection:
    ids = [str(row.get("test_id") or row.get("id")) for row in rows if row.get("test_id") or row.get("id")]
    return Selection(
        ids=ids if group is None else [],
        groups=[group] if group else [],
        all_tests=group is None and not ids,
        levels=levels,
        allow_operator=operator,
        allow_destructive=destructive,
        repeat=repeat,
        until_fail=until_fail,
    )


class TestsPage(Page):
    run_requested = Signal(object)
    counts_changed = Signal(str, object)
    selection_changed = Signal(bool)
    show_in_history = Signal(str)
    copy_context = Signal(str, str)
    clear_requested = Signal()
    levels_changed = Signal(str)
    operator_changed = Signal(bool)
    destructive_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("All Tests", "Every test of every group", "all", parent)
        self.groups: list[TestGroup] = []
        self.tests: list[TestCase] = []
        self.current_group: str | None = None
        self.read_only = False
        self.levels = "L,S,E"
        self.session_counts: dict[str, dict[str, int]] = {}
        self._details_row: dict[str, Any] | None = None
        self.missing_tests: set[str] = set()

        # Header controls -------------------------------------------------
        self.run_group_button = QPushButton(icon("play", "#FFFFFF", 14), "Run Group")
        self.run_group_button.setObjectName("Accent")
        self.run_group_button.clicked.connect(self.run_group)
        self.add_action(self.run_group_button)
        self.run_selected_button = QPushButton(icon("play", COLORS["accent"], 14), "Run Selected")
        self.run_selected_button.clicked.connect(self.run_selected)
        self.add_action(self.run_selected_button)

        # Filter bar ------------------------------------------------------
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        level_label = QLabel("Level")
        level_label.setObjectName("Secondary")
        bar_layout.addWidget(level_label)
        self.level_buttons: dict[str, QToolButton] = {}
        for level in ("S", "L", "E"):
            button = QToolButton()
            button.setText(level)
            button.setCheckable(True)
            button.setChecked(True)
            button.setToolTip({"S": "Standard", "L": "Lab / equipment", "E": "Extended"}[level])
            button.toggled.connect(self._levels_changed)
            bar_layout.addWidget(button)
            self.level_buttons[level] = button
        bar_layout.addSpacing(8)
        self.operator_toggle = ToggleSwitch("Operator tests")
        self.operator_toggle.setChecked(True)
        self.operator_toggle.setToolTip("Include tests that ask the operator to do something")
        bar_layout.addWidget(self.operator_toggle)
        self.destructive_toggle = ToggleSwitch("Destructive")
        self.destructive_toggle.setChecked(False)
        self.destructive_toggle.setToolTip("Destructive tests are off by default (TST-022)")
        self.destructive_toggle.toggled.connect(self._destructive_toggled)
        self.destructive_toggle.toggled.connect(self.destructive_changed.emit)
        self.operator_toggle.toggled.connect(self.operator_changed.emit)
        bar_layout.addWidget(self.destructive_toggle)
        bar_layout.addSpacing(8)
        repeat_label = QLabel("Repeat")
        repeat_label.setObjectName("Secondary")
        bar_layout.addWidget(repeat_label)
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 9999)
        self.repeat_spin.setValue(1)
        self.repeat_spin.setFixedWidth(66)
        bar_layout.addWidget(self.repeat_spin)
        self.until_fail = QCheckBox("Until fail")
        bar_layout.addWidget(self.until_fail)
        bar_layout.addStretch(1)
        self.details_toggle = ToggleSwitch("Details")
        self.details_toggle.setChecked(True)
        self.details_toggle.toggled.connect(self._toggle_details)
        bar_layout.addWidget(self.details_toggle)
        self.body.addWidget(bar)

        self.stats = StatRow(
            [
                ("Tests", "0"),
                ("PASS", "0"),
                ("FAIL", "0"),
                ("SKIP", "0"),
                ("N/A", "0"),
            ]
        )
        self.body.addWidget(self.stats)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = ResultTable()
        self.table.selection_changed.connect(self._show_details)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.splitter.addWidget(self.table)

        self.details_card = SectionCard("Details")
        self.details_grid = KeyValueGrid()
        self.details_card.add_widget(self.details_grid)
        self.details_extra = QLabel()
        self.details_extra.setWordWrap(True)
        self.details_extra.setObjectName("Secondary")
        self.details_card.add_widget(self.details_extra)
        self.splitter.addWidget(self.details_card)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([480, 150])
        self.body.addWidget(self.splitter, 1)

    # -- catalogue -----------------------------------------------------
    def set_catalogue(self, groups: list[TestGroup], tests: list[TestCase], *, preserve: bool = False) -> None:
        self.groups = groups
        self.tests = tests
        self._refresh_rows()

    def set_group(self, code: str | None) -> None:
        self.current_group = code
        if code:
            group = next((g for g in self.groups if g.code == code), None)
            name = group.name if group else code
            self.set_title(f"{name}", f"Group {code} · {group.test_count if group else 0} tests")
        else:
            self.set_title("All Tests", f"{len(self.tests)} tests in {len(self.groups)} groups")
        self._refresh_rows()

    def _filtered_tests(self) -> list[TestCase]:
        if self.current_group:
            return [test for test in self.tests if test.group == self.current_group]
        return list(self.tests)

    def _refresh_rows(self) -> None:
        rows = [
            {
                "test_id": test.id,
                "id": test.id,
                "group": test.group,
                "title": test.title,
                "level": test.level_name,
                "operator": test.operator,
                "destructive": test.destructive,
                "reqs": test.reqs,
                "reason": "",
                "result": "NOT RUN",
                "duration_ms": None,
                "iteration": 1,
                "missing": test.id in self.missing_tests,
            }
            for test in self._filtered_tests()
        ]
        self.table.set_catalogue({test.id: {"title": test.title, "level": test.level_name, "reqs": test.reqs, "operator": test.operator, "destructive": test.destructive, "needs": test.needs} for test in self.tests})
        self.table.set_rows(rows)
        self.table.setColumnHidden(3, self.current_group is not None)
        self._update_counts()
        if self.read_only:
            self.details_grid.set_items({})
            self.details_extra.setText("")

    def set_missing_tests(self, missing: set[str]) -> None:
        self.missing_tests = set(missing)
        for row in self.table.source_model.rows:
            row["missing"] = str(row.get("test_id") or row.get("id")) in self.missing_tests
        if self.table.source_model.rows:
            self.table.source_model.dataChanged.emit(
                self.table.source_model.index(0, 0),
                self.table.source_model.index(len(self.table.source_model.rows) - 1, len(self.table.source_model.COLUMNS) - 1),
            )

    def set_results(self, results: list[dict[str, Any]]) -> None:
        for result in results:
            self.table.update_result(result)
        self._update_counts()

    # -- live run ------------------------------------------------------
    def reset_for_run(self) -> None:
        self._refresh_rows()

    def on_test_started(self, data: dict[str, Any]) -> None:
        self.table.source_model.mark_running(str(data.get("id", "")))
        row = self.table.selected_row()
        if row is not None:
            self._show_details(row)

    def on_test_result(self, result: dict[str, Any]) -> None:
        self.table.update_result(result)
        self._update_counts()
        if self._details_row and str(self._details_row.get("test_id")) == str(result.get("id")):
            self._show_details(result)

    def aborting(self) -> None:
        self.set_title(self.title_label.text(), "Aborting… waiting for the device to finish")

    def run_finished(self, payload: dict[str, Any]) -> None:
        self.table.source_model.mark_unfinished_not_run()
        self._update_counts()
        counts = payload.get("counts", {})
        self.set_title(
            self.title_label.text(),
            f"{counts.get('pass', 0)} PASS · {counts.get('fail', 0)} FAIL · "
            f"{counts.get('skip', 0)} SKIP · {counts.get('na', 0)} N/A",
        )

    # -- counts / badges ----------------------------------------------
    def _update_counts(self) -> None:
        counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "N/A": 0, "RUNNING": 0, "NOT RUN": 0}
        group_counts: dict[str, dict[str, int]] = {}
        total = 0
        for row in self.table.source_model.rows:
            total += 1
            value = verdict_text(row)
            counts[value] = counts.get(value, 0) + 1
            group = str(row.get("group") or "")
            if group:
                bucket = group_counts.setdefault(group, {"PASS": 0, "FAIL": 0, "SKIP": 0, "N/A": 0, "RUNNING": 0, "NOT RUN": 0})
                bucket[value] = bucket.get(value, 0) + 1
        self.session_counts = group_counts
        self.stats.set_value("Tests", str(total))
        self.stats.set_value("PASS", str(counts.get("PASS", 0)), COLORS["pass"])
        self.stats.set_value("FAIL", str(counts.get("FAIL", 0)), COLORS["fail"])
        self.stats.set_value("SKIP", str(counts.get("SKIP", 0)), COLORS["skip"])
        self.stats.set_value("N/A", str(counts.get("N/A", 0)), COLORS["na"])
        if self.current_group:
            bucket = group_counts.get(self.current_group, {})
            self.counts_changed.emit(self.current_group, bucket)
        else:
            for group, bucket in group_counts.items():
                self.counts_changed.emit(group, bucket)

    def group_badge(self, code: str) -> dict[str, int]:
        return self.session_counts.get(code, {})

    # -- selection / details -------------------------------------------
    def _show_details(self, row: dict[str, Any] | None) -> None:
        if row is None:
            return
        self._details_row = row
        test = next(
            (test for test in self.tests if test.id == str(row.get("test_id") or row.get("id"))),
            None,
        )
        measured = row.get("measured") or {}
        limits = row.get("limits") or {}
        if isinstance(measured, dict):
            measured_text = measured.get("text") or (f"{measured.get('value')} {measured.get('unit', '')}".strip() if measured.get("value") is not None else "—")
        else:
            measured_text = str(measured or "—")
        if isinstance(limits, dict):
            limits_text = limits.get("text") or "—"
        else:
            limits_text = str(limits or "—")
        self.details_grid.set_items(
            {
                "Test": f"{row.get('test_id') or row.get('id', '')} — {row.get('title', '')}",
                "Result": verdict_text(row),
                "Level": row.get("level") or (test.level_name if test else ""),
                "Flags": ", ".join(
                    flag
                    for flag, value in (
                        ("operator", row.get("operator", test.operator if test else False)),
                        ("destructive", row.get("destructive", test.destructive if test else False)),
                    )
                    if value
                )
                or "—",
                "Needs": (test.needs if test else "") or "—",
                "Measured": measured_text,
                "Limits": limits_text,
                "Reason": row.get("reason") or "—",
                "Duration": f"{row.get('duration_ms')} ms" if row.get("duration_ms") is not None else "—",
                "Timeout": f"{test.timeout_ms} ms" if test and test.timeout_ms else "—",
                "Requirements": row.get("reqs") or (test.reqs if test else "") or "—",
            }
        )
        if test:
            self.details_extra.setText(test.title)
        self.selection_changed.emit(True)

    def set_read_only(self, read_only: bool) -> None:
        self.read_only = read_only
        self.run_group_button.setVisible(not read_only)
        self.run_selected_button.setVisible(not read_only)
        self.operator_toggle.setVisible(not read_only)
        self.destructive_toggle.setVisible(not read_only)
        self.repeat_spin.setVisible(not read_only)
        self.until_fail.setVisible(not read_only)
        for button in self.level_buttons.values():
            button.setVisible(not read_only)
        self.details_toggle.setVisible(not read_only)

    # -- actions -------------------------------------------------------
    def _levels(self) -> str:
        selected = [level for level, button in self.level_buttons.items() if button.isChecked()]
        return ",".join(selected) if selected else "S,L,E"

    def _levels_changed(self) -> None:
        if not any(button.isChecked() for button in self.level_buttons.values()):
            self.level_buttons["S"].setChecked(True)
        self.levels_changed.emit(self._levels())

    def _destructive_toggled(self, enabled: bool) -> None:
        if not enabled:
            return
        destructive = [test for test in self.tests if test.destructive]
        names = "\n".join(f"• {test.id} — {test.title}" for test in destructive) or "• (the connected catalogue reports no destructive tests)"
        box = QMessageBox(self)
        box.setWindowTitle("Allow destructive tests?")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Destructive tests can erase flash, change option bytes, reset the MCU and overwrite RTC/backup data.")
        box.setInformativeText("The following tests will be allowed for the next run:\n\n" + names)
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            self.destructive_toggle.blockSignals(True)
            self.destructive_toggle.setChecked(False)
            self.destructive_toggle.blockSignals(False)

    def _selection_for_group(self) -> Selection:
        return Selection(
            groups=[self.current_group] if self.current_group else [],
            all_tests=self.current_group is None,
            levels=self._levels(),
            allow_operator=self.operator_toggle.isChecked(),
            allow_destructive=self.destructive_toggle.isChecked(),
            repeat=self.repeat_spin.value(),
            until_fail=self.until_fail.isChecked(),
        )

    def run_group(self) -> None:
        if self.read_only:
            return
        self.run_requested.emit(self._selection_for_group())

    def run_all(self) -> None:
        if self.read_only:
            return
        selection = self._selection_for_group()
        if self.current_group is not None:
            selection = Selection(
                all_tests=True,
                levels=selection.levels,
                allow_operator=selection.allow_operator,
                allow_destructive=selection.allow_destructive,
                repeat=selection.repeat,
                until_fail=selection.until_fail,
            )
        self.run_requested.emit(selection)

    def run_selected(self) -> None:
        if self.read_only:
            return
        rows = self.table.selected_rows()
        if not rows:
            QMessageBox.information(self, "Run Selected", "Select one or more tests first.")
            return
        selection = Selection(
            ids=[str(row.get("test_id") or row.get("id")) for row in rows],
            groups=[],
            all_tests=False,
            levels=self._levels(),
            allow_operator=self.operator_toggle.isChecked(),
            allow_destructive=self.destructive_toggle.isChecked(),
            repeat=self.repeat_spin.value(),
            until_fail=self.until_fail.isChecked(),
        )
        self.run_requested.emit(selection)

    def run_failed_again(self, results: list[dict[str, Any]]) -> None:
        failed = [str(result.get("test_id") or result.get("id")) for result in results if verdict_text(result) == "FAIL"]
        if not failed:
            QMessageBox.information(self, "Run Failed Again", "There are no failed tests in the last run.")
            return
        self.run_requested.emit(
            Selection(
                ids=failed,
                all_tests=False,
                levels="S,L,E",
                allow_operator=self.operator_toggle.isChecked(),
                allow_destructive=False,
            )
        )

    def repeat_dialog(self) -> None:
        value, ok = QInputDialog.getInt(self, "Repeat Run", "Repeat the selection:", self.repeat_spin.value(), 1, 9999)
        if ok:
            self.repeat_spin.setValue(value)
            self.run_selected()

    def clear(self) -> None:
        self.clear_requested.emit()

    def _toggle_details(self, visible: bool) -> None:
        self.details_card.setVisible(visible)

    def _context_menu(self, position: Any) -> None:
        row = self.table.selected_row()
        if row is None:
            return
        menu = QMenu(self)
        run = menu.addAction(icon("play", COLORS["text"], 14), "Run")
        run.triggered.connect(self.run_selected)
        repeat = menu.addAction("Run Repeatedly…")
        repeat.triggered.connect(self.repeat_dialog)
        menu.addSeparator()
        copy_id = menu.addAction("Copy Test ID")
        copy_id.triggered.connect(lambda: QApplication.clipboard().setText(str(row.get("test_id") or row.get("id"))))
        copy_result = menu.addAction("Copy Result")
        copy_result.triggered.connect(lambda: QApplication.clipboard().setText(self._format_result(row)))
        menu.addSeparator()
        history = menu.addAction(icon("history", COLORS["text"], 14), "Show in History")
        history.triggered.connect(lambda: self.show_in_history.emit(str(row.get("test_id") or row.get("id"))))
        menu.exec(self.table.viewport().mapToGlobal(position))

    @staticmethod
    def _format_result(row: dict[str, Any]) -> str:
        measured = row.get("measured") or {}
        limits = row.get("limits") or {}
        measured_text = measured.get("text", "") if isinstance(measured, dict) else str(measured)
        limits_text = limits.get("text", "") if isinstance(limits, dict) else str(limits)
        return (
            f"{row.get('test_id') or row.get('id')} {verdict_text(row)} "
            f"({row.get('duration_ms')} ms) measured={measured_text} limits={limits_text} "
            f"reason={row.get('reason', '')}"
        )

    def set_query(self, query: str) -> None:
        self.table.set_query(query)

    def show_only(self, result: str) -> None:
        self.table.proxy.set_result_filter(result)

    def sort_by(self, column: int, descending: bool = False) -> None:
        self.table.sortByColumn(column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)

    def set_preset(self, preset: Any) -> None:
        levels = set(str(preset.levels).replace(" ", "").split(","))
        for level, button in self.level_buttons.items():
            button.blockSignals(True)
            button.setChecked(level in levels)
            button.blockSignals(False)
        self.operator_toggle.setChecked(bool(preset.allow_operator))
        self.repeat_spin.setValue(max(1, int(preset.repeat)))
        self.until_fail.setChecked(bool(preset.until_fail))

    def preset(self) -> Selection:
        return self._selection_for_group()
