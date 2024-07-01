"""File, report, view, preference and help commands."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from hwval_studio.config import default_db_path
from hwval_studio.persistence.database import HistoryStore
from hwval_studio.platform_support import open_url, reveal_path
from hwval_studio.ui.dialogs.help_window import AboutDialog, HelpWindow
from hwval_studio.ui.dialogs.preferences import PreferencesDialog
from hwval_studio.ui.dialogs.serial_console import SerialConsoleDialog
from hwval_studio.ui.dialogs.simulator_dialog import SimulatorDialog
from hwval_studio.ui.theme import apply_zoom


class CommandsMixin:
    # -- file / reports -----------------------------------------------
    def _open_report(self) -> None:
        self.show_page("reports")
        self._select_sidebar_for_page("reports")
        self.reports_page.open_report()

    def _export_report(self) -> None:
        self.show_page("reports")
        if self.reports_page.current_run() is None:
            if self._last_run_id:
                self.reports_page.current_run_id = self._last_run_id
                self.reports_page._preview_selected()
            else:
                self._show_error("Select a run in History or Reports first.")
                return
        box = QMessageBox(self)
        box.setWindowTitle("Export report")
        box.setText("Choose the report format.")
        json_button = box.addButton("JSON", QMessageBox.ButtonRole.AcceptRole)
        md_button = box.addButton("Markdown", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is json_button:
            self.reports_page.export_json()
        elif box.clickedButton() is md_button:
            self.reports_page.export_markdown()

    def _export_history(self) -> None:
        self.show_page("reports")
        self.reports_page.export_history()

    def _import_results(self) -> None:
        self.show_page("reports")
        self.reports_page.import_results()

    def _page_setup(self) -> None:
        from PySide6.QtPrintSupport import QPageSetupDialog

        from hwval_studio.ui.dialogs.history_dialogs import shared_printer

        dialog = QPageSetupDialog(shared_printer(), self)
        if dialog.exec() == QPageSetupDialog.DialogCode.Accepted:
            self.show_banner("Page setup applied to the next printed report")

    def _print_report(self) -> None:
        self.show_page("reports")
        self.reports_page.print_selected()

    def _open_recent_add(self, path: str) -> None:
        if path in self._recent_reports:
            self._recent_reports.remove(path)
        self._recent_reports.insert(0, path)
        self._recent_reports = self._recent_reports[:10]
        self.preferences.set("recent/reports", json.dumps(self._recent_reports))
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        if not self._recent_reports:
            empty = self.recent_menu.addAction("No recent reports")
            empty.setEnabled(False)
            return
        for path in self._recent_reports:
            action = self.recent_menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, value=path: self._open_recent(value))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Clear Menu")
        clear.triggered.connect(self._clear_recent)

    def _open_recent(self, path: str) -> None:
        self.show_page("reports")
        self._select_sidebar_for_page("reports")
        self.reports_page.show_report_file(path)

    def _clear_recent(self) -> None:
        self._recent_reports = []
        self.preferences.set("recent/reports", "[]")
        self._update_recent_menu()

    def _new_window(self) -> None:
        from hwval_studio.ui.main_window import MainWindow

        window = MainWindow(self.preferences, HistoryStore(self.store.path, recover_running=False), auto_connect=False)
        window.show()
        self._windows.append(window)
        self._refresh_window_menu()

    def _refresh_window_menu(self) -> None:
        menu = getattr(self, "window_menu", None)
        if menu is None:
            return
        for action in list(menu.actions())[getattr(self, "_window_menu_pinned", 4):]:
            menu.removeAction(action)
        for widget in QApplication.topLevelWidgets():
            if widget.__class__.__name__ != "MainWindow":
                continue
            action = menu.addAction(widget.windowTitle() or "Window")
            action.setCheckable(True)
            action.setChecked(widget is self)
            action.triggered.connect(lambda _checked=False, w=widget: (w.show(), w.raise_(), w.activateWindow()))

    # -- tools ---------------------------------------------------------
    def _serial_console(self) -> None:
        if self._operator_mode:
            return
        if self.identity is None:
            self._show_error("Connect to a device first.")
            return
        SerialConsoleDialog(self.controller, self).exec()

    def _simulator(self) -> None:
        dialog = SimulatorDialog(self)
        dialog.connect_requested.connect(self._connect_simulator)
        dialog.exec()

    def _connect_simulator(self, port: str) -> None:
        self._manual_disconnect = False
        self._connect_port(port)

    # -- preferences ---------------------------------------------------
    def open_preferences(self) -> None:
        if self._operator_mode:
            self._show_error("Preferences are hidden in operator mode.")
            return
        dialog = PreferencesDialog(self.preferences, self)
        dialog.database_changed.connect(self._database_changed)
        dialog.exec()
        self.tests_page.set_preset(self.preferences.test_preset)
        self.operator_page.set_preset(self.preferences.operator_preset)
        self.operator_page.operator_name.clear()
        self.operator_page.operator_name.addItems(self.preferences.operator_names)
        self._update_actions()

    def _database_changed(self, path: str) -> None:
        if not path:
            path = str(default_db_path())
        try:
            if Path(path).resolve() == self.store.path.resolve():
                return
        except OSError:
            pass
        try:
            self.store.close()
        except Exception:
            pass
        try:
            self.store = HistoryStore(path)
            self.controller.store = self.store
            self.history_page.store = self.store
            self.reports_page.store = self.store
            self.status_db.setText(str(self.store.path))
            self.preferences.database_path = path
            self.history_page.refresh()
            self.reports_page.refresh()
            self.show_banner(f"History database switched to {path}")
        except Exception as exc:
            self._show_error(f"Could not open the history database: {exc}")

    # -- view ----------------------------------------------------------
    def _toggle_sidebar(self, checked: bool | None = None) -> None:
        if not hasattr(self, "sidebar"):
            return
        visible = not self.sidebar.isVisible()
        if checked is not None:
            visible = bool(checked)
        self.sidebar.setVisible(visible)
        self.sidebar_action.setChecked(visible)

    def _toggle_log(self, checked: bool | None = None) -> None:
        if not hasattr(self, "log_console"):
            return
        visible = not self.log_console.isVisible()
        if checked is not None:
            visible = bool(checked)
        self.log_console.setVisible(visible)
        self.log_action.setChecked(visible)
        self.preferences.show_log_on_start = visible

    def _toggle_terminal(self, checked: bool | None = None) -> None:
        if not hasattr(self, "terminal"):
            return
        visible = not self.terminal.isVisible()
        if checked is not None:
            visible = bool(checked)
        self.terminal.setVisible(visible)
        self.terminal_action.setChecked(visible)

    def _toggle_details(self, checked: bool) -> None:
        if hasattr(self, "tests_page"):
            self.tests_page.details_card.setVisible(checked)

    def _toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _zoom(self, delta: int) -> None:
        if delta == 0:
            self._zoom_percent = 100
        else:
            self._zoom_percent = max(70, min(200, self._zoom_percent + delta))
        apply_zoom(QApplication.instance(), self._zoom_percent)
        self.preferences.set("window/zoom", self._zoom_percent)
        self.show_banner(f"Zoom: {self._zoom_percent}%")

    def _sort_by(self, column: int) -> None:
        if self.stack.currentWidget() is not self.tests_page:
            self.show_page("all")
        self.tests_page.sort_by(column)

    def _show_only(self, name: str) -> None:
        mapping = {"All Results": "", "Failed": "FAIL", "Skipped": "SKIP", "Not Run": "NOT RUN"}
        if self.stack.currentWidget() is not self.tests_page:
            self.show_page("all")
        self.tests_page.show_only(mapping.get(name, ""))
        self.show_only_actions[name].setChecked(True)

    def _search_changed(self, text: str) -> None:
        if self.stack.currentWidget() is self.tests_page:
            self.tests_page.set_query(text)
        elif self.stack.currentWidget() is self.history_page:
            self.history_page.board_filter.setText(text)
        elif self.stack.currentWidget() is self.reports_page:
            self.reports_page.preview.find(text)

    def _focus_search(self) -> None:
        self.search.setVisible(True)
        self.search.setFocus()
        self.search.selectAll()

    def _find_next(self) -> None:
        query = self.search.text().strip()
        if not query or self.stack.currentWidget() is not self.tests_page:
            return
        table = self.tests_page.table
        start = table.currentIndex().row() + 1 if table.currentIndex().isValid() else 0
        for row in list(range(start, table.proxy.rowCount())) + list(range(0, start)):
            index = table.proxy.index(row, 4)
            if query.lower() in str(index.data() or "").lower():
                table.selectRow(row)
                table.scrollTo(index)
                return

    def _copy_test_id(self) -> None:
        row = self.tests_page.table.selected_row()
        if row:
            QApplication.clipboard().setText(str(row.get("test_id") or row.get("id")))
            self.show_banner("Test ID copied")

    def _copy_result(self) -> None:
        row = self.tests_page.table.selected_row()
        if row:
            QApplication.clipboard().setText(self.tests_page._format_result(row))
            self.show_banner("Result copied")

    def _edit(self, name: str) -> None:
        widget = QApplication.focusWidget()
        if widget is not None and hasattr(widget, name):
            getattr(widget, name)()

    def _show_test_in_history(self, test_id: str) -> None:
        self.show_page("history")
        self._select_sidebar_for_page("history")
        self.history_page.focus_test(test_id)

    def _zoom_window(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _hide_others(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if widget is not self and widget.isVisible():
                widget.hide()

    def _show_all(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if widget.__class__.__name__ == "MainWindow":
                widget.show()
                widget.raise_()

    def _bring_all_to_front(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if widget.__class__.__name__ == "MainWindow":
                widget.show()
                widget.raise_()

    # -- help ----------------------------------------------------------
    def _open_help(self, tab: str) -> None:
        HelpWindow(self, tab).exec()

    def _about(self) -> None:
        AboutDialog(self).exec()

    def _show_log_folder(self) -> None:
        from hwval_studio.config import log_dir

        reveal_path(log_dir())

    def _show_db_folder(self) -> None:
        reveal_path(self.store.path.parent)

    def _report_issue(self) -> None:
        open_url("https://github.com/soccentric-stm32/validation-gui/issues")
