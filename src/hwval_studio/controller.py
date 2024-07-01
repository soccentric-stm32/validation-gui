"""Application controller: connection, runs, updates, demo and SWD tasks.

The controller owns the QThread transport and starts short-lived
``TaskThread`` workers for every operation.  No method called from the UI
blocks on I/O; results arrive as Qt signals (ARC-002).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from hwval_studio import __version__
from hwval_studio.config import Preferences
from hwval_studio.core.client import (
    Client,
    DeviceError,
    Identity,
    RunController,
    Selection,
    TestCase,
    TestGroup,
)
from hwval_studio.core.services import BootService, DemoService, HwvalService
from hwval_studio.firmware import FirmwareImage, ImageError, compare_versions, parse_image
from hwval_studio.firmware.openocd import (
    OpenOcdError,
    OpenOcdRunner,
    find_openocd,
    install_hint,
    openocd_version,
    version_supported,
)
from hwval_studio.persistence.database import HistoryStore
from hwval_studio.persistence.reports import export_run
from hwval_studio.protocol.generated.hwlink.Body import Body
from hwval_studio.protocol.generated.hwlink.Role import Role
from hwval_studio.protocol.generated.hwlink.TestVerdict import TestVerdict
from hwval_studio.transport import PortInfo, SerialWorker, list_ports


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[TaskThread], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self.fn(self))
        except Exception as exc:
            self.failed.emit(str(exc))


class StudioController(QObject):
    ports_changed = Signal(object)
    connection_state = Signal(str)
    connected = Signal(object)
    disconnected = Signal(str)
    log = Signal(str, str)
    device_info_ready = Signal(object)
    catalogue_ready = Signal(object, object)
    harness_ready = Signal(object)
    boot_info_ready = Signal(object)
    demo_status_ready = Signal(object)
    status_failed = Signal(str)
    run_active_changed = Signal(bool)
    run_started = Signal(object)
    test_started = Signal(object)
    test_result = Signal(object)
    run_prompt = Signal(object)
    run_prompt_done = Signal(object)
    run_finished = Signal(object)
    run_failed = Signal(str)
    update_state = Signal(str)
    update_progress = Signal(int, int, float)
    update_finished = Signal(object)
    update_failed = Signal(str)
    update_watch = Signal(object)
    swd_output = Signal(str)
    swd_info_ready = Signal(object)
    swd_finished = Signal(str, object)
    swd_failed = Signal(str)
    ping_failed = Signal(int)
    banner = Signal(str)
    button_event = Signal(object)
    serial_bytes = Signal(bytes)
    hlink_frame = Signal(bytes)
    error = Signal(str)
    operation_busy = Signal(bool)

    def __init__(self, preferences: Preferences, store: HistoryStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.preferences = preferences
        self.store = store
        self.worker: SerialWorker | None = None
        self.client: Client | None = None
        self.identity: Identity | None = None
        self.port = ""
        self.role = 0
        self.device_info: dict[str, Any] | None = None
        self.groups: list[TestGroup] = []
        self.tests: list[TestCase] = []
        self.harness: dict[str, Any] = {}
        self.boot_info: dict[str, Any] | None = None
        self.demo_status: dict[str, Any] | None = None
        self._tasks: list[TaskThread] = []
        self._run_controller: RunController | None = None
        self._run_active = False
        self._update_cancel = threading.Event()
        self._update_active = False
        self._swd_active = False
        self._ping_active = False
        self._ping_misses = 0
        self._disconnect_emitted = False

    # -- helpers -------------------------------------------------------
    def _spawn(self, fn: Callable[[TaskThread], Any], on_ok: Callable[[Any], None], on_err: Callable[[str], None]) -> TaskThread:
        task = TaskThread(fn, self)
        task.succeeded.connect(on_ok)
        task.failed.connect(on_err)
        task.finished.connect(lambda: self._forget(task))
        self._tasks.append(task)
        task.start()
        return task

    def _forget(self, task: TaskThread) -> None:
        if task in self._tasks:
            self._tasks.remove(task)

    def _log(self, level: str, text: str) -> None:
        self.log.emit(level, text)

    def refresh_ports(self) -> list[PortInfo]:
        ports = list_ports(include_simulators=True)
        self.ports_changed.emit(ports)
        return ports

    # -- connection ----------------------------------------------------
    def connect_device(self, port: str) -> None:
        if self._run_active or self._update_active or self._swd_active:
            self.error.emit("Finish the active operation before reconnecting.")
            return
        if self.worker is not None:
            self._close_worker()
        self.port = port
        self.preferences.last_port = port
        self._disconnect_emitted = False
        self.connection_state.emit("connecting")
        self.log.emit("INFO", f"opening {port}")
        self.worker = SerialWorker(port)
        self.worker.failed.connect(self._on_worker_failed)
        self.worker.transport_error.connect(self._on_transport_error)
        self.worker.closed.connect(self._on_worker_closed)
        self.worker.raw_bytes.connect(self.serial_bytes.emit)
        self.worker.frame_received.connect(self.hlink_frame.emit)
        self.worker.start()
        self._spawn(
            lambda task: self._connect_task(port),
            self._on_connected,
            self._on_connect_failed,
        )

    def _connect_task(self, port: str) -> dict[str, Any]:
        worker = self.worker
        if worker is None:
            raise DeviceError("transport was closed")
        if not worker.wait_ready(5.0):
            raise DeviceError(worker.open_error or "serial port did not open")
        client = Client(worker, log_handler=self._log)
        identity = client.connect()
        result: dict[str, Any] = {"identity": identity, "client": client}
        if identity.role == Role.HWVAL:
            result["device_info"] = client.get_device_info()
            groups, tests = client.load_catalogue()
            result["groups"] = groups
            result["tests"] = tests
            result["harness"] = client.load_harness()
        elif identity.role == Role.BOOTLOADER:
            result["boot_info"] = client.get_boot_info()
        elif identity.role == Role.DEMO:
            result["demo_status"] = client.get_status()
        return result

    def _on_connected(self, result: dict[str, Any]) -> None:
        client: Client = result["client"]
        identity: Identity = result["identity"]
        self.client = client
        self.identity = identity
        self.role = identity.role
        self.hwval_service = HwvalService(client)
        self.boot_service = BootService(client)
        self.demo_service = DemoService(client)
        if "device_info" in result:
            self.device_info = result.get("device_info")
            # DeviceInfo carries the full 96-bit UID as a hex string; use it
            # for device history and report names instead of the 64 bits in
            # HelloReply.uid.
            full_uid = str(self.device_info.get("uid") or "")
            if full_uid:
                try:
                    identity.uid = int(full_uid, 16)
                    identity.uid_hex = full_uid.upper()
                except ValueError:
                    pass
        if "groups" in result:
            self.groups = result.get("groups") or []
            self.tests = result.get("tests") or []
        if "harness" in result:
            self.harness = result.get("harness") or {}
        if "boot_info" in result:
            self.boot_info = result.get("boot_info")
        if "demo_status" in result:
            self.demo_status = self._fill_demo_identity(result.get("demo_status") or {})
        try:
            self.store.record_device(identity.uid_hex, identity.dev_id, identity.rev_id)
            if self.groups:
                self.store.save_catalogue(identity.version, [asdict(test) for test in self.tests])
        except Exception as exc:
            self.log.emit("WARN", f"could not record device/catalogue: {exc}")
        self.connection_state.emit("connected")
        self.connected.emit(identity)
        self.banner.emit(f"Connected to {identity.role_name} {identity.firmware_name} {identity.version}")
        self.log.emit("INFO", f"identified {identity.role_name} {identity.firmware_name} {identity.version} ({identity.uid_hex})")
        if self.device_info:
            self.device_info_ready.emit(self.device_info)
        if self.groups:
            self.catalogue_ready.emit(self.groups, self.tests)
        if self.harness:
            self.harness_ready.emit(self.harness)
        if self.boot_info:
            self.boot_info_ready.emit(self.boot_info)
        if self.demo_status:
            self.demo_status_ready.emit(self.demo_status)

    def _on_connect_failed(self, message: str) -> None:
        self.connection_state.emit("disconnected")
        self.log.emit("ERROR", f"connect failed: {message}")
        if self.worker is not None:
            self._close_worker()
        self.error.emit(message)

    def _on_worker_failed(self, message: str) -> None:
        self._log("ERROR", f"transport: {message}")
        if not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.connection_state.emit("disconnected")
            self.disconnected.emit(message)

    def _on_transport_error(self, message: str) -> None:
        self._log("ERROR", f"transport: {message}")
        if self.identity is not None and not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.connection_state.emit("link lost")
            self.disconnected.emit(message)

    def _on_worker_closed(self) -> None:
        if self.identity is not None and not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.connection_state.emit("disconnected")
            self.disconnected.emit("serial transport closed")

    def wait_for_tasks(self, timeout_ms: int = 10000) -> None:
        """Let running worker tasks finish so Qt does not destroy a thread.

        Call after disconnect_device(), which asks the run/update loops to
        stop.  terminate() is a last resort: it is only reached if a task
        ignored the 10 s deadline, and it avoids Qt aborting the process.
        """
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        for task in list(self._tasks):
            remaining = max(0.0, deadline - time.monotonic())
            if not task.wait(int(remaining * 1000)):
                self.log.emit("WARN", "a worker task did not stop; terminating it")
                task.terminate()
                task.wait(1000)
        self._tasks.clear()

    def disconnect_device(self) -> None:
        if self._run_active:
            self.abort_run()
        self._update_cancel.set()
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self._close_worker()
        self.client = None
        self.identity = None
        self.role = 0
        self.device_info = None
        self.groups = []
        self.tests = []
        self.harness = {}
        self.boot_info = None
        self.demo_status = None
        if not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.connection_state.emit("disconnected")
            self.disconnected.emit("")
        self.log.emit("INFO", "disconnected")

    def _close_worker(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            try:
                worker.close()
            except Exception:
                pass

    def _restart_worker(self, timeout: float = 8.0) -> None:
        port = self.port
        if not port:
            raise DeviceError("no port selected")
        worker = SerialWorker(port)
        worker.failed.connect(self._on_worker_failed)
        worker.transport_error.connect(self._on_transport_error)
        worker.closed.connect(self._on_worker_closed)
        worker.raw_bytes.connect(self.serial_bytes.emit)
        worker.frame_received.connect(self.hlink_frame.emit)
        worker.start()
        self.worker = worker
        if not worker.wait_ready(timeout):
            raise DeviceError(worker.open_error or f"could not reopen {port}")

    def _reconnect(self, expected_role: int, attempts: int = 20) -> Client:
        last: Exception | None = None
        for _ in range(attempts):
            try:
                if self.worker is None or not self.worker.is_open:
                    self._restart_worker()
                    self.client = None
                if self.client is None:
                    if self.worker is None:
                        raise DeviceError("transport unavailable")
                    self.client = Client(self.worker, log_handler=self._log)
                self.client.connect(expected_role=expected_role)
                self.identity = self.client.identity
                self.role = expected_role
                if self.identity is not None:
                    self.connected.emit(self.identity)
                return self.client
            except Exception as exc:
                last = exc
                time.sleep(0.25)
        raise DeviceError(f"could not reconnect as {expected_role}: {last}")

    @staticmethod
    def _file_sha256(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return ""

    def _fill_demo_identity(self, status: dict[str, Any]) -> dict[str, Any]:
        """Status omits the identity strings; HelloReply already has them."""
        identity = self.identity
        if identity is not None:
            for key, value in (
                ("firmware_name", identity.firmware_name),
                ("version", identity.version),
                ("commit", identity.commit),
                ("build_time", identity.build_time),
            ):
                if not status.get(key):
                    status[key] = value
        return status

    def _reopen_serial(self) -> dict[str, Any]:
        """Reopen the VCP, identify the device and refresh its role data."""
        self._restart_worker()
        if self.client is None and self.worker is not None:
            self.client = Client(self.worker, log_handler=self._log)
        if self.client is None:
            raise DeviceError("transport unavailable")
        client = self.client
        identity = client.connect()
        result: dict[str, Any] = {"identity": identity, "client": client}
        # The role (and therefore its data) can change after an SWD
        # operation; do not leave the previous catalogue/BootInfo/Status
        # on screen.
        if identity.role == Role.HWVAL:
            result["device_info"] = client.get_device_info()
            result["groups"], result["tests"] = client.load_catalogue()
            result["harness"] = client.load_harness()
        elif identity.role == Role.BOOTLOADER:
            result["boot_info"] = client.get_boot_info()
        elif identity.role == Role.DEMO:
            result["demo_status"] = client.get_status()
        return result

    def enter_text_mode(self) -> None:
        if self.client is None:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.enter_text_mode()
            return True

        self._spawn(task, lambda _: self.banner.emit("Device switched to the text CLI"), self.error.emit)

    def write_serial(self, data: bytes) -> None:
        if self.worker is None:
            raise DeviceError("no serial connection")
        self.worker.write(data)

    def set_baud_async(self, rate: int) -> None:
        if self.client is None:
            return

        def task(_task: TaskThread) -> int:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.set_baud(rate)
            if self.worker is not None:
                self.worker.change_baud(rate)
            return rate

        def ok(rate: int) -> None:
            self.banner.emit(f"Link switched to {rate} baud")
            self.log.emit("INFO", f"baud rate changed to {rate}")

        self._spawn(task, ok, self.error.emit)

    # -- ping / link health -------------------------------------------
    def ping_async(self) -> None:
        if self._ping_active or self.client is None or self._run_active or self._update_active:
            return
        self._ping_active = True

        def ping(_task: TaskThread) -> bool:
            if self.client is None:
                return False
            self.client.ping()
            return True

        def ok(_result: bool) -> None:
            self._ping_active = False
            self._ping_misses = 0

        def fail(message: str) -> None:
            self._ping_active = False
            self._ping_misses += 1
            self.ping_failed.emit(self._ping_misses)
            self.log.emit("WARN", f"ping failed ({self._ping_misses}): {message}")
            if self._ping_misses >= 3 and not self._disconnect_emitted:
                self._disconnect_emitted = True
                self.connection_state.emit("link lost")
                self.disconnected.emit("no ping reply after 3 attempts")

        self._spawn(ping, ok, fail)

    # -- HWVAL run -----------------------------------------------------
    def _recover_run(self, run_id: int, reason: str) -> None:
        def task(_task: TaskThread) -> dict[str, Any]:
            self._reconnect(Role.HWVAL, attempts=30)
            if self.client is None:
                raise DeviceError("not connected")
            fetched = self.client.get_results()
            return {"results": fetched}

        def ok(payload: dict[str, Any]) -> None:
            results = payload.get("results") or []
            try:
                self.store.clear_results(run_id)
                for result in results:
                    self.store.add_result(run_id, result)
            except Exception as exc:
                self.log.emit("WARN", f"could not refresh history after reset: {exc}")
            verdicts = [int(r.get("result", 3)) for r in results]
            summary = {
                "total": len(results),
                "pass": verdicts.count(TestVerdict.PASS),
                "fail": verdicts.count(TestVerdict.FAIL),
                "skip": verdicts.count(TestVerdict.SKIP),
                "na": verdicts.count(TestVerdict.NA),
                "aborted": False,
                "resumed": True,
            }
            counts = {"pass": summary["pass"], "fail": summary["fail"], "skip": summary["skip"], "na": summary["na"]}
            try:
                self.store.finish_run(
                    run_id,
                    status="COMPLETE",
                    overall="FAIL" if summary["fail"] else "PASS",
                    n_pass=summary["pass"],
                    n_fail=summary["fail"],
                    n_skip=summary["skip"],
                    n_na=summary["na"],
                )
            except Exception:
                pass
            self._run_active = False
            self._run_controller = None
            self.run_active_changed.emit(False)
            self.connection_state.emit("connected")
            self.update_state.emit("idle")
            for result in results:
                self.test_result.emit(result)
            self.run_finished.emit(
                {
                    "run_id": run_id,
                    "summary": summary,
                    "results": results,
                    "overall": "FAIL" if summary["fail"] else "PASS",
                    "counts": counts,
                }
            )
            self.banner.emit("Device reset during the run; results were recovered with GetResults")

        def failed(message: str) -> None:
            self._run_active = False
            self._run_controller = None
            self.run_active_changed.emit(False)
            self.connection_state.emit("disconnected")
            self.log.emit("ERROR", f"run recovery failed: {message}")
            try:
                self.store.finish_run(run_id, status="INCOMPLETE", overall="FAIL", n_pass=0, n_fail=0, n_skip=0, n_na=0)
            except Exception:
                pass
            self.run_failed.emit(f"{reason}; recovery failed: {message}")

        self._spawn(task, ok, failed)

    def start_run(
        self,
        selection: Selection,
        *,
        mode: str = "ENGINEER",
        operator_name: str = "",
        record_history: bool = True,
    ) -> int:
        if self.client is None or self.role != Role.HWVAL:
            self.error.emit("Select a HWVAL device before running tests.")
            return 0
        if self._run_active:
            self.error.emit("A run is already active.")
            return 0
        if self._update_active or self._swd_active:
            self.error.emit("A firmware operation is active.")
            return 0
        identity = self.identity
        run_id = 0
        if record_history and identity is not None:
            run_id = self.store.start_run(
                uid=identity.uid_hex,
                fw_name=identity.firmware_name,
                fw_version=identity.version,
                fw_commit=identity.commit,
                gui_version=__version__,
                mode=mode,
                operator_name=operator_name,
                selection=selection.to_dict(),
            )
        self._run_active = True
        self.run_active_changed.emit(True)
        self.connection_state.emit("running")
        self.update_state.emit("running")

        def on_event(body_type: int, data: dict[str, Any]) -> None:
            if body_type == Body.RunStarted:
                self.run_started.emit(data)
            elif body_type == Body.TestStarted:
                self.test_started.emit(data)
            elif body_type == Body.TestResult:
                if run_id:
                    try:
                        self.store.add_result(run_id, data)
                    except Exception as exc:
                        self.log.emit("WARN", f"could not store result: {exc}")
                self.test_result.emit(data)
            elif body_type == Body.OperatorPrompt:
                self.run_prompt.emit(data)
            elif body_type == Body.OperatorPromptDone:
                self.run_prompt_done.emit(data)
            elif body_type == Body.ButtonEvent:
                self.button_event.emit(data)
            elif body_type == Body.Progress:
                total = int(data.get("total", 0))
                done = int(data.get("done", 0))
                if total:
                    self.update_progress.emit(done, total, 0.0)

        def task(worker_task: TaskThread) -> dict[str, Any]:
            if self.client is None:
                raise DeviceError("not connected")
            run = self.client.start_run(selection, on_event=on_event, on_log=self._log)
            self._run_controller = run
            run.start()
            summary = run.pump()
            return {"summary": summary, "results": run.results, "run_id": run_id}

        def ok(result: dict[str, Any]) -> None:
            self._run_active = False
            self._run_controller = None
            self.run_active_changed.emit(False)
            self.connection_state.emit("connected")
            self.update_state.emit("idle")
            summary = result["summary"]
            results = result["results"]
            run_id = int(result["run_id"])
            verdicts = [int(r.get("result", 3)) for r in results]
            counts = {
                "pass": int(summary.get("pass", verdicts.count(TestVerdict.PASS))),
                "fail": int(summary.get("fail", verdicts.count(TestVerdict.FAIL))),
                "skip": int(summary.get("skip", verdicts.count(TestVerdict.SKIP))),
                "na": int(summary.get("na", verdicts.count(TestVerdict.NA))),
            }
            if run_id:
                status = "ABORTED" if summary.get("aborted") else "COMPLETE"
                overall = "FAIL" if counts["fail"] else "PASS"
                try:
                    self.store.finish_run(
                        run_id,
                        status=status,
                        overall=overall,
                        n_pass=counts["pass"],
                        n_fail=counts["fail"],
                        n_skip=counts["skip"],
                        n_na=counts["na"],
                    )
                except Exception as exc:
                    self.log.emit("WARN", f"could not finish history run: {exc}")
                if mode == "OPERATOR" and self.preferences.operator_auto_export:
                    folder = self.preferences.auto_export_folder
                    if folder:
                        try:
                            export_run(self.store, run_id, folder)
                            self.log.emit("INFO", f"report exported to {folder}")
                        except Exception as exc:
                            self.log.emit("WARN", f"automatic report export failed: {exc}")
            self.run_finished.emit(
                {
                    "run_id": run_id,
                    "summary": summary,
                    "results": results,
                    "overall": "FAIL" if counts["fail"] else "PASS",
                    "counts": counts,
                }
            )

        def fail(message: str) -> None:
            if run_id and self.client is not None and ("timeout" in message.lower() or "stalled" in message.lower() or "link" in message.lower()):
                self.log.emit("WARN", f"run interrupted ({message}); reconnecting and reading results")
                self._recover_run(run_id, message)
                return
            self._run_active = False
            self._run_controller = None
            self.run_active_changed.emit(False)
            self.connection_state.emit("connected")
            self.update_state.emit("idle")
            self.log.emit("ERROR", f"run failed: {message}")
            if run_id:
                try:
                    self.store.finish_run(
                        run_id, status="INCOMPLETE", overall="FAIL", n_pass=0, n_fail=0, n_skip=0, n_na=0
                    )
                except Exception:
                    pass
            self.run_failed.emit(message)

        self._spawn(task, ok, fail)
        return run_id

    def answer_prompt(self, prompt_id: int, answer: str) -> None:
        if self._run_controller is not None:
            self._run_controller.answer(prompt_id, answer)

    def abort_run(self) -> None:
        if self._run_controller is not None:
            self._run_controller.abort()
            self.connection_state.emit("aborting")
            self.update_state.emit("aborting")
            self.log.emit("WARN", "abort requested; waiting for RunFinished")

    # -- HWVAL data ----------------------------------------------------
    def refresh_device_info(self) -> None:
        if self.client is None or self.role != Role.HWVAL:
            return

        def task(_task: TaskThread) -> dict[str, Any]:
            if self.client is None:
                raise DeviceError("not connected")
            return self.client.get_device_info()

        self._spawn(task, self.device_info_ready.emit, self.status_failed.emit)

    def refresh_harness(self) -> None:
        if self.client is None or self.role != Role.HWVAL:
            return

        def task(_task: TaskThread) -> dict[str, Any]:
            if self.client is None:
                raise DeviceError("not connected")
            return self.client.load_harness()

        def ok(data: dict[str, Any]) -> None:
            self.harness = data
            self.harness_ready.emit(data)

        self._spawn(task, ok, self.status_failed.emit)

    def fetch_results(self) -> None:
        if self.client is None or self.role != Role.HWVAL:
            return

        def task(_task: TaskThread) -> list[dict[str, Any]]:
            if self.client is None:
                raise DeviceError("not connected")
            return self.client.get_results()

        self._spawn(task, lambda data: self.banner.emit(f"Read {len(data)} result(s) from the device"), self.status_failed.emit)

    def clear_results(self) -> None:
        if self.client is None or self.role != Role.HWVAL:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.clear_results()
            return True

        self._spawn(task, lambda _: self.banner.emit("Device results cleared"), self.status_failed.emit)

    def reset_device(self) -> None:
        if self.client is None:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.reset()
            return True

        self._spawn(task, lambda _: self.banner.emit("Reset requested"), self.error.emit)

    # -- BOOT / firmware update ---------------------------------------
    def start_update(self, image: FirmwareImage | str | Path, *, activate: bool = True) -> bool:
        if self._run_active:
            self.error.emit("Abort the active run before updating firmware.")
            return False
        if self._swd_active:
            self.error.emit("An SWD operation is active.")
            return False
        if self._update_active:
            self.error.emit("An update is already active.")
            return False
        if self.client is None:
            self.error.emit("Connect to a device before updating firmware.")
            return False
        if self.role == Role.HWVAL:
            self.error.emit(
                "HWVAL is running in the bench configuration (single-bank). "
                "UART update needs the product configuration; use Tools > Provision Product Configuration."
            )
            return False
        try:
            parsed = image if isinstance(image, FirmwareImage) else parse_image(image)
        except ImageError as exc:
            self.error.emit(str(exc))
            return False
        warnings = list(parsed.warnings)
        if self.boot_info:
            active = next(
                (slot for slot in self.boot_info.get("slots", []) if slot.get("slot") == self.boot_info.get("active_slot")),
                None,
            )
            if active:
                warnings.extend(compare_versions(parsed, active))
        self._update_active = True
        self._update_cancel.clear()
        self.update_state.emit("updating")
        self.connection_state.emit("updating")
        self.operation_busy.emit(True)

        def progress(done: int, total: int, speed: float) -> None:
            self.update_progress.emit(done, total, speed)

        def task(_task: TaskThread) -> dict[str, Any]:
            if self.client is None:
                raise DeviceError("not connected")
            if self.role == Role.DEMO:
                self.update_state.emit("entering bootloader")
                self.client.enter_bootloader()
                time.sleep(0.4)
                self._reconnect(Role.BOOTLOADER, attempts=30)
            if self.role != Role.BOOTLOADER:
                raise DeviceError("device is not in BOOTLOADER mode")
            switched_baud = False
            if self.preferences.fast_baud:
                try:
                    self.client.set_baud(921600)
                    if self.worker is not None:
                        self.worker.change_baud(921600)
                    switched_baud = True
                    self.log.emit("INFO", "bulk transfer at 921600 baud")
                except Exception as exc:
                    self.log.emit("WARN", f"could not switch to 921600 baud: {exc}")
            self.update_state.emit("uploading")
            try:
                result = self.client.update_image(
                    parsed,
                    activate=activate,
                    progress=progress,
                    cancel=self._update_cancel,
                )
            finally:
                if switched_baud and self.client is not None:
                    try:
                        self.client.set_baud(115200)
                        if self.worker is not None:
                            self.worker.change_baud(115200)
                    except Exception:
                        pass
            watch: dict[str, Any] = {}
            if activate:
                self.update_state.emit("waiting for confirmation")
                try:
                    self._reconnect(Role.DEMO, attempts=40)
                    deadline = time.monotonic() + 60.0
                    while time.monotonic() < deadline:
                        if self._update_cancel.is_set():
                            break
                        status = self.client.get_status()
                        watch = status
                        if status.get("trial_name") == "CONFIRMED":
                            break
                        if status.get("trial_name") == "PENDING":
                            time.sleep(1.0)
                            continue
                        time.sleep(1.0)
                except Exception as exc:
                    watch = {"error": str(exc)}
            return {"result": result, "watch": watch, "warnings": warnings}

        def ok(payload: dict[str, Any]) -> None:
            self._update_active = False
            self.operation_busy.emit(False)
            self.update_state.emit("idle")
            self.connection_state.emit("connected")
            result = payload["result"]
            watch = payload["watch"]
            outcome = "OK"
            if watch.get("trial_name") == "PENDING":
                outcome = "ROLLED_BACK"
            try:
                self.store.record_firmware_op(
                    kind="UART_UPDATE",
                    outcome=outcome,
                    uid=self.identity.uid_hex if self.identity else "",
                    file_name=parsed.path.name,
                    file_sha256=parsed.sha256,
                    image_name=parsed.name,
                    image_version=parsed.version_text,
                    slot=str(self.boot_info.get("active_slot_name", "")) if self.boot_info else "",
                    detail=f"crc=0x{int(result.get('image_crc32', 0)):08X}; watch={watch}",
                )
            except Exception as exc:
                self.log.emit("WARN", f"could not record firmware operation: {exc}")
            self.update_finished.emit(
                {"result": result, "watch": watch, "image": parsed, "warnings": payload["warnings"]}
            )
            self.banner.emit(f"Firmware update finished: {parsed.name} {parsed.version_text}")
            self._refresh_boot_async()

        def fail(message: str) -> None:
            self._update_active = False
            self.operation_busy.emit(False)
            self.update_state.emit("idle")
            self.connection_state.emit("connected")
            cancelled = "cancelled" in message.lower()
            try:
                self.store.record_firmware_op(
                    kind="UART_UPDATE",
                    outcome="CANCELLED" if cancelled else "FAILED",
                    uid=self.identity.uid_hex if self.identity else "",
                    file_name=parsed.path.name,
                    file_sha256=parsed.sha256,
                    image_name=parsed.name,
                    image_version=parsed.version_text,
                    slot="",
                    detail=message,
                )
            except Exception:
                pass
            self.log.emit("ERROR", f"update failed: {message}")
            self.update_failed.emit(message)

        self._spawn(task, ok, fail)
        return True

    def cancel_update(self) -> None:
        self._update_cancel.set()
        self.update_state.emit("cancelling")
        self.log.emit("WARN", "update cancellation requested")

    def _refresh_boot_async(self) -> None:
        if self.client is None or self.role != Role.BOOTLOADER:
            return

        def task(_task: TaskThread) -> dict[str, Any]:
            if self.client is None:
                raise DeviceError("not connected")
            return self.client.get_boot_info()

        def ok(info: dict[str, Any]) -> None:
            self.boot_info = info
            self.boot_info_ready.emit(info)

        self._spawn(task, ok, lambda message: self.log.emit("WARN", f"boot info: {message}"))

    def refresh_boot_info(self) -> None:
        if self.client is None or self.role != Role.BOOTLOADER:
            return

        def task(_task: TaskThread) -> dict[str, Any]:
            if self.client is None:
                raise DeviceError("not connected")
            return self.client.get_boot_info()

        def ok(info: dict[str, Any]) -> None:
            self.boot_info = info
            self.boot_info_ready.emit(info)

        self._spawn(task, ok, self.status_failed.emit)

    def activate_pending(self) -> None:
        if self.client is None or self.role != Role.BOOTLOADER:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.activate()
            # ARC-002: the wait and the reconnect belong to the worker, not
            # to the UI thread.
            time.sleep(0.5)
            try:
                self._reconnect(Role.DEMO, attempts=20)
            except Exception as exc:
                self.log.emit("WARN", f"could not reconnect after activate: {exc}")
            return True

        def ok(_result: bool) -> None:
            self.banner.emit("Activate sent; the device is resetting")

        self._spawn(task, ok, self.error.emit)

    def enter_bootloader(self) -> None:
        if self.client is None or self.role != Role.DEMO:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.enter_bootloader()
            time.sleep(0.4)
            self._reconnect(Role.BOOTLOADER, attempts=30)
            return True

        def ok(_result: bool) -> None:
            self.role = Role.BOOTLOADER
            self.banner.emit("Device is in the bootloader")
            self._refresh_boot_async()

        self._spawn(task, ok, self.error.emit)

    # -- demo ----------------------------------------------------------
    def refresh_demo_status(self) -> None:
        if self.client is None or self.role != Role.DEMO:
            return
        if self._demo_poll_active:
            return
        self._demo_poll_active = True

        def task(_task: TaskThread) -> dict[str, Any]:
            if self.client is None:
                raise DeviceError("not connected")
            return self.client.get_status()

        def ok(status: dict[str, Any]) -> None:
            self._demo_poll_active = False
            status = self._fill_demo_identity(status)
            self.demo_status = status
            self.demo_status_ready.emit(status)
            if self.client is not None:
                from hwval_studio.protocol import codec

                for event in self.client.drain_events():
                    if event.body_type == Body.ButtonEvent:
                        self.button_event.emit(codec.parse_button_event(event.table))

        def fail(message: str) -> None:
            self._demo_poll_active = False
            if "not connected" not in message:
                self.log.emit("WARN", f"status poll failed: {message}")

        self._spawn(task, ok, fail)

    _demo_poll_active = False

    def set_led(self, led: int, pattern: int, period_ms: int) -> None:
        if self.client is None or self.role != Role.DEMO:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.set_led(led, pattern, period_ms)
            return True

        self._spawn(task, lambda _: self.refresh_demo_status(), self.status_failed.emit)

    def set_led_all(self, pattern: int, period_ms: int) -> None:
        if self.client is None or self.role != Role.DEMO:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.set_led_all(pattern, period_ms)
            return True

        self._spawn(task, lambda _: self.refresh_demo_status(), self.status_failed.emit)

    def clear_fault(self) -> None:
        if self.client is None or self.role != Role.DEMO:
            return

        def task(_task: TaskThread) -> bool:
            if self.client is None:
                raise DeviceError("not connected")
            self.client.clear_fault()
            return True

        self._spawn(task, lambda _: self.refresh_demo_status(), self.status_failed.emit)

    # -- SWD / OpenOCD -------------------------------------------------
    def openocd_executable(self) -> str:
        path = find_openocd(self.preferences.openocd_path)
        if not path:
            raise OpenOcdError("OpenOCD was not found.\n\n" + install_hint())
        try:
            version = openocd_version(path)
        except OpenOcdError as exc:
            raise OpenOcdError(
                f"cannot determine the OpenOCD version: {exc}\n\n" + install_hint()
            ) from exc
        if not version_supported(version):
            raise OpenOcdError(f"OpenOCD {version} is too old (>= 0.12 required).\n\n" + install_hint())
        return path

    def check_openocd(self) -> None:
        try:
            path = self.openocd_executable()
            version = openocd_version(path)
            self.banner.emit(f"OpenOCD {version} found at {path}")
        except OpenOcdError as exc:
            self.error.emit(str(exc))

    def _begin_swd(self, operation: str) -> bool:
        if self._swd_active:
            self.swd_failed.emit("An SWD operation is already running.")
            return False
        if self._run_active:
            self.swd_failed.emit("Abort the active run before using SWD.")
            return False
        self._swd_active = True
        self.operation_busy.emit(True)
        self.update_state.emit(f"swd:{operation}")
        return True

    def _finish_swd(self) -> None:
        self._swd_active = False
        self.operation_busy.emit(False)
        self.update_state.emit("idle")

    def _swd_task(
        self,
        operation: str,
        fn: Callable[[OpenOcdRunner, TaskThread], dict[str, Any]],
        *,
        record: tuple[str, str, str, str, str] | None = None,
    ) -> None:
        if not self._begin_swd(operation):
            return
        # SWD-008: close the serial link before the target is reset.
        serial_was_open = self.worker is not None
        if serial_was_open:
            self._close_worker()
            self.client = None

        reopened: dict[str, Any] = {}

        def task(worker_task: TaskThread) -> dict[str, Any]:
            executable = self.openocd_executable()
            runner = OpenOcdRunner(executable=executable, log=self.swd_output.emit)
            try:
                return fn(runner, worker_task)
            finally:
                runner.stop()
                # ARC-002: reopening the VCP can wait for the ST-LINK and
                # reconnect for seconds, so it runs here, not in a UI slot.
                if serial_was_open:
                    try:
                        reopened.update(self._reopen_serial())
                    except Exception as exc:
                        self.log.emit("WARN", f"could not reopen serial link: {exc}")

        def ok(result: dict[str, Any]) -> None:
            self._finish_swd()
            if reopened:
                self._on_connected(reopened)
            self.swd_finished.emit(operation, result)
            self.banner.emit(f"{operation} completed")
            if record:
                kind, file_name, sha, image_name, image_version = record
                try:
                    self.store.record_firmware_op(
                        kind=kind,
                        outcome="OK",
                        file_name=file_name,
                        file_sha256=sha,
                        image_name=image_name,
                        image_version=image_version,
                        detail=str(result.get("output", ""))[-1000:],
                    )
                except Exception:
                    pass

        def fail(message: str) -> None:
            self._finish_swd()
            if reopened:
                self._on_connected(reopened)
            self.swd_failed.emit(message)
            self.log.emit("ERROR", f"{operation} failed: {message}")
            if record:
                kind, file_name, sha, image_name, image_version = record
                try:
                    self.store.record_firmware_op(
                        kind=kind,
                        outcome="FAILED",
                        file_name=file_name,
                        file_sha256=sha,
                        image_name=image_name,
                        image_version=image_version,
                        detail=message,
                    )
                except Exception:
                    pass

        self._spawn(task, ok, fail)

    def read_swd_info(self) -> None:
        self._swd_task("Read option bytes", lambda runner, _task: runner.read_info())

    def flash_hwval(self, image: str | Path) -> None:
        path = Path(image)

        def run(runner: OpenOcdRunner, _task: TaskThread) -> dict[str, Any]:
            return runner.flash_hwval(path)

        self._swd_task(
            "Flash HWVAL",
            run,
            record=("SWD_FLASH", path.name, self._file_sha256(path), "HWVAL", ""),
        )

    def provision_product(self, boot_image: str | Path) -> None:
        path = Path(boot_image)

        def run(runner: OpenOcdRunner, _task: TaskThread) -> dict[str, Any]:
            return runner.provision_product(path)

        self._swd_task(
            "Provision product configuration",
            run,
            record=("PROVISION", path.name, self._file_sha256(path), "BOOT", ""),
        )

    def restore_bench(self, hwval_image: str | Path | None = None) -> None:
        path = Path(hwval_image) if hwval_image else None

        def run(runner: OpenOcdRunner, _task: TaskThread) -> dict[str, Any]:
            return runner.restore_bench(path)

        file_name = path.name if path else ""
        self._swd_task(
            "Restore bench configuration",
            run,
            record=("RESTORE_BENCH", file_name, self._file_sha256(path) if path else "", "HWVAL", ""),
        )

    def read_option_bytes(self) -> None:
        def run(runner: OpenOcdRunner, _task: TaskThread) -> dict[str, Any]:
            options = runner.read_option_bytes()
            return {"options": options.as_dict(), "output": runner.output}

        self._swd_task("Read option bytes", run)
