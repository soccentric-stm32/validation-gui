"""Controller events, runs, firmware operations and operator mode."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

from hwval_studio import APP_NAME
from hwval_studio.core.client import Selection
from hwval_studio.platform_support import (
    alert_sound,
    bring_to_front,
    is_macos,
    request_attention,
    serial_permission_hint,
    set_progress,
)
from hwval_studio.protocol.generated.hwlink.Role import Role
from hwval_studio.ui.dialogs.operator_prompt import OperatorPromptDialog
from hwval_studio.ui.theme import COLORS


class HandlersMixin:
    def _test_by_id(self, test_id: str) -> Any:
        return next((test for test in self.controller.tests if test.id == test_id), None)

    # -- controller events --------------------------------------------
    def _log_message(self, level: str, text: str) -> None:
        self.log_console.log(level, text)
        getattr(self.logger, level.lower(), self.logger.info)(text)

    def _device_info_ready(self, info: dict[str, Any]) -> None:
        self.overview_page.set_device_info(info)
        self._update_actions()

    def _catalogue_ready(self, groups: list[Any], tests: list[Any]) -> None:
        self.tests_page.set_catalogue(groups, tests)
        catalogue = {
            test.id: {
                "title": test.title,
                "level": test.level_name,
                "reqs": test.reqs,
                "operator": test.operator,
                "destructive": test.destructive,
                "needs": test.needs,
            }
            for test in tests
        }
        self.tests_page.table.set_catalogue(catalogue)
        self._rebuild_sidebar()
        self._update_actions()

    def _harness_ready(self, harness: dict[str, Any]) -> None:
        self.overview_page.set_harness(harness)
        missing = self.overview_page.mark_missing_harness(self.controller.tests)
        self.tests_page.set_missing_tests(missing)
        if missing:
            self.show_banner(
                f"Harness check: {len(missing)} test(s) need a missing wire: " + ", ".join(sorted(missing)[:8]),
                error=True,
            )
        else:
            self.show_banner("Harness check: all fitted wires are present")

    def _boot_info_ready(self, info: dict[str, Any]) -> None:
        self.controller.boot_info = info
        self.overview_page.set_boot_info(info)
        self.update_page.set_boot_info(info)

    def _demo_status_ready(self, status: dict[str, Any]) -> None:
        self.controller.demo_status = status
        self.demo_page.set_status(status)

    def _run_active_changed(self, active: bool) -> None:
        self._run_active = active
        self._update_actions()
        self.abort_button.setEnabled(active)
        self.run_button.setEnabled(not active and self.role == Role.HWVAL)

    def _run_started(self, data: dict[str, Any]) -> None:
        self._run_started_at = time.monotonic()
        total = int(data.get("total", 0))
        self.activity.set_progress(f"Running {total} test(s)", 0, max(1, total))
        self.operator_page.start_run(total)
        self._run_active = True
        self._update_actions()

    def _test_started(self, data: dict[str, Any]) -> None:
        self.tests_page.on_test_started(data)
        index = int(data.get("index", 0))
        total = int(data.get("total", 0))
        elapsed = time.monotonic() - getattr(self, "_run_started_at", time.monotonic())
        self.activity.set_progress(f"Running {data.get('id', '')} · {elapsed:.0f}s", index, max(1, total))
        test = self._test_by_id(str(data.get("id", "")))
        self.operator_page.test_started(data, test.title if test else "")

    def _test_result(self, result: dict[str, Any]) -> None:
        self.tests_page.on_test_result(result)
        self.operator_page.test_result(result)
        self._update_sidebar_badges()
        if self._run_active:
            self.activity.set_state("Running", f"{result.get('id', '')} — {result.get('result_name', '')}")

    def _run_prompt(self, prompt: dict[str, Any]) -> None:
        if self._prompt_dialog is not None:
            self._prompt_dialog.close()
        dialog = OperatorPromptDialog(prompt, self, operator_mode=self._operator_mode)
        dialog.answered.connect(self.controller.answer_prompt)
        dialog.timed_out.connect(
            lambda _id: self.show_banner(
                "Operator prompt timed out; the test will be reported as SKIP NO_OPERATOR", error=True
            )
        )
        dialog.finished.connect(lambda _result: setattr(self, "_prompt_dialog", None))
        self._prompt_dialog = dialog
        if not self.isActiveWindow():
            alert_sound()
            bring_to_front(self)
            request_attention(self)
        dialog.open()

    def _run_prompt_done(self, done: dict[str, Any]) -> None:
        """TST-032: HWVAL answered the prompt itself (B1 or timeout)."""
        if self._prompt_dialog is not None:
            self._prompt_dialog.close_on_done(done)

    def _run_finished(self, payload: dict[str, Any]) -> None:
        self._run_active = False
        self._last_results = payload.get("results", [])
        self._last_run_id = int(payload.get("run_id", 0) or self._last_run_id)
        self.tests_page.run_finished(payload)
        self.tests_page.set_results(payload.get("results", []))
        self.operator_page.run_finished(payload)
        counts = payload.get("counts", {})
        self.activity.set_state(
            "Ready",
            f"{counts.get('pass', 0)} PASS · {counts.get('fail', 0)} FAIL · {counts.get('skip', 0)} SKIP",
        )
        self._update_sidebar_badges()
        self._update_actions()
        for widget in (self.tests_page.destructive_toggle, self.allow_destructive_action):
            widget.blockSignals(True)
            widget.setChecked(False)
            widget.blockSignals(False)
        overall = payload.get("overall", "PASS")
        self.show_banner(
            f"Run complete: {overall} · {counts.get('pass', 0)} passed, "
            f"{counts.get('fail', 0)} failed, {counts.get('skip', 0)} skipped",
            error=overall != "PASS",
        )
        self.history_page.refresh()
        self.reports_page.refresh()
        self.preferences.test_preset = self.tests_page.preset()

    def _run_failed(self, message: str) -> None:
        self._run_active = False
        self.operator_page.run_failed(message)
        self.activity.set_state("Ready", "Run failed")
        self._update_actions()
        self._show_error(message)

    def _update_progress(self, done: int, total: int, speed: float) -> None:
        self.activity.set_progress("Updating firmware", done, total)
        self.update_page.show_progress(done, total, speed)
        set_progress(self, done, total)

    def _update_finished(self, payload: dict[str, Any]) -> None:
        self._update_active = False
        self.update_page.show_finished(payload)
        self.activity.set_state("Ready", "Update verified")
        set_progress(self, 0, 0)
        self._update_actions()
        self.history_page.refresh()
        self.reports_page.refresh()
        self.update_page.set_busy(False)
        self.show_banner("Firmware update verified and written to the inactive slot")
        if self.controller.role == Role.BOOTLOADER:
            self.controller.refresh_boot_info()

    def _update_failed(self, message: str) -> None:
        self._update_active = False
        self.update_page.show_failed(message)
        self.activity.set_state("Ready", "Update failed")
        set_progress(self, 0, 0)
        self._update_actions()

    def _swd_output(self, line: str) -> None:
        self.log_console.info(line)
        self.flash_page.show_output(line)

    def _swd_finished(self, operation: str, result: dict[str, Any]) -> None:
        self.flash_page.show_finished(operation, result)
        if "options" in result:
            self.flash_page.show_options(result)
        self.flash_page.set_busy(False)
        self.activity.set_state("Ready", operation)
        self._update_actions()
        self.history_page.refresh()
        self.reports_page.refresh()
        lowered = operation.lower()
        if lowered.startswith("provision"):
            self.show_banner("Product configuration provisioned. Connect to BOOT over UART to load the first application.")
        elif lowered.startswith("flash"):
            self.show_banner("HWVAL flashed and verified in single-bank mode.")
        elif lowered.startswith("restore"):
            self.show_banner("Bench configuration restored.")

    def _swd_failed(self, message: str) -> None:
        self.flash_page.show_failed(message)
        self.flash_page.set_busy(False)
        self.activity.set_state("Ready", "SWD operation failed")
        self._update_actions()
        self._show_error(message)

    def _button_event(self, event: dict[str, Any]) -> None:
        self.demo_page.button_event(event)
        self.show_banner(
            f"B1 {event.get('press_name', '')} press · pattern {event.get('pattern_name', '')} "
            f"({event.get('period_ms', 0)} ms)"
        )
        if self._prompt_dialog is not None:
            self._prompt_dialog.close_on_button(event)

    def _ping_failed(self, misses: int) -> None:
        self.activity.set_state("Link", f"Ping missed ({misses}/3)")

    def _operation_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_actions()

    # -- banners / errors ---------------------------------------------
    def _show_error(self, message: str) -> None:
        if not message:
            return
        hint = serial_permission_hint(self._port(), message)
        detail = message if not hint else f"{message}\n\n{hint}"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(f"{APP_NAME} error")
        box.setText(message.splitlines()[0][:240] if message else "An error occurred")
        box.setInformativeText(hint or "")
        box.setDetailedText(detail)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        self.log_console.error(message)

    def show_banner(self, text: str, *, error: bool = False) -> None:
        self.banner.setText(text)
        if error:
            self.banner.setStyleSheet(
                f"background: {COLORS['fail_soft']}; border: 1px solid {COLORS['fail']}55; "
                f"border-radius: 8px; padding: 7px 11px; color: {COLORS['text']};"
            )
        else:
            self.banner.setStyleSheet(
                f"background: {COLORS['accent_soft']}; border: 1px solid {COLORS['accent']}44; "
                f"border-radius: 8px; padding: 7px 11px; color: {COLORS['text']};"
            )
        self.banner.show()
        self.banner_timer.start(6500)

    # -- run actions ---------------------------------------------------
    def _run_selection(self, selection: Selection) -> None:
        if self.identity is None or self.role != Role.HWVAL:
            self._show_error("Connect to a HWVAL device before running tests.")
            return
        if self._run_active:
            return
        self._last_selection = selection
        self.tests_page.reset_for_run()
        self.tests_page.destructive_toggle.blockSignals(True)
        self.tests_page.destructive_toggle.setChecked(False)
        self.tests_page.destructive_toggle.blockSignals(False)
        self.allow_destructive_action.blockSignals(True)
        self.allow_destructive_action.setChecked(False)
        self.allow_destructive_action.blockSignals(False)
        mode = "OPERATOR" if self._operator_mode else "ENGINEER"
        operator = self.operator_page.operator_name.currentText().strip() if self._operator_mode else ""
        run_id = self.controller.start_run(selection, mode=mode, operator_name=operator)
        if run_id:
            self._last_run_id = run_id
            if not self._operator_mode:
                self.show_page("tests")
            self._run_active = True
            self._update_actions()
            self.activity.set_progress("Preparing run…", 0, 1)

    def _run_selected(self) -> None:
        if self._operator_mode:
            self.operator_page._run()
        else:
            self.tests_page.run_selected()

    def _run_group(self) -> None:
        if self._operator_mode:
            self.operator_page._run()
        else:
            self.tests_page.run_group()

    def _run_groups(self) -> None:
        codes = ", ".join(group.code for group in self.controller.groups)
        text, ok = QInputDialog.getText(
            self,
            "Run Groups",
            "Group codes (comma-separated, e.g. ADC,DAC,CLK):\n" + codes[:900],
        )
        if not ok or not text.strip():
            return
        groups = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
        if not groups:
            return
        selection = Selection(
            groups=groups,
            all_tests=False,
            levels=self.tests_page._levels(),
            allow_operator=self.tests_page.operator_toggle.isChecked(),
            allow_destructive=self.tests_page.destructive_toggle.isChecked(),
            repeat=self.tests_page.repeat_spin.value(),
            until_fail=self.tests_page.until_fail.isChecked(),
        )
        self._run_selection(selection)

    def _run_all(self) -> None:
        if self._operator_mode:
            self.operator_page._run()
            return
        selection = (
            self.tests_page._selection_for_group()
            if self.stack.currentWidget() is self.tests_page
            else self.tests_page.preset()
        )
        selection.ids = []
        selection.groups = []
        selection.all_tests = True
        levels = selection.levels or "S,L,E"
        box = QMessageBox(self)
        box.setWindowTitle("Run All Tests")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"Run all tests at level {levels}?")
        box.setInformativeText(
            f"Operator tests: {'allowed' if selection.allow_operator else 'disabled'}\n"
            f"Repeat: {selection.repeat}{' (until failure)' if selection.until_fail else ''}\n"
            "Destructive tests are off unless enabled in the Tests menu."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self._run_selection(selection)

    def _run_failed(self) -> None:
        if not self._last_results:
            self._show_error("There are no results from a previous run.")
            return
        self.tests_page.run_failed_again(self._last_results)

    def _repeat(self) -> None:
        self.tests_page.repeat_dialog()

    def _abort(self) -> None:
        if not self._run_active:
            return
        self.controller.abort_run()
        self.tests_page.aborting()
        self.operator_page.aborting()
        self.activity.set_busy("Aborting…", "Waiting for the device to finish")

    def _allow_destructive(self, checked: bool) -> None:
        if not hasattr(self, "tests_page"):
            return
        self.tests_page.destructive_toggle.blockSignals(True)
        self.tests_page.destructive_toggle.setChecked(checked)
        self.tests_page.destructive_toggle.blockSignals(False)
        if not checked:
            return
        destructive = [test for test in self.controller.tests if test.destructive]
        names = "\n".join(f"• {test.id} — {test.title}" for test in destructive) or "• (none in the current catalogue)"
        box = QMessageBox(self)
        box.setWindowTitle("Allow destructive tests?")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Destructive tests are enabled for the next run only.")
        box.setInformativeText(
            names + "\n\nThe scope can include flash sectors, backup SRAM/registers, RTC configuration and MCU resets."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            self.allow_destructive_action.blockSignals(True)
            self.allow_destructive_action.setChecked(False)
            self.allow_destructive_action.blockSignals(False)
            self.tests_page.destructive_toggle.blockSignals(True)
            self.tests_page.destructive_toggle.setChecked(False)
            self.tests_page.destructive_toggle.blockSignals(False)

    def _sync_level_actions(self, levels: str) -> None:
        selected = set(levels.replace(" ", "").split(","))
        for level, action in self.level_actions.items():
            action.blockSignals(True)
            action.setChecked(level in selected)
            action.blockSignals(False)

    def _sync_operator_action(self, checked: bool) -> None:
        self.allow_operator_action.blockSignals(True)
        self.allow_operator_action.setChecked(checked)
        self.allow_operator_action.blockSignals(False)

    def _sync_destructive_action(self, checked: bool) -> None:
        self.allow_destructive_action.blockSignals(True)
        self.allow_destructive_action.setChecked(checked)
        self.allow_destructive_action.blockSignals(False)

    def _allow_operator(self, checked: bool) -> None:
        if not hasattr(self, "tests_page"):
            return
        self.tests_page.operator_toggle.blockSignals(True)
        self.tests_page.operator_toggle.setChecked(checked)
        self.tests_page.operator_toggle.blockSignals(False)

    def _level_toggled(self, level: str, checked: bool) -> None:
        if not hasattr(self, "tests_page"):
            return
        button = self.tests_page.level_buttons.get(level)
        if button is not None:
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)

    def _clear_results(self) -> None:
        if self.identity is None or self.role != Role.HWVAL:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Clear results")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Clear the results stored on the device?")
        box.setInformativeText("Runs already stored in the local history are kept.")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.controller.clear_results()
            self.tests_page.reset_for_run()
            self.show_banner("Device results cleared")

    # -- device / firmware --------------------------------------------
    def _refresh_overview(self) -> None:
        if self.identity is None:
            return
        if self.role == Role.HWVAL:
            self.controller.refresh_device_info()
            self.controller.refresh_harness()
        elif self.role == Role.BOOTLOADER:
            self.controller.refresh_boot_info()
        elif self.role == Role.DEMO:
            self.controller.refresh_demo_status()

    def _harness_check(self) -> None:
        if self.role != Role.HWVAL:
            return
        self.show_page("overview")
        self.controller.refresh_harness()
        self.show_banner("Reading harness wiring from HWVAL…")

    def _reset_device(self) -> None:
        if self.identity is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Reset device")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Reset the device now?")
        box.setInformativeText("Any active run will be aborted." if self._run_active else "The link will be re-established automatically.")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.controller.reset_device()

    def _enter_bootloader(self) -> None:
        if self.role != Role.DEMO:
            self._show_error("Enter Bootloader is available when the DEMO application is connected.")
            return
        self.controller.enter_bootloader()
        self.activity.set_busy("Entering bootloader…", "Waiting for BOOT")

    def _show_device_info(self) -> None:
        if self.identity is None:
            self._show_error("Connect to a device first.")
            return
        from hwval_studio.ui.widgets import KeyValueGrid

        dialog = QDialog(self)
        dialog.setWindowTitle("Device Information")
        dialog.resize(620, 520)
        layout = QVBoxLayout(dialog)
        title = QLabel(f"{self.identity.role_name} · {self.identity.firmware_name} {self.identity.version}")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        grid = KeyValueGrid()
        items: dict[str, Any] = {
            "Chip UID": self.identity.uid_hex,
            "DEV_ID / REV_ID": f"0x{self.identity.dev_id:03X} / 0x{self.identity.rev_id:04X}",
            "Git commit": self.identity.commit or "—",
            "Build time": self.identity.build_time or "—",
            "Flash mode": self.identity.flash_mode_name,
            "Protocol": f"{self.identity.protocol_major}.{self.identity.protocol_minor} (max frame {self.identity.max_frame})",
            "Detail": self.identity.detail or "—",
        }
        if self.controller.device_info:
            info = self.controller.device_info
            items.update(
                {
                    "CPUID": f"0x{int(info.get('cpuid', 0)):08X}",
                    "Flash size": f"{info.get('flash_size_kb', 0)} KB",
                    "Package": info.get("package") or "—",
                    "SYSCLK": f"{int(info.get('sysclk_hz', 0)) / 1e6:.3f} MHz",
                    "HCLK": f"{int(info.get('hclk_hz', 0)) / 1e6:.3f} MHz",
                    "PCLK1 / PCLK2": f"{int(info.get('pclk1_hz', 0)) / 1e6:.1f} / {int(info.get('pclk2_hz', 0)) / 1e6:.1f} MHz",
                    "OPTCR / OPTCR1": f"0x{int(info.get('optcr', 0)):08X} / 0x{int(info.get('optcr1', 0)):08X}",
                    "Reset cause": info.get("reset_cause_text") or f"0x{int(info.get('reset_cause', 0)):08X}",
                    "Uptime": f"{int(info.get('uptime_ms', 0)) / 1000:.0f} s",
                }
            )
        grid.set_items(items)
        layout.addWidget(grid)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _set_baud(self, rate: int) -> None:
        self.baud_actions[rate].setChecked(True)
        if self.identity is not None:
            self.controller.set_baud_async(rate)

    def _swd_info(self) -> None:
        self.show_page("flash")
        self.flash_page.set_busy(True)
        self.controller.read_swd_info()

    def _check_openocd(self) -> None:
        try:
            executable = self.controller.openocd_executable()
            from hwval_studio.firmware.openocd import openocd_version

            self.flash_page.set_openocd(executable, openocd_version(executable))
            self.show_banner(f"OpenOCD found at {executable}")
        except Exception as exc:
            self.flash_page.set_openocd(None)
            self._show_error(str(exc))

    def _read_options(self) -> None:
        self.show_page("flash")
        self.flash_page.set_busy(True)
        self.controller.read_option_bytes()

    def _provision(self) -> None:
        self.show_page("flash")
        if self.flash_page._boot_file():
            self.flash_page.confirm_provision()
        else:
            self.show_banner("Select boot.hex on the Flash (SWD) page, then choose Provision Product Configuration.", error=True)

    def _restore_bench(self) -> None:
        self.show_page("flash")
        self.flash_page.confirm_restore()

    def _restore_requested(self, path: object) -> None:
        self.controller.restore_bench(path if path else None)

    def _start_update(self, image: object, activate: bool) -> None:
        if not self.controller.start_update(image, activate=activate):
            return
        self._update_active = True
        self.update_page.set_busy(True)
        self._update_actions()
        self.activity.set_busy("Updating firmware…", "Preparing upload")

    # -- operator mode -------------------------------------------------
    def _toggle_operator_mode(self, checked: bool) -> None:
        if checked:
            self.enter_operator_mode()
        else:
            self.leave_operator_mode()

    def enter_operator_mode(self) -> None:
        if self._operator_mode:
            return
        self._operator_mode = True
        self.operator_action.blockSignals(True)
        self.operator_action.setChecked(True)
        self.operator_action.blockSignals(False)
        self.operator_page.set_preset(self.preferences.operator_preset)
        self.operator_page.operator_name.clear()
        self.operator_page.operator_name.addItems(self.preferences.operator_names)
        if self.preferences.operator_name:
            self.operator_page.operator_name.setCurrentText(self.preferences.operator_name)
        self.operator_page.set_identity(self.identity)
        self.stack.setCurrentWidget(self.operator_page)
        self.sidebar.hide()
        self.toolbar.hide()
        self.log_console.hide()
        self.statusBar().hide()
        self.banner.hide()
        self.menuBar().setVisible(not is_macos())
        self._update_actions()
        self.setWindowTitle(f"{APP_NAME} — Operator")
        self.operator_page.run_button.setFocus()

    def leave_operator_mode(self) -> None:
        if not self._operator_mode:
            return
        pin = self.preferences.operator_pin
        if pin:
            value, ok = QInputDialog.getText(self, "Exit operator mode", "PIN:", QLineEdit.EchoMode.Password)
            if not ok:
                self.operator_action.blockSignals(True)
                self.operator_action.setChecked(True)
                self.operator_action.blockSignals(False)
                return
            if value != pin:
                self._show_error("The PIN is incorrect.")
                self.operator_action.blockSignals(True)
                self.operator_action.setChecked(True)
                self.operator_action.blockSignals(False)
                return
        self._operator_mode = False
        self.operator_action.blockSignals(True)
        self.operator_action.setChecked(False)
        self.operator_action.blockSignals(False)
        self.sidebar.show()
        self.toolbar.show()
        self.log_console.setVisible(self.preferences.show_log_on_start)
        self.statusBar().show()
        self.menuBar().setVisible(True)
        from hwval_studio import __version__

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.show_page(self.preferences.last_selected_item or "overview")
        self._update_actions()

    def _operator_run(self, operator_name: str) -> None:
        self.preferences.operator_name = operator_name
        if operator_name not in self.preferences.operator_names:
            names = self.preferences.operator_names
            names.append(operator_name)
            self.preferences.operator_names = names
        preset = self.preferences.operator_preset
        selection = Selection(
            all_tests=True,
            levels=preset.levels,
            allow_operator=preset.allow_operator,
            allow_destructive=False,
            repeat=1,
            until_fail=False,
        )
        self._run_selection(selection)

    # -- timers --------------------------------------------------------
    def _start_timers(self) -> None:
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(2000)
        self._ping_timer.timeout.connect(self._ping)
        self._ping_timer.start()
        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(1000)
        self._demo_timer.timeout.connect(self._poll_demo)
        self._demo_timer.start()
        self._retention_timer = QTimer(self)
        self._retention_timer.setSingleShot(True)
        self._retention_timer.timeout.connect(self._apply_retention)
        self._retention_timer.start(1500)
        self._port_timer = QTimer(self)
        self._port_timer.setInterval(2500)
        self._port_timer.timeout.connect(self._poll_ports)
        self._port_timer.start()

    def _poll_ports(self) -> None:
        if self.identity is None and not self._busy:
            self._refresh_ports()

    def _ping(self) -> None:
        if self.identity is None or self._run_active or self._update_active or self._busy:
            return
        self.controller.ping_async()

    def _poll_demo(self) -> None:
        if self.identity is None or self.role != Role.DEMO or self._busy:
            return
        if self.stack.currentWidget() is self.demo_page and self.isVisible():
            self.controller.refresh_demo_status()

    def _apply_retention(self) -> None:
        days = self.preferences.retention_days
        if days <= 0:
            return
        try:
            removed = self.store.purge_older_than(days)
            if removed:
                self.log_console.info(f"retention: removed {removed} old run(s)")
                self.history_page.refresh()
                self.reports_page.refresh()
        except Exception as exc:
            self.log_console.warn(f"retention failed: {exc}")
