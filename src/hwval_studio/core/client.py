"""High-level, Qt-free HWLINK client used by the GUI and the CLI."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hwval_studio import PROTOCOL_MAJOR, PROTOCOL_MINOR, __version__
from hwval_studio.protocol import codec
from hwval_studio.protocol.generated.hwlink.Body import Body
from hwval_studio.protocol.generated.hwlink.Role import Role
from hwval_studio.protocol.generated.hwlink.TestVerdict import TestVerdict
from hwval_studio.protocol.link import (
    LinkError,
    LinkSession,
    LinkTimeout,
    ProtocolError,
    SessionConfig,
    Transport,
)


class DeviceError(RuntimeError):
    """The device reported an error or is in the wrong state."""


class VersionMismatch(DeviceError):
    def __init__(self, host: int, device: int, message: str = "") -> None:
        self.host = host
        self.device = device
        super().__init__(message or f"protocol major mismatch: host {host}, device {device}")


@dataclass(slots=True)
class Identity:
    role: int
    role_name: str
    firmware_name: str
    version: str
    commit: str
    build_time: str
    uid: int
    uid_hex: str
    dev_id: int
    rev_id: int
    flash_mode: int
    flash_mode_name: str
    protocol_major: int
    protocol_minor: int
    max_frame: int
    detail: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TestCase:
    id: str
    group: str
    title: str
    level: int
    level_name: str
    operator: bool
    destructive: bool
    timeout_ms: int
    needs: str
    reqs: str


@dataclass(slots=True)
class TestGroup:
    code: str
    name: str
    test_count: int
    category: str = "Other Peripherals"


@dataclass(slots=True)
class Selection:
    ids: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    all_tests: bool = False
    levels: str = "L,S,E"
    allow_operator: bool = True
    allow_destructive: bool = False
    repeat: int = 1
    until_fail: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ids": self.ids,
            "groups": self.groups,
            "all": self.all_tests,
            "levels": self.levels,
            "allow_operator": self.allow_operator,
            "allow_destructive": self.allow_destructive,
            "repeat": self.repeat,
            "until_fail": self.until_fail,
        }

    def describe(self) -> str:
        if self.ids:
            return ", ".join(self.ids)
        if self.groups:
            return "groups: " + ", ".join(self.groups)
        return "all tests"


EventCallback = Callable[[int, dict[str, Any]], None]
LogCallback = Callable[[str, str], None]


class RunController:
    """Drives one HWVAL run and lets the UI answer prompts or abort.

    The controller is owned by a worker thread.  ``answer`` and ``abort`` are
    thread-safe and are serviced between event reads.
    """

    def __init__(
        self,
        client: Client,
        selection: Selection,
        *,
        on_event: EventCallback | None = None,
        on_log: LogCallback | None = None,
    ) -> None:
        self.client = client
        self.selection = selection
        self.on_event_cb = on_event
        self.on_log = on_log
        self.results: list[dict[str, Any]] = []
        self.summary: dict[str, Any] = {}
        self.aborted = False
        self.finished = False
        self.started = False
        self._answers: queue.Queue[tuple[int, str]] = queue.Queue()
        self._starts: dict[str, int] = {}
        self._abort_requested = threading.Event()
        self._stop = threading.Event()

    # -- callbacks -----------------------------------------------------
    def _emit(self, body_type: int, data: dict[str, Any]) -> None:
        if self.on_event_cb:
            self.on_event_cb(body_type, data)

    def _log(self, level: str, text: str) -> None:
        if self.on_log:
            self.on_log(level, text)

    # -- control from the UI ------------------------------------------
    def answer(self, prompt_id: int, answer: str) -> None:
        self._answers.put((prompt_id, answer))

    def abort(self) -> None:
        self._abort_requested.set()

    def stop(self) -> None:
        self._stop.set()

    # -- run loop ------------------------------------------------------
    def start(self) -> dict[str, Any]:
        payload = codec.build_run(
            ids=self.selection.ids,
            groups=self.selection.groups,
            all_tests=self.selection.all_tests,
            levels=self.selection.levels,
            allow_operator=self.selection.allow_operator,
            allow_destructive=self.selection.allow_destructive,
            repeat=self.selection.repeat,
            until_fail=self.selection.until_fail,
        )
        body_type, table = self.client.session.request(payload, response_types={Body.Ack}, timeout=2.0)
        self.started = True
        self._log("INFO", f"run started: {self.selection.describe()}")
        return {"ack": codec.parse_ack(table)}

    def pump(self) -> dict[str, Any]:
        """Process events until RunFinished; returns the summary."""
        if not self.started:
            self.start()
        session = self.client.session
        last_event = time.monotonic()
        while not self.finished and not self._stop.is_set():
            self._service_control()
            try:
                event = session.wait_event(0.1)
                last_event = time.monotonic()
            except LinkTimeout:
                if time.monotonic() - last_event > 20.0:
                    raise LinkTimeout("run stalled: no event or progress for 20 s") from None
                continue
            except (ProtocolError, LinkError) as exc:
                self._log("WARN", f"link error during run: {exc}")
                continue
            body_type = event.body_type
            table = event.table
            if body_type == Body.RunStarted:
                data = codec.parse_run_started(table)
                self._emit(body_type, data)
            elif body_type == Body.TestStarted:
                data = codec.parse_test_started(table)
                test_id = str(data.get("id", ""))
                self._starts[test_id] = self._starts.get(test_id, 0) + 1
                self._emit(body_type, data)
            elif body_type == Body.TestResult:
                data = codec.parse_test_result(table)
                data["iteration"] = self._starts.get(str(data.get("id", "")), 1)
                self.results.append(data)
                self._emit(body_type, data)
            elif body_type == Body.OperatorPrompt:
                data = codec.parse_operator_prompt(table)
                self._emit(body_type, data)
            elif body_type == Body.OperatorPromptDone:
                self._emit(body_type, codec.parse_operator_prompt_done(table))
            elif body_type == Body.RunFinished:
                self.summary = codec.parse_run_finished(table)
                self.finished = True
                self._emit(body_type, self.summary)
            elif body_type == Body.Progress:
                self._emit(body_type, codec.parse_progress(table))
            elif body_type == Body.ButtonEvent:
                self._emit(body_type, codec.parse_button_event(table))
            elif body_type == Body.Log:
                data = codec.parse_log(table)
                self._log(data["level_name"], data["text"])
        if self._stop.is_set() and not self.finished:
            try:
                self.client.session.request(codec.build_abort(), response_types={Body.Ack}, timeout=1.0)
            except LinkError:
                pass
        if not self.summary:
            verdicts = [int(r.get("result", 3)) for r in self.results]
            self.summary = {
                "total": len(self.results),
                "pass": verdicts.count(TestVerdict.PASS),
                "fail": verdicts.count(TestVerdict.FAIL),
                "skip": verdicts.count(TestVerdict.SKIP),
                "na": verdicts.count(TestVerdict.NA),
                "aborted": self.aborted or self._stop.is_set(),
                "resumed": False,
            }
        return self.summary

    def _service_control(self) -> None:
        if self._abort_requested.is_set() and not self.aborted:
            self.aborted = True
            try:
                self.client.session.request(codec.build_abort(), response_types={Body.Ack}, timeout=1.0)
                self._log("WARN", "abort requested")
            except LinkError:
                pass
        while True:
            try:
                prompt_id, answer = self._answers.get_nowait()
            except queue.Empty:
                break
            try:
                self.client.session.request(
                    codec.build_operator_answer(prompt_id, answer),
                    response_types={Body.Ack},
                    timeout=2.0,
                )
                self._log("INFO", f"operator answer {answer!r} for prompt {prompt_id}")
            except LinkError as exc:
                self._log("ERROR", f"could not send operator answer: {exc}")


class Client:
    """Role-independent HWLINK client with role helpers."""

    def __init__(
        self,
        transport: Transport,
        *,
        host_name: str = "hwval-studio",
        host_version: str = __version__,
        timeout: float = 0.5,
        retries: int = 3,
        log_handler: LogCallback | None = None,
    ) -> None:
        self.transport = transport
        self.log_handler = log_handler
        self.session = LinkSession(
            transport,
            config=SessionConfig(
                timeout=timeout,
                retries=retries,
                host_name=host_name,
                host_version=host_version,
                protocol_minor=PROTOCOL_MINOR,
            ),
            log_handler=log_handler,
        )
        self.identity: Identity | None = None
        self.role: int = 0
        self.device_info: dict[str, Any] | None = None
        self.groups: list[TestGroup] = []
        self.tests: list[TestCase] = []
        self.harness: dict[str, Any] = {}
        self.busy = False
        self.last_error = ""
        self._cancel = threading.Event()

    # -- connection ----------------------------------------------------
    def _hello_once(self) -> dict[str, Any]:
        return self.session.hello()

    def connect(self, *, expected_role: int | None = None) -> Identity:
        try:
            reply = self._hello_once()
        except LinkTimeout:
            # CR-01: HWVAL starts in its text CLI; ask it for link mode.
            try:
                self.transport.write(b"mode link\r")
            except Exception:
                pass
            time.sleep(0.15)
            reply = self._hello_once()
        major = int(reply.get("protocol_major", 0))
        if major != PROTOCOL_MAJOR:
            raise VersionMismatch(PROTOCOL_MAJOR, major) from None
        minor = int(reply.get("protocol_minor", 0))
        if minor > PROTOCOL_MINOR:
            self._log("INFO", f"device protocol minor {minor} is newer than host {PROTOCOL_MINOR}; continuing")
        if expected_role is not None and int(reply.get("role", 0)) != expected_role:
            raise DeviceError(
                f"expected {expected_role} role, device reports {reply.get('role_name', reply.get('role'))}"
            )
        self.identity = Identity(**{key: reply[key] for key in Identity.__dataclass_fields__ if key in reply})
        self.identity.raw = reply
        self.role = int(reply.get("role", 0))
        self._log("INFO", f"connected: {self.identity.role_name} {self.identity.firmware_name} {self.identity.version}")
        return self.identity

    def _log(self, level: str, text: str) -> None:
        if self.log_handler:
            self.log_handler(level, text)

    def close(self) -> None:
        self._cancel.set()
        try:
            self.transport.close()
        except Exception:
            pass

    def ping(self) -> int:
        return self.session.ping()

    def set_baud(self, rate: int) -> None:
        self.session.set_baud(rate)

    def reset(self) -> None:
        self.session.reset()

    def enter_text_mode(self) -> None:
        self.session.enter_text_mode()

    def enter_bootloader(self) -> None:
        self._require(Role.DEMO)
        self.session.request(codec.build_enter_bootloader(), response_types={Body.Ack}, timeout=2.0)
        self._log("INFO", "device entering bootloader")

    # -- HWVAL ---------------------------------------------------------
    def _require(self, role: int) -> None:
        if self.role != role:
            raise DeviceError(f"operation requires {codec.ROLE_NAMES.get(role, role)} role")

    def get_device_info(self) -> dict[str, Any]:
        self._require(Role.HWVAL)
        _, table = self.session.request(codec.build_get_device_info(), response_types={Body.DeviceInfo})
        self.device_info = codec.parse_device_info(table)
        return self.device_info

    def load_catalogue(self) -> tuple[list[TestGroup], list[TestCase]]:
        self._require(Role.HWVAL)
        groups: list[TestGroup] = []
        page = 0
        while True:
            _, table = self.session.request(codec.build_list_groups(page), response_types={Body.GroupList})
            data = codec.parse_group_list(table)
            for group in data["groups"]:
                groups.append(
                    TestGroup(
                        code=group["code"],
                        name=group["name"],
                        test_count=int(group["test_count"]),
                        category=CATEGORY_MAP.get(group["code"], "Other Peripherals"),
                    )
                )
            page += 1
            if page >= int(data["page_count"]) or page > 64:
                break
        tests: list[TestCase] = []
        for group in groups:
            page = 0
            while True:
                _, table = self.session.request(
                    codec.build_list_tests(group.code, page), response_types={Body.TestList}
                )
                data = codec.parse_test_list(table)
                for test in data["tests"]:
                    tests.append(
                        TestCase(
                            id=test["id"],
                            group=test["group"],
                            title=test["title"],
                            level=int(test["level"]),
                            level_name=test["level_name"],
                            operator=bool(test["operator"]),
                            destructive=bool(test["destructive"]),
                            timeout_ms=int(test["timeout_ms"]),
                            needs=test["needs"],
                            reqs=test["reqs"],
                        )
                    )
                page += 1
                if page >= int(data["page_count"]) or page > 64:
                    break
        self.groups = groups
        self.tests = tests
        self._log("INFO", f"catalogue: {len(groups)} groups, {len(tests)} tests")
        return groups, tests

    def load_harness(self) -> dict[str, Any]:
        self._require(Role.HWVAL)
        wires: list[dict[str, Any]] = []
        page = 0
        info: dict[str, Any] = {}
        while True:
            _, table = self.session.request(codec.build_get_harness(page), response_types={Body.HarnessInfo})
            data = codec.parse_harness(table)
            info = data
            wires.extend(data["wires"])
            page += 1
            if page >= int(data["page_count"]) or page > 8:
                break
        info["wires"] = wires
        self.harness = info
        return info

    def start_run(
        self,
        selection: Selection,
        *,
        on_event: EventCallback | None = None,
        on_log: LogCallback | None = None,
    ) -> RunController:
        self._require(Role.HWVAL)
        return RunController(self, selection, on_event=on_event, on_log=on_log)

    def get_results(self) -> list[dict[str, Any]]:
        self._require(Role.HWVAL)
        results: list[dict[str, Any]] = []
        page = 0
        while True:
            _, table = self.session.request(codec.build_get_results(page), response_types={Body.ResultList})
            data = codec.parse_result_list(table)
            results.extend(data["results"])
            page += 1
            if page >= int(data["page_count"]) or page > 128:
                break
        return results

    def clear_results(self) -> None:
        self._require(Role.HWVAL)
        self.session.request(codec.build_clear_results(), response_types={Body.Ack})

    def get_report(self) -> dict[str, Any]:
        self._require(Role.HWVAL)
        _, table = self.session.request(codec.build_get_report(), response_types={Body.Report})
        return codec.parse_report(table)

    def get_setting(self, key: str) -> dict[str, Any]:
        self._require(Role.HWVAL)
        _, table = self.session.request(codec.build_get_setting(key), response_types={Body.Setting})
        return codec.parse_setting(table)

    def set_setting(self, key: str, value: str) -> None:
        self._require(Role.HWVAL)
        self.session.request(codec.build_set_setting(key, value), response_types={Body.Ack})

    # -- BOOT ----------------------------------------------------------
    def get_boot_info(self) -> dict[str, Any]:
        self._require(Role.BOOTLOADER)
        _, table = self.session.request(codec.build_get_boot_info(), response_types={Body.BootInfo})
        return codec.parse_boot_info(table)

    def update_image(
        self,
        image: Any,
        *,
        chunk_size: int = 1024,
        activate: bool = True,
        progress: Callable[[int, int, float], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Upload a parsed FirmwareImage; retries every request (FW-004/005)."""
        self._require(Role.BOOTLOADER)
        header = image.header_dict()
        body = image.body
        self.session.request(codec.build_update_begin(header), response_types={Body.Ack}, timeout=5.0)
        previous_event_handler = self.session.event_handler

        def handle_event(event: Any) -> None:
            if event.body_type == Body.Progress and progress:
                data = codec.parse_progress(event.table)
                total = int(data.get("total", 0))
                if total:
                    elapsed = max(0.001, time.monotonic() - started)
                    progress(int(data.get("done", 0)), total, int(data.get("done", 0)) / elapsed)

        self.session.event_handler = handle_event
        offset = 0
        started = time.monotonic()
        resyncs = 0
        try:
            while offset < len(body):
                if cancel is not None and cancel.is_set():
                    self.abort_update()
                    raise DeviceError("update cancelled")
                payload = codec.build_update_data(offset, body[offset : offset + chunk_size])
                # A chunk may hit a 128 KB sector erase: allow a generous
                # timeout and restart it on every Progress event (LNK-009).
                response_type, table = self.session.request(
                    payload,
                    response_types={Body.Ack, Body.Nak},
                    timeout=8.0,
                    allow_nak=True,
                )
                if response_type == Body.Nak:
                    nak = codec.parse_nak(table)
                    if int(nak["error"]) == 10:  # OUT_OF_ORDER: resynchronise
                        resyncs += 1
                        if resyncs > 8:
                            raise DeviceError("update resync limit reached")
                        offset = int(nak["expected_offset"])
                        self._log("WARN", f"update resync to offset {offset}")
                        continue
                    raise DeviceError(f"UpdateData at {offset}: {nak['error_name']}: {nak['detail']}")
                ack = codec.parse_ack(table)
                next_offset = int(ack["next_offset"])
                if next_offset <= offset:
                    raise DeviceError(f"device did not advance past offset {offset}")
                offset = next_offset
                if progress:
                    elapsed = max(0.001, time.monotonic() - started)
                    progress(offset, len(body), offset / elapsed)
            _, table = self.session.request(
                codec.build_update_end(), response_types={Body.UpdateResult}, timeout=30.0
            )
            result = codec.parse_update_result(table)
            if not result["success"]:
                raise DeviceError(f"update failed: {result['error_name']}: {result['detail']}")
            if activate:
                self.session.request(codec.build_activate(), response_types={Body.Ack}, timeout=3.0)
            return result
        finally:
            # M12: a Nak, timeout or cancel must not leave the upload's
            # event handler installed for the rest of the session.
            self.session.event_handler = previous_event_handler

    def abort_update(self) -> None:
        try:
            self.session.request(codec.build_update_abort(), response_types={Body.Ack}, timeout=1.0)
        except LinkError:
            pass

    def activate(self) -> None:
        self._require(Role.BOOTLOADER)
        self.session.request(codec.build_activate(), response_types={Body.Ack}, timeout=3.0)

    # -- DEMO ----------------------------------------------------------
    def get_status(self) -> dict[str, Any]:
        self._require(Role.DEMO)
        _, table = self.session.request(codec.build_get_status(), response_types={Body.Status})
        return codec.parse_status(table)

    def drain_events(self) -> list[Any]:
        """Return events that arrived while a request was in flight."""
        events: list[Any] = []
        while True:
            try:
                events.append(self.session.events.get_nowait())
            except queue.Empty:
                break
        return events

    def set_led(self, led: int, pattern: int, period_ms: int) -> None:
        self._require(Role.DEMO)
        self.session.request(
            codec.build_set_led(led, pattern, period_ms), response_types={Body.Ack}, timeout=2.0
        )

    def set_led_all(self, pattern: int, period_ms: int) -> None:
        self._require(Role.DEMO)
        self.session.request(
            codec.build_set_led_all(pattern, period_ms), response_types={Body.Ack}, timeout=2.0
        )

    def clear_fault(self) -> None:
        self._require(Role.DEMO)
        self.session.request(codec.build_clear_fault(), response_types={Body.Ack}, timeout=2.0)


