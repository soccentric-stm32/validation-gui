"""Main window actions, menus and toolbar (SRS section 6)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QWidget,
)

from hwval_studio import APP_NAME
from hwval_studio.platform_support import is_macos
from hwval_studio.protocol.generated.hwlink.Role import Role
from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import ActivityView, SearchBox


class ActionsMixin:
    # -- actions -------------------------------------------------------
    def _build_actions(self) -> None:
        # File
        self.new_window_action = self._action("New Window", self._new_window, shortcut="Ctrl+N", icon_name="chip", enabled=is_macos())
        self.open_report_action = self._action("Open Report…", self._open_report)
        self.export_report_action = self._action("Export Report…", self._export_report, shortcut="Ctrl+Shift+E", icon_name="export")
        self.export_history_action = self._action("Export Run History…", self._export_history, icon_name="database")
        self.import_results_action = self._action("Import Results…", self._import_results, icon_name="import")
        self.page_setup_action = self._action("Page Setup…", self._page_setup)
        self.print_report_action = self._action("Print Report…", self._print_report, shortcut="Ctrl+P", icon_name="print")
        self.close_action = self._action("Close Window", self.close, shortcut="Ctrl+W")
        self.quit_action = self._action("Quit", QApplication.quit, shortcut="Ctrl+Q", role=QAction.MenuRole.QuitRole)
        self.hide_action = self._action("Hide HWVAL Studio", self.hide, shortcut="Ctrl+H")
        self.hide_others_action = self._action("Hide Others", self._hide_others, shortcut="Ctrl+Alt+H")
        self.show_all_action = self._action("Show All", self._show_all)

        # Edit
        self.undo_action = self._action("Undo", lambda: self._edit("undo"), shortcut=QKeySequence.StandardKey.Undo)
        self.redo_action = self._action("Redo", lambda: self._edit("redo"), shortcut=QKeySequence.StandardKey.Redo)
        self.cut_action = self._action("Cut", lambda: self._edit("cut"), shortcut=QKeySequence.StandardKey.Cut)
        self.copy_action = self._action("Copy", lambda: self._edit("copy"), shortcut=QKeySequence.StandardKey.Copy)
        self.paste_action = self._action("Paste", lambda: self._edit("paste"), shortcut=QKeySequence.StandardKey.Paste)
        self.select_all_action = self._action("Select All", lambda: self._edit("selectAll"), shortcut=QKeySequence.StandardKey.SelectAll)
        self.copy_test_id_action = self._action("Copy Test ID", self._copy_test_id)
        self.copy_result_action = self._action("Copy Result as Text", self._copy_result)
        self.find_action = self._action("Find…", self._focus_search, shortcut="Ctrl+F", icon_name="search")
        self.find_next_action = self._action("Find Next", self._find_next, shortcut="Ctrl+G")
        self.preferences_action = self._action(
            "Preferences…", self.open_preferences, shortcut="Ctrl+,", icon_name="settings", role=QAction.MenuRole.PreferencesRole
        )

        # View
        self.sidebar_action = self._action("Show Sidebar", self._toggle_sidebar, shortcut="Ctrl+Alt+S", icon_name="sidebar", checkable=True)
        self.sidebar_action.setChecked(True)
        self.log_action = self._action("Show Log", self._toggle_log, shortcut="Ctrl+Shift+L", icon_name="console", checkable=True)
        self.log_action.setChecked(bool(self.preferences.show_log_on_start))
        self.terminal_action = self._action("Debug Terminal", self._toggle_terminal, shortcut="Ctrl+J", icon_name="console", checkable=True)
        self.terminal_action.setChecked(True)
        self.details_action = self._action("Show Details Pane", self._toggle_details, checkable=True)
        self.details_action.setChecked(True)
        self.operator_action = self._action(
            "Operator Mode", self._toggle_operator_mode, shortcut="Ctrl+Shift+O", icon_name="user", checkable=True
        )
        self.sort_actions: dict[str, QAction] = {}
        for name, column in (("Test ID", 2), ("Group", 3), ("Title", 4), ("Level", 5), ("Duration", 7), ("Result", 1)):
            action = QAction(name, self)
            action.triggered.connect(lambda _checked=False, value=column: self._sort_by(value))
            self.addAction(action)
            self.sort_actions[name] = action
        self.show_only_group = QActionGroup(self)
        self.show_only_group.setExclusive(True)
        self.show_only_actions: dict[str, QAction] = {}
        for name in ("All Results", "Failed", "Skipped", "Not Run"):
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(name == "All Results")
            action.triggered.connect(lambda _checked=False, value=name: self._show_only(value))
            self.show_only_group.addAction(action)
            self.addAction(action)
            self.show_only_actions[name] = action
        self.zoom_in_action = self._action("Zoom In", lambda: self._zoom(10), shortcut="Ctrl+=", icon_name="zoom")
        self.zoom_out_action = self._action("Zoom Out", lambda: self._zoom(-10), shortcut="Ctrl+-")
        self.zoom_reset_action = self._action("Actual Size", lambda: self._zoom(0), shortcut="Ctrl+0")
        self.fullscreen_action = self._action("Enter Full Screen", self._toggle_fullscreen, shortcut="F11", icon_name="eye", checkable=True)

        # Device
        self.connect_action = self._action("Connect", self._connect_clicked, shortcut="Ctrl+K", icon_name="connect")
        self.disconnect_action = self._action("Disconnect", self._disconnect_clicked, shortcut="Ctrl+Shift+K", icon_name="disconnect")
        self.refresh_ports_action = self._action("Refresh Ports", self._refresh_ports, icon_name="refresh")
        self.baud_group = QActionGroup(self)
        self.baud_group.setExclusive(True)
        self.baud_actions: dict[int, QAction] = {}
        for rate in (115200, 921600):
            action = QAction(f"{rate} baud", self)
            action.setCheckable(True)
            action.setChecked(rate == 115200)
            action.triggered.connect(lambda _checked=False, value=rate: self._set_baud(value))
            self.baud_group.addAction(action)
            self.addAction(action)
            self.baud_actions[rate] = action
        self.device_info_action = self._action("Device Information", self._show_device_info, icon_name="info")
        self.reset_device_action = self._action("Reset Device", self._reset_device, icon_name="power")
        self.enter_bootloader_action = self._action("Enter Bootloader", self._enter_bootloader, icon_name="flash")
        self.harness_action = self._action("Harness Check", self._harness_check, icon_name="check")

        # Tests
        self.run_selected_action = self._action("Run Selected", self._run_selected, shortcut="Ctrl+R", icon_name="play")
        self.run_group_action = self._action("Run Group", self._run_group, shortcut="Ctrl+Alt+R", icon_name="play")
        self.run_all_action = self._action("Run All…", self._run_all, shortcut="Ctrl+Shift+R", icon_name="play")
        self.run_groups_action = self._action("Run Groups…", self._run_groups, icon_name="play")
        self.run_failed_action = self._action("Run Failed Again", self._run_failed)
        self.repeat_action = self._action("Repeat…", self._repeat)
        self.abort_action = self._action("Abort", self._abort, shortcut="Ctrl+.", icon_name="stop")
        self.allow_destructive_action = self._action("Allow Destructive Tests…", self._allow_destructive, checkable=True)
        self.level_actions: dict[str, QAction] = {}
        for level in ("S", "L", "E"):
            action = QAction(f"Level {level}", self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda checked, value=level: self._level_toggled(value, checked))
            self.addAction(action)
            self.level_actions[level] = action
        self.allow_operator_action = self._action("Allow Operator Tests", self._allow_operator, checkable=True)
        self.allow_operator_action.setChecked(True)
        self.clear_results_action = self._action("Clear Results", self._clear_results, icon_name="trash")

        # Tools
        self.update_page_action = self._action("Firmware Update (UART)…", lambda: self.show_page("update"), shortcut="Ctrl+Shift+U", icon_name="update")
        self.flash_page_action = self._action("Flash Firmware (SWD)…", lambda: self.show_page("flash"), icon_name="flash")
        self.provision_action = self._action("Provision Product Configuration…", self._provision, icon_name="lock")
        self.restore_action = self._action("Restore Bench Configuration…", self._restore_bench, icon_name="refresh")
        self.read_options_action = self._action("Read Option Bytes", self._read_options, icon_name="info")
        self.serial_console_action = self._action("Serial Console", self._serial_console, icon_name="console")
        self.simulator_action = self._action("Device Simulator", self._simulator, icon_name="chip")
        self.options_action = self._action("Options…", self.open_preferences, icon_name="settings")

        # Window / Help
        self.minimize_action = self._action("Minimize", self.showMinimized, shortcut="Ctrl+M")
        self.zoom_window_action = self._action("Zoom", self._zoom_window)
        self.front_action = self._action("Bring All to Front", self._bring_all_to_front)
        self.help_action = self._action("HWVAL Studio Help", lambda: self._open_help("guide"), shortcut="F1", icon_name="help")
        self.guide_action = self._action("HWVAL User Guide", lambda: self._open_help("guide"), icon_name="folder")
        self.catalogue_action = self._action("Test Catalogue", lambda: self._open_help("catalogue"), icon_name="all")
        self.shortcuts_action = self._action("Keyboard Shortcuts", lambda: self._open_help("shortcuts"), icon_name="help")
        self.log_folder_action = self._action("Show Log Folder", self._show_log_folder, icon_name="folder")
        self.db_folder_action = self._action("Show Database Folder", self._show_db_folder, icon_name="database")
        self.issue_action = self._action("Report an Issue…", self._report_issue, icon_name="warning")
        self.about_action = self._action("About HWVAL Studio", self._about, role=QAction.MenuRole.AboutRole)
        self.check_updates_action = self._action("Check for Updates…", None, enabled=False)

    # -- menus ---------------------------------------------------------
    def _build_menus(self) -> None:
        menubar = self.menuBar()
        menubar.setNativeMenuBar(is_macos())
        app_menu = menubar.addMenu(APP_NAME)
        app_menu.addAction(self.about_action)
        app_menu.addAction(self.check_updates_action)
        app_menu.addSeparator()
        app_menu.addAction(self.preferences_action)
        app_menu.addSeparator()
        if is_macos():
            app_menu.addMenu("Services")
            app_menu.addSeparator()
            app_menu.addAction(self.hide_action)
            app_menu.addAction(self.hide_others_action)
            app_menu.addAction(self.show_all_action)
            app_menu.addSeparator()
        app_menu.addAction(self.quit_action)

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.new_window_action)
        file_menu.addAction(self.open_report_action)
        file_menu.addAction(self.export_report_action)
        file_menu.addAction(self.export_history_action)
        file_menu.addAction(self.import_results_action)
        self.recent_menu = file_menu.addMenu("Open Recent")
        file_menu.addSeparator()
        file_menu.addAction(self.page_setup_action)
        file_menu.addAction(self.print_report_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_action)
        if not is_macos():
            file_menu.addAction(self.quit_action)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        for action in (self.cut_action, self.copy_action, self.paste_action, self.select_all_action):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.copy_test_id_action)
        edit_menu.addAction(self.copy_result_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.find_action)
        edit_menu.addAction(self.find_next_action)
        if not is_macos():
            edit_menu.addSeparator()
            edit_menu.addAction(self.preferences_action)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.sidebar_action)
        view_menu.addAction(self.log_action)
        view_menu.addAction(self.terminal_action)
        view_menu.addAction(self.details_action)
        view_menu.addSeparator()
        view_menu.addAction(self.operator_action)
        sort_menu = view_menu.addMenu("Sort By")
        for action in self.sort_actions.values():
            sort_menu.addAction(action)
        show_menu = view_menu.addMenu("Show Only")
        for action in self.show_only_actions.values():
            show_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.zoom_reset_action)
        view_menu.addSeparator()
        view_menu.addAction(self.fullscreen_action)

        device_menu = menubar.addMenu("&Device")
        device_menu.addAction(self.connect_action)
        device_menu.addAction(self.disconnect_action)
        device_menu.addAction(self.refresh_ports_action)
        baud_menu = device_menu.addMenu("Baud Rate")
        for action in self.baud_actions.values():
            baud_menu.addAction(action)
        device_menu.addSeparator()
        device_menu.addAction(self.device_info_action)
        device_menu.addAction(self.reset_device_action)
        device_menu.addAction(self.enter_bootloader_action)
        device_menu.addSeparator()
        device_menu.addAction(self.harness_action)

        tests_menu = menubar.addMenu("&Tests")
        tests_menu.addAction(self.run_selected_action)
        tests_menu.addAction(self.run_group_action)
        tests_menu.addAction(self.run_all_action)
        tests_menu.addAction(self.run_groups_action)
        tests_menu.addAction(self.run_failed_action)
        tests_menu.addAction(self.repeat_action)
        tests_menu.addAction(self.abort_action)
        tests_menu.addSeparator()
        tests_menu.addAction(self.allow_destructive_action)
        level_menu = tests_menu.addMenu("Level Filter")
        for action in self.level_actions.values():
            level_menu.addAction(action)
        tests_menu.addAction(self.allow_operator_action)
        tests_menu.addSeparator()
        tests_menu.addAction(self.clear_results_action)

        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(self.update_page_action)
        tools_menu.addAction(self.flash_page_action)
        tools_menu.addAction(self.provision_action)
        tools_menu.addAction(self.restore_action)
        tools_menu.addAction(self.read_options_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.serial_console_action)
        tools_menu.addAction(self.simulator_action)
        if not is_macos():
            tools_menu.addSeparator()
            tools_menu.addAction(self.options_action)

        if is_macos():
            window_menu = menubar.addMenu("&Window")
            window_menu.addAction(self.minimize_action)
            window_menu.addAction(self.zoom_window_action)
            window_menu.addAction(self.front_action)
            window_menu.addSeparator()
            self.window_menu = window_menu
            self._window_menu_pinned = 4

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self.help_action)
        help_menu.addAction(self.guide_action)
        help_menu.addAction(self.catalogue_action)
        help_menu.addAction(self.shortcuts_action)
        help_menu.addSeparator()
        help_menu.addAction(self.log_folder_action)
        help_menu.addAction(self.db_folder_action)
        help_menu.addAction(self.issue_action)
        if not is_macos():
            help_menu.addSeparator()
            help_menu.addAction(self.about_action)

    # -- toolbar -------------------------------------------------------
    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.toolbar = toolbar
        self.sidebar_button = QPushButton()
        self.sidebar_button.setObjectName("Flat")
        self.sidebar_button.setIcon(icon("sidebar", COLORS["secondary"], 18))
        self.sidebar_button.setToolTip("Show/Hide Sidebar")
        self.sidebar_button.clicked.connect(lambda: self._toggle_sidebar())
        toolbar.addWidget(self.sidebar_button)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(270)
        self.port_combo.setToolTip("Serial port")
        toolbar.addWidget(self.port_combo)
        self.connect_button = QPushButton(icon("connect", COLORS["accent"], 15), "Connect")
        self.connect_button.setObjectName("Accent")
        self.connect_button.clicked.connect(self._connect_clicked)
        toolbar.addWidget(self.connect_button)
        self.activity = ActivityView()
        toolbar.addWidget(self.activity)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.run_button = QPushButton(icon("play", COLORS["pass"], 15), "Run")
        self.run_button.setToolTip("Run selected tests (⌘R)")
        self.run_button.clicked.connect(self._run_selected)
        toolbar.addWidget(self.run_button)
        self.abort_button = QPushButton(icon("stop", COLORS["fail"], 15), "Abort")
        self.abort_button.setToolTip("Abort the current run (⌘.)")
        self.abort_button.clicked.connect(self._abort)
        toolbar.addWidget(self.abort_button)
        self.search = SearchBox("Search tests…")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._search_changed)
        toolbar.addWidget(self.search)

    # -- state ---------------------------------------------------------
    def _update_actions(self) -> None:
        if not hasattr(self, "connect_action"):
            return
        connected = self.identity is not None
        hwval = connected and self.role == Role.HWVAL
        demo = connected and self.role == Role.DEMO
        busy = self._busy or self._run_active or self._update_active
        self.connect_action.setEnabled(not busy)
        self.connect_action.setText("Disconnect" if connected else "Connect")
        self.connect_button.setText("Disconnect" if connected else "Connect")
        if connected:
            self.connect_button.setIcon(icon("disconnect", COLORS["secondary"], 15))
        else:
            self.connect_button.setIcon(icon("connect", COLORS["accent"], 15))
        self.disconnect_action.setEnabled(connected and not busy)
        for action in (
            self.run_selected_action,
            self.run_group_action,
            self.run_all_action,
            self.run_groups_action,
            self.run_failed_action,
            self.repeat_action,
            self.allow_destructive_action,
            self.allow_operator_action,
            self.clear_results_action,
        ):
            action.setEnabled(hwval and not self._run_active and not self._update_active)
        self.abort_action.setEnabled(self._run_active)
        self.run_button.setEnabled(hwval and not self._run_active and not self._update_active)
        self.abort_button.setEnabled(self._run_active)
        self.run_button.setVisible(not self._operator_mode)
        self.abort_button.setVisible(not self._operator_mode)
        self.device_info_action.setEnabled(connected)
        self.reset_device_action.setEnabled(connected and not busy)
        self.enter_bootloader_action.setEnabled(demo and not busy)
        self.harness_action.setEnabled(hwval and not busy)
        for action in self.baud_actions.values():
            action.setEnabled(connected)
        self.update_page_action.setEnabled(connected and not busy and not self._operator_mode)
        self.flash_page_action.setEnabled(not busy and not self._operator_mode)
        self.provision_action.setEnabled(not busy and not self._operator_mode)
        self.restore_action.setEnabled(not busy and not self._operator_mode)
        self.read_options_action.setEnabled(not busy and not self._operator_mode)
        self.serial_console_action.setEnabled(connected and not self._operator_mode)
        self.simulator_action.setEnabled(True)
        self.update_page.update_button.setEnabled(
            connected and self.role in (Role.BOOTLOADER, Role.DEMO) and self.update_page.image is not None and not busy
        )
        self.preferences_action.setEnabled(not self._operator_mode)
        self.options_action.setEnabled(not self._operator_mode)
        self.operator_action.setEnabled(True)
        self.details_action.setEnabled(hwval)
        for action in self.level_actions.values():
            action.setEnabled(hwval)
        if not hwval:
            self.abort_action.setEnabled(False)
        if self._operator_mode:
            for action in (
                self.run_selected_action,
                self.run_group_action,
                self.run_all_action,
                self.run_groups_action,
                self.run_failed_action,
                self.repeat_action,
                self.allow_destructive_action,
                self.allow_operator_action,
                self.clear_results_action,
            ):
                action.setEnabled(False)
            for action in self.level_actions.values():
                action.setEnabled(False)
            self.abort_action.setEnabled(self._run_active)
