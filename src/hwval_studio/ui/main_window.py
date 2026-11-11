"""HWVAL Studio main window."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hwval_studio import APP_NAME, __version__
from hwval_studio.config import Preferences, default_db_path
from hwval_studio.controller import StudioController
from hwval_studio.core.client import Identity, Selection
from hwval_studio.persistence.database import HistoryStore
from hwval_studio.platform_support import is_macos, set_progress
from hwval_studio.transport.port_lock import release_port
from hwval_studio.ui.dialogs.operator_prompt import OperatorPromptDialog
from hwval_studio.ui.log_console import LogConsole
from hwval_studio.ui.main_actions import ActionsMixin
from hwval_studio.ui.main_commands import CommandsMixin
from hwval_studio.ui.main_handlers import HandlersMixin
from hwval_studio.ui.main_navigation import NavigationMixin
from hwval_studio.ui.pages.demo import DemoPage
from hwval_studio.ui.pages.flash import FlashPage
from hwval_studio.ui.pages.history import HistoryPage
from hwval_studio.ui.pages.operator import OperatorView
from hwval_studio.ui.pages.overview import OverviewPage
from hwval_studio.ui.pages.reports import ReportsPage
from hwval_studio.ui.pages.tests import TestsPage
from hwval_studio.ui.pages.update import UpdatePage
from hwval_studio.ui.soc_terminal import TerminalPanel
from hwval_studio.ui.theme import COLORS, apply_zoom, icon


class MainWindow(ActionsMixin, NavigationMixin, HandlersMixin, CommandsMixin, QMainWindow):
    def __init__(
        self,
        preferences: Preferences | None = None,
        store: HistoryStore | None = None,
        *,
        operator_mode: bool = False,
        auto_connect: bool = True,
    ) -> None:
        super().__init__()
        self.logger = logging.getLogger("hwval_studio")
        self.preferences = preferences or Preferences()
        if store is None:
            store = HistoryStore(self.preferences.database_path or default_db_path())
        self.store = store
        self.controller = StudioController(self.preferences, self.store, self)
        self.identity: Identity | None = None
        self.role = 0
        self._run_active = False
        self._update_active = False
        self._busy = False
        self._manual_disconnect = False
        self._operator_mode = False
        self._prompt_dialog: OperatorPromptDialog | None = None
        self._last_run_id = 0
        self._last_results: list[dict[str, Any]] = []
        self._last_selection: Selection | None = None
        self._zoom_percent = int(self.preferences.get_int("window/zoom", 100))
        self._reconnect_pending = False
        self._sidebar_width = 248
        self._recent_reports: list[str] = self._load_recent()
        self._windows: list[MainWindow] = []
        self._sidebar_items: dict[str, QTreeWidgetItem] = {}
        self._port_lock = None
        self._locked_port: str | None = None

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(icon("chip", COLORS["accent"], 64))
        self.setMinimumSize(1024, 680)
        self.setAcceptDrops(True)
        if is_macos():
            self.setUnifiedTitleAndToolBarOnMac(True)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_central()
        self._connect_signals()
        self._restore_window_state()
        self._update_actions()
        self._update_recent_menu()
        self._refresh_window_menu()
        self._start_timers()
        self._refresh_ports()
        if self._zoom_percent != 100:
            apply_zoom(QApplication.instance(), self._zoom_percent)
        if operator_mode or self.preferences.start_in_operator_mode:
            self.enter_operator_mode()
        if auto_connect and self.preferences.auto_connect:
            QTimer.singleShot(350, self._auto_connect)

    # -- construction helpers -----------------------------------------
    def _action(
        self,
        text: str,
        slot: Any,
        *,
        shortcut: str | QKeySequence | None = None,
        icon_name: str | None = None,
        checkable: bool = False,
        enabled: bool = True,
        role: QAction.MenuRole | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if icon_name:
            action.setIcon(icon(icon_name, COLORS["text"], 16))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        action.setEnabled(enabled)
        if slot is not None:
            if checkable:
                action.toggled.connect(slot)
            else:
                action.triggered.connect(slot)
        if role is not None:
            action.setMenuRole(role)
        self.addAction(action)
        return action

    def _load_recent(self) -> list[str]:
        import json

        raw = str(self.preferences.get("recent/reports", "[]") or "[]")
        try:
            values = json.loads(raw)
            return [str(v) for v in values] if isinstance(values, list) else []
        except (TypeError, ValueError):
            return []

    # -- central widget ------------------------------------------------
    def _build_central(self) -> None:
        self.banner = QLabel()
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        self.banner_timer = QTimer(self)
        self.banner_timer.setSingleShot(True)
        self.banner_timer.timeout.connect(self.banner.hide)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(0)
        self.sidebar_tree = QTreeWidget()
        self.sidebar_tree.setHeaderHidden(True)
        self.sidebar_tree.setIndentation(12)
        self.sidebar_tree.setAnimated(True)
        self.sidebar_tree.setExpandsOnDoubleClick(True)
        self.sidebar_tree.setRootIsDecorated(True)
        self.sidebar_tree.setObjectName("SourceList")
        self.sidebar_tree.setAccessibleName("Sidebar")
        self.sidebar_tree.itemClicked.connect(self._sidebar_clicked)
        sidebar_layout.addWidget(self.sidebar_tree, 1)

        self.stack = QStackedWidget()
        self.stack.setAccessibleName("Main content")
        self.overview_page = OverviewPage()
        self.tests_page = TestsPage()
        self.update_page = UpdatePage(self.preferences)
        self.flash_page = FlashPage(self.preferences)
        self.demo_page = DemoPage()
        self.history_page = HistoryPage(self.store, self.preferences)
        self.reports_page = ReportsPage(self.store, self.preferences)
        self.operator_page = OperatorView(self.preferences.operator_preset, self.preferences.operator_names)
        self.pages = {
            "overview": self.overview_page,
            "tests": self.tests_page,
            "update": self.update_page,
            "flash": self.flash_page,
            "demo": self.demo_page,
            "history": self.history_page,
            "reports": self.reports_page,
            "operator": self.operator_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.addWidget(self.sidebar)
        self.content_splitter.addWidget(self.stack)
        # Debug UART terminal on the right, as in the BOOT flasher.
        self.terminal = TerminalPanel(title="Debug UART")
        self.terminal.closed.connect(lambda: self._toggle_terminal(False))
        self.content_splitter.addWidget(self.terminal)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setCollapsible(1, False)
        self.content_splitter.setSizes([self._sidebar_width, 800, 360])

        self.log_console = LogConsole()
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.addWidget(self.content_splitter)
        self.main_splitter.addWidget(self.log_console)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setSizes([720, 110])

        root = QWidget()
        root.setObjectName("Root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        banner_wrap = QWidget()
        banner_layout = QHBoxLayout(banner_wrap)
        banner_layout.setContentsMargins(14, 7, 14, 0)
        banner_layout.addWidget(self.banner)
        root_layout.addWidget(banner_wrap)
        root_layout.addWidget(self.main_splitter, 1)
        self.setCentralWidget(root)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_connection = QLabel("Not connected")
        self.status_role = QLabel("")
        self.status_port = QLabel("")
        self.status_db = QLabel(str(self.store.path))
        status.addWidget(self.status_connection, 1)
        status.addPermanentWidget(self.status_role)
        status.addPermanentWidget(self.status_port)
        status.addPermanentWidget(self.status_db)
        self.log_console.setVisible(self.preferences.show_log_on_start)
        self.terminal.refresh_ports()
        self._rebuild_sidebar()
        self._wire_pages()

    def _wire_pages(self) -> None:
        self.overview_page.refresh_requested.connect(self._refresh_overview)
        self.overview_page.harness_requested.connect(self._harness_check)
        self.overview_page.reset_requested.connect(self._reset_device)
        self.overview_page.bootloader_requested.connect(self._enter_bootloader)
        self.overview_page.provision_requested.connect(self._provision)
        self.overview_page.activate_requested.connect(self.controller.activate_pending)
        self.overview_page.diagnostics_requested.connect(self._show_device_info)
        self.tests_page.run_requested.connect(self._run_selection)
        self.tests_page.counts_changed.connect(self._group_counts_changed)
        self.tests_page.show_in_history.connect(self._show_test_in_history)
        self.tests_page.clear_requested.connect(self._clear_results)
        self.tests_page.levels_changed.connect(self._sync_level_actions)
        self.tests_page.operator_changed.connect(self._sync_operator_action)
        self.tests_page.destructive_changed.connect(self._sync_destructive_action)
        self.update_page.update_requested.connect(self._start_update)
        self.update_page.cancel_requested.connect(self.controller.cancel_update)
        self.update_page.bootloader_requested.connect(self._enter_bootloader)
        self.update_page.provision_requested.connect(self._provision)
        self.update_page.refresh_requested.connect(self.controller.refresh_boot_info)
        self.update_page.activate_requested.connect(self.controller.activate_pending)
        self.flash_page.info_requested.connect(self._swd_info)
        self.flash_page.openocd_check_requested.connect(self._check_openocd)
        self.flash_page.flash_requested.connect(self.controller.flash_hwval)
        self.flash_page.provision_requested.connect(self.controller.provision_product)
        self.flash_page.restore_requested.connect(self._restore_requested)
        self.flash_page.options_requested.connect(self._read_options)
        self.demo_page.refresh_requested.connect(self.controller.refresh_demo_status)
        self.demo_page.led_requested.connect(self.controller.set_led)
        self.demo_page.led_all_requested.connect(self.controller.set_led_all)
        self.demo_page.clear_fault_requested.connect(self.controller.clear_fault)
        self.demo_page.reset_requested.connect(self._reset_device)
        self.demo_page.bootloader_requested.connect(self._enter_bootloader)
        self.operator_page.run_requested.connect(self._operator_run)
        self.operator_page.abort_requested.connect(self._abort)
        self.operator_page.exit_requested.connect(lambda: self._toggle_operator_mode(False))
        self.reports_page.exported.connect(self._open_recent_add)
        self.reports_page.opened.connect(self._open_recent_add)

    def _connect_signals(self) -> None:
        c = self.controller
        c.ports_changed.connect(self._ports_changed)
        c.connection_state.connect(self._connection_state)
        c.connected.connect(self._connected)
        c.disconnected.connect(self._disconnected)
        c.log.connect(self._log_message)
        c.device_info_ready.connect(self._device_info_ready)
        c.catalogue_ready.connect(self._catalogue_ready)
        c.harness_ready.connect(self._harness_ready)
        c.boot_info_ready.connect(self._boot_info_ready)
        c.demo_status_ready.connect(self._demo_status_ready)
        c.status_failed.connect(self._show_error)
        c.run_active_changed.connect(self._run_active_changed)
        c.run_started.connect(self._run_started)
        c.test_started.connect(self._test_started)
        c.test_result.connect(self._test_result)
        c.run_prompt.connect(self._run_prompt)
        c.run_prompt_done.connect(self._run_prompt_done)
        c.run_finished.connect(self._run_finished)
        c.run_failed.connect(self._run_failed)
        c.update_state.connect(self.update_page.set_state)
        c.update_progress.connect(self._update_progress)
        c.update_finished.connect(self._update_finished)
        c.update_failed.connect(self._update_failed)
        c.swd_output.connect(self._swd_output)
        c.swd_finished.connect(self._swd_finished)
        c.swd_failed.connect(self._swd_failed)
        c.button_event.connect(self._button_event)
        c.ping_failed.connect(self._ping_failed)
        c.banner.connect(lambda text: self.show_banner(text))
        c.error.connect(self._show_error)
        c.operation_busy.connect(self._operation_busy)
        c.hlink_frame.connect(lambda data: self.log_console.log_frame("RX", data))
        c.connection_state.connect(
            lambda state: set_progress(self, 0, 0) if state in {"disconnected", "connected"} else None
        )

    # -- geometry ------------------------------------------------------
    def _restore_window_state(self) -> None:
        geometry, state, width, splitter = self.preferences.restore_window_state()
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1280, 820)
        if state:
            self.restoreState(state)
        self._sidebar_width = max(200, min(360, width))
        self.content_splitter.setSizes([self._sidebar_width, 900, 360])
        if splitter:
            self.main_splitter.restoreState(splitter)
        self.sidebar.setMinimumWidth(200)
        self.sidebar.setMaximumWidth(360)
        sidebar_visible = self.preferences.get_bool("window/sidebar_visible", True)
        self.sidebar.setVisible(sidebar_visible)
        self.sidebar_action.setChecked(sidebar_visible)
        last = self.preferences.last_selected_item
        QTimer.singleShot(0, lambda: self._select_key(last or "overview"))

    def _save_window_state(self) -> None:
        self.preferences.save_window_state(
            self.saveGeometry(),
            self.saveState(),
            self.content_splitter.sizes()[0] if self.content_splitter.sizes() else self._sidebar_width,
            self.main_splitter.saveState(),
        )
        self.preferences.test_preset = self.tests_page.preset()
        self.preferences.set("window/sidebar_visible", self.sidebar.isVisible())
        self.preferences.last_selected_item = self._current_key() or self.preferences.last_selected_item

    def closeEvent(self, event: Any) -> None:
        if self._run_active and self.preferences.confirm_quit_during_run:
            box = QMessageBox(self)
            box.setWindowTitle("Quit while running?")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("A test run is active.")
            box.setInformativeText("Abort the run and quit HWVAL Studio?")
            box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if box.exec() != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self._update_active and self.preferences.confirm_quit_during_run:
            box = QMessageBox(self)
            box.setWindowTitle("Quit during update?")
            box.setText("A firmware update is active.")
            box.setInformativeText("Cancel the update and quit? The active slot is left unchanged.")
            box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
            if box.exec() != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._save_window_state()
        try:
            self.controller.disconnect_device()
        except Exception:
            pass
        # M20: do not destroy the controller/store while a worker is running.
        try:
            self.controller.wait_for_tasks()
        except Exception:
            pass
        try:
            self.store.close()
        except Exception:
            pass
        release_port(self._port_lock)
        self._port_lock = None
        self._locked_port = None
        self.logger.info("window closed")
        event.accept()