CATEGORY_MAP = {
    "DEV": "CPU & System",
    "CORE": "CPU & System",
    "FRT": "CPU & System",
    "CACHE": "CPU & System",
    "MPU": "CPU & System",
    "INT": "CPU & System",
    "DMA": "CPU & System",
    "DBG": "CPU & System",
    "RAM": "Memory",
    "FLS": "Memory",
    "OB": "Memory",
    "OTP": "Memory",
    "QSPI": "Memory",
    "FMC": "Memory",
    "SD": "Memory",
    "CLK": "Clocks & Power",
    "PWR": "Clocks & Power",
    "RST": "Clocks & Power",
    "WDG": "Clocks & Power",
    "RTC": "Clocks & Power",
    "GPIO": "GPIO & Board I/O",
    "LED": "GPIO & Board I/O",
    "BTN": "GPIO & Board I/O",
    "ADC": "Analog",
    "DAC": "Analog",
    "TIM": "Timers",
    "LPTIM": "Timers",
    "UART": "Communication",
    "SPI": "Communication",
    "I2S": "Communication",
    "I2C": "Communication",
    "CAN": "Communication",
    "SAI": "Communication",
    "SPDIF": "Communication",
    "ETH": "Connectivity",
    "USB": "Connectivity",
    "USBHS": "Connectivity",
    "LTDC": "Graphics & Media",
    "DMA2D": "Graphics & Media",
    "JPEG": "Graphics & Media",
    "DCMI": "Graphics & Media",
    "CRC": "Other Peripherals",
    "RNG": "Other Peripherals",
    "CEC": "Other Peripherals",
    "DFSDM": "Other Peripherals",
    "MDIOS": "Other Peripherals",
    "STLK": "Board",
    "BRD": "Board",
}
