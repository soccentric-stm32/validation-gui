"""Sidebar, page navigation and connection controls."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QToolTip, QTreeWidgetItem

from hwval_studio.core.client import Identity
from hwval_studio.protocol.generated.hwlink.Role import Role
from hwval_studio.transport.port_lock import acquire_port, release_port
from hwval_studio.ui.theme import COLORS, icon, nav_icon

CATEGORY_ICONS = {
    "CPU & System": "cpu",
    "Memory": "memory",
    "Clocks & Power": "clock",
    "GPIO & Board I/O": "gpio",
    "Analog": "analog",
    "Timers": "timers",
    "Communication": "comm",
    "Connectivity": "connectivity",
    "Graphics & Media": "graphics",
    "Other Peripherals": "other",
    "Board": "board",
}

GROUP_ICONS = {
    "ADC": "analog",
    "DAC": "analog",
    "CLK": "clock",
    "RTC": "clock",
    "PWR": "power",
    "RST": "power",
    "WDG": "timers",
    "TIM": "timers",
    "LPTIM": "timers",
    "GPIO": "gpio",
    "LED": "led",
    "BTN": "button",
    "UART": "comm",
    "SPI": "comm",
    "I2S": "comm",
    "I2C": "comm",
    "CAN": "comm",
    "SAI": "comm",
    "SPDIF": "comm",
    "ETH": "ethernet",
    "USB": "usb",
    "USBHS": "usb",
    "CORE": "cpu",
    "CACHE": "cpu",
    "MPU": "cpu",
    "DMA": "cpu",
    "DBG": "cpu",
    "INT": "cpu",
    "DEV": "chip",
    "BRD": "board",
    "STLK": "board",
}


class NavigationMixin:
    # -- sidebar -------------------------------------------------------
    def _rebuild_sidebar(self) -> None:
        current = self._current_key()
        self.sidebar_tree.blockSignals(True)
        self.sidebar_tree.clear()
        self._sidebar_items = {}

        def section(title: str) -> QTreeWidgetItem:
            item = QTreeWidgetItem([title.upper()])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setForeground(0, QColor(COLORS["secondary"]))
            font = QFont()
            font.setPointSizeF(8.5)
            font.setBold(True)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
            item.setFont(0, font)
            item.setSizeHint(0, QSize(0, 27))
            self.sidebar_tree.addTopLevelItem(item)
            return item

        def add_item(
            parent: QTreeWidgetItem | None, key: str, text: str, icon_name: str, tooltip: str = ""
        ) -> QTreeWidgetItem:
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setIcon(0, nav_icon(icon_name, 17))
            item.setToolTip(0, tooltip)
            item.setSizeHint(0, QSize(0, 24))
            if parent is None:
                self.sidebar_tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self._sidebar_items[key] = item
            return item

        device = section("Device")
        add_item(device, "overview", "Overview", "overview", "Identity, clocks, option bytes and harness")

        tests = section("Test & Validation")
        add_item(tests, "all", "All Tests", "all", "Every test of every group")
        categories: dict[str, QTreeWidgetItem] = {}
        for group in self.controller.groups:
            category = group.category if group.category in CATEGORY_ICONS else "Other Peripherals"
            if category not in categories:
                cat_item = QTreeWidgetItem([category])
                cat_item.setIcon(0, icon(CATEGORY_ICONS[category], COLORS["secondary"], 16))
                cat_item.setForeground(0, QColor(COLORS["secondary"]))
                cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                cat_item.setSizeHint(0, QSize(0, 23))
                tests.addChild(cat_item)
                categories[category] = cat_item
            icon_name = GROUP_ICONS.get(group.code, CATEGORY_ICONS[category])
            add_item(categories[category], f"group:{group.code}", group.name, icon_name, f"{group.test_count} tests")
        if not self.controller.groups:
            placeholder = QTreeWidgetItem(["Connect to HWVAL to load the catalogue"])
            placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            placeholder.setForeground(0, QColor(COLORS["muted"]))
            tests.addChild(placeholder)

        firmware = section("Firmware")
        add_item(firmware, "update", "Update (UART)", "update", "Update an application through the A/B bootloader")
        add_item(firmware, "flash", "Flash (SWD)", "flash", "Flash and provision over SWD with OpenOCD")
        add_item(firmware, "demo", "Demo App", "demo", "LEDs, button, health and faults")

        data = section("Data")
        add_item(data, "history", "History", "history", "Stored runs and reports")
        add_item(data, "reports", "Reports", "reports", "Preview, export and print reports")
        self.sidebar_tree.expandAll()
        self._update_sidebar_badges()
        self._update_sidebar_state()
        self.sidebar_tree.blockSignals(False)
        if current:
            self._select_key(current)

    def _current_key(self) -> str:
        item = self.sidebar_tree.currentItem() if hasattr(self, "sidebar_tree") else None
        if item is None:
            return ""
        return str(item.data(0, Qt.ItemDataRole.UserRole) or "")

    def _select_key(self, key: str) -> None:
        item = getattr(self, "_sidebar_items", {}).get(key)
        if item is not None:
            self.sidebar_tree.setCurrentItem(item)
            self.show_page(key)

    def _sidebar_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        key = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not key:
            return
        if not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            QToolTip.showText(self.mapToGlobal(self.rect().center()), item.toolTip(0) or "Not available", self)
            return
        self.show_page(key)

    def _select_sidebar_for_page(self, key: str) -> None:
        item = getattr(self, "_sidebar_items", {}).get(key)
        if item is not None:
            self.sidebar_tree.setCurrentItem(item)

    def _update_sidebar_state(self) -> None:
        role = self.role
        for key, item in getattr(self, "_sidebar_items", {}).items():
            if key in {"overview", "flash", "history", "reports"}:
                continue
            base_tip = item.toolTip(0)
            if key == "all" or key.startswith("group:"):
                enabled = role == Role.HWVAL
                tip = base_tip if enabled else "Connect to HWVAL to run tests"
            elif key == "update":
                enabled = role in (Role.BOOTLOADER, Role.DEMO, Role.HWVAL)
                tip = base_tip if role in (Role.BOOTLOADER, Role.DEMO) else "UART update requires BOOT or DEMO (HWVAL is the bench configuration)"
            elif key == "demo":
                enabled = role == Role.DEMO
                tip = base_tip if enabled else "Connect to the DEMO application"
            else:
                enabled = True
                tip = base_tip
            if enabled:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(0, QColor(COLORS["text"]))
            else:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setForeground(0, QColor(COLORS["muted"]))
            item.setToolTip(0, tip)

    def _update_sidebar_badges(self) -> None:
        if not hasattr(self, "_sidebar_items"):
            return
        overall = {"PASS": 0, "FAIL": 0, "SKIP": 0, "N/A": 0}
        for group in self.controller.groups:
            counts = self.tests_page.group_badge(group.code)
            for key in overall:
                overall[key] += counts.get(key, 0)
            item = self._sidebar_items.get(f"group:{group.code}")
            if item is None:
                continue
            mark = ""
            color = COLORS["text"]
            if counts.get("FAIL", 0):
                mark = f"  ✗{counts['FAIL']}"
                color = COLORS["fail"]
            elif counts.get("PASS", 0):
                mark = f"  ✓{counts['PASS']}"
                color = COLORS["pass"]
            elif counts.get("SKIP", 0):
                mark = f"  –{counts['SKIP']}"
                color = COLORS["skip"]
            item.setText(0, group.name + mark)
            item.setForeground(0, QColor(color))
            icon_name = GROUP_ICONS.get(group.code, CATEGORY_ICONS.get(group.category, "chip"))
            item.setIcon(0, icon(icon_name, color, 17) if mark else nav_icon(icon_name, 17))
        all_item = self._sidebar_items.get("all")
        if all_item is not None:
            mark = ""
            color = COLORS["text"]
            if overall["FAIL"]:
                mark = f"  ✗{overall['FAIL']}"
                color = COLORS["fail"]
            elif overall["PASS"]:
                mark = f"  ✓{overall['PASS']}"
                color = COLORS["pass"]
            all_item.setText(0, "All Tests" + mark)
            all_item.setForeground(0, QColor(color))

    def _group_counts_changed(self, _code: str, _counts: object) -> None:
        self._update_sidebar_badges()

    # -- page selection ------------------------------------------------
    def show_page(self, key: str, *, force: bool = False) -> None:
        if key.startswith("group:"):
            self.tests_page.set_group(key.split(":", 1)[1])
            self.stack.setCurrentWidget(self.tests_page)
        elif key == "all":
            self.tests_page.set_group(None)
            self.stack.setCurrentWidget(self.tests_page)
        elif key in self.pages:
            self.stack.setCurrentWidget(self.pages[key])
        else:
            return
        if not self._operator_mode:
            self._select_sidebar_for_page(key if key == "all" or key.startswith("group:") else key)
        self.preferences.last_selected_item = key
        self.search.setVisible(self.stack.currentWidget() is self.tests_page)
        if self.stack.currentWidget() is self.tests_page:
            self.search.setPlaceholderText("Search tests by ID, title, group or requirement…")
        if key == "history":
            self.history_page.refresh()
        elif key == "reports":
            self.reports_page.refresh()
        elif key == "update":
            self.controller.refresh_boot_info()
        elif key == "demo":
            self.controller.refresh_demo_status()
        elif key == "overview":
            self._refresh_overview()

    # -- ports / connection -------------------------------------------
    def _refresh_ports(self) -> None:
        self._ports_changed(self.controller.refresh_ports())

    def _ports_changed(self, ports: list[Any]) -> None:
        if not hasattr(self, "port_combo"):
            return
        current = self.port_combo.currentData()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for port in ports:
            self.port_combo.addItem(port.label(), port.device)
        if current:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        elif self.preferences.last_port:
            index = self.port_combo.findData(self.preferences.last_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        self.port_combo.blockSignals(False)
        if not ports:
            self.port_combo.addItem("No serial ports found", "")

    def _port(self) -> str:
        data = self.port_combo.currentData() if hasattr(self, "port_combo") else ""
        return str(data or "")

    def _connect_clicked(self) -> None:
        if self.identity is not None:
            self._disconnect_clicked()
            return
        port = self._port()
        if not port:
            self._show_error("No serial port selected. Attach the board or use Tools > Device Simulator.")
            return
        self._manual_disconnect = False
        self._connect_port(port)

    def _connect_port(self, port: str) -> None:
        if self._port_lock is not None and port == self._locked_port:
            # Reconnect after a reset or link loss: the lock is already ours.
            self.controller.connect_device(port)
            return
        if self._port_lock is not None:
            # The selection changed: drop the old port's lock before taking
            # the new one, or the old port stays locked forever.
            release_port(self._port_lock)
            self._port_lock = None
            self._locked_port = None
        if self.identity is not None:
            if self._port() == port:
                return
            self.controller.disconnect_device()
        lock = acquire_port(port)
        if lock is None:
            self._show_error(f"{port} is already in use by another HWVAL Studio window or process.")
            return
        self._port_lock = lock
        self._locked_port = port
        self.controller.connect_device(port)

    def _disconnect_clicked(self) -> None:
        self._manual_disconnect = True
        self.controller.disconnect_device()
        release_port(self._port_lock)
        self._port_lock = None
        self._locked_port = None

    def _auto_connect(self) -> None:
        if self.identity is not None or not self.preferences.auto_connect:
            return
        preferred = self.preferences.last_port or self.preferences.default_port
        index = self.port_combo.findData(preferred) if preferred else -1
        if index < 0 and self.port_combo.count():
            for candidate in range(self.port_combo.count()):
                data = str(self.port_combo.itemData(candidate) or "")
                if data and not data.startswith(("simulator:", "sim:", "tcp://")):
                    index = candidate
                    break
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
            self._connect_port(self._port())

    def _schedule_reconnect(self) -> None:
        if self._reconnect_pending or not self.preferences.auto_connect or self._manual_disconnect:
            return
        if self._run_active or self._update_active:
            return
        if not self.port_combo.currentData():
            return
        self._reconnect_pending = True
        self.log_console.warn("serial link lost; reconnecting in 5 s")
        QTimer.singleShot(5000, self._attempt_reconnect)

    def _attempt_reconnect(self) -> None:
        self._reconnect_pending = False
        if self.identity is not None or self._manual_disconnect:
            return
        port = self._port()
        if port:
            self.log_console.info(f"reconnecting to {port}")
            self._connect_port(port)

    def _connection_state(self, state: str) -> None:
        self.status_connection.setText(state.capitalize())
        if state == "connected":
            self.activity.set_state(
                f"{self.identity.role_name if self.identity else 'Connected'}",
                f"{self.identity.firmware_name if self.identity else ''} {self.identity.version if self.identity else ''}",
            )
        elif state in {"connecting", "updating", "running", "aborting", "link lost"}:
            self.activity.set_busy(state.capitalize(), "")
        else:
            self.activity.set_idle("Not connected", "Choose a port and click Connect")
        self._update_actions()

    def _connected(self, identity: Identity) -> None:
        self.identity = identity
        self.role = identity.role
        self.status_connection.setText(f"Connected · {identity.role_name}")
        self.status_role.setText(f"{identity.firmware_name} {identity.version}")
        self.status_port.setText(self._port())
        self.terminal.refresh_ports(self._port())
        self.terminal.stop("Board port in use")
        self.activity.set_state(f"{identity.role_name} {identity.version}", f"{identity.firmware_name} · Ready")
        self.port_combo.setToolTip(f"{identity.uid_hex} · {identity.firmware_name} {identity.version}")
        self.overview_page.set_identity(identity)
        self.overview_page.set_role(identity.role)
        self.update_page.set_identity(identity)
        self.operator_page.set_identity(identity)
        self._update_sidebar_state()
        self._update_actions()
        self._rebuild_sidebar()
        self.show_banner(f"Connected to {identity.role_name} {identity.firmware_name} {identity.version}")
        self.update_page.activate.setChecked(self.preferences.auto_activate)
        if identity.role == Role.HWVAL and not self.controller.groups:
            self.controller.refresh_device_info()
        if identity.role == Role.BOOTLOADER:
            self.controller.refresh_boot_info()
        if identity.role == Role.DEMO:
            self.controller.refresh_demo_status()

    def _disconnected(self, reason: str) -> None:
        was_connected = self.identity is not None
        self.identity = None
        self.role = 0
        self.status_connection.setText("Not connected")
        self.status_role.setText("")
        self.status_port.setText("")
        self.terminal.resume()
        self.activity.set_idle("Not connected", reason or "Choose a port and click Connect")
        self.overview_page.set_identity(None)
        self.overview_page.set_role(0)
        self.update_page.set_identity(None)
        self.operator_page.set_identity(None)
        self._update_sidebar_state()
        self._update_actions()
        if was_connected:
            self.log_console.warn(f"disconnected: {reason}" if reason else "disconnected")
            if reason:
                self.show_banner(f"Device disconnected: {reason}", error=True)
            if not self._manual_disconnect:
                self._schedule_reconnect()
            self.history_page.refresh()
            self.reports_page.refresh()
