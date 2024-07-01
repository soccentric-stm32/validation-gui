"""Serial/simulator transport worker (ARC-002).

All serial reads and writes happen on this QThread; the UI and operation
threads exchange bytes through thread-safe queues and Qt signals.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from PySide6.QtCore import QThread, Signal

from hwval_studio.protocol.link import (
    MAX_FRAME,
    FrameParser,
    build_raw,
)
from hwval_studio.simulator.device import SimulatedDevice, SimulatedTransport

SIM_PREFIXES = ("simulator:", "sim:")


def is_simulator_port(port: str) -> bool:
    return port.lower().startswith(SIM_PREFIXES)


def is_socket_port(port: str) -> bool:
    return port.lower().startswith(("tcp://", "socket://"))


class SerialWorker(QThread):
    opened = Signal(str)
    failed = Signal(str)
    closed = Signal()
    transport_error = Signal(str)
    frame_received = Signal(bytes)
    raw_bytes = Signal(bytes)

    def __init__(self, port: str, baudrate: int = 115200, parent: Any = None) -> None:
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self._tx: queue.Queue[bytes | None] = queue.Queue()
        self._rx: queue.Queue[bytes | None] = queue.Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._open_error = ""
        self._parser = FrameParser()
        self._backend: Any = None
        self._serial: Any = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------
    @property
    def open_error(self) -> str:
        return self._open_error

    @property
    def is_open(self) -> bool:
        return self._backend is not None or self._serial is not None

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout) and not self._open_error

    def run(self) -> None:
        self._stop.clear()
        try:
            if is_simulator_port(self.port):
                role = self.port.split(":", 1)[1].strip() or "hwval"
                self._backend = SimulatedTransport(SimulatedDevice(role, auto_answer=False))
            elif is_socket_port(self.port):
                from hwval_studio.transport.sync import SocketTransport

                address = self.port.split("://", 1)[1]
                host, _, port_text = address.partition(":")
                self._backend = SocketTransport(host or "127.0.0.1", int(port_text or 7000))
            else:
                import serial

                self._serial = serial.Serial(
                    self.port, self.baudrate, timeout=0.02, write_timeout=3
                )
        except Exception as exc:
            self._open_error = str(exc)
            self._ready.set()
            self.failed.emit(str(exc))
            return
        self._open_error = ""
        self._ready.set()
        self.opened.emit(self.port)
        while not self._stop.is_set():
            self._drain_tx()
            if self._serial is not None:
                try:
                    waiting = self._serial.in_waiting
                    data = self._serial.read(min(max(1, waiting), MAX_FRAME * 2))
                except Exception as exc:
                    if not self._stop.is_set():
                        self.transport_error.emit(f"serial read failed: {exc}")
                    break
                if data:
                    self.raw_bytes.emit(data)
                    self._parse(data)
            elif self._backend is not None:
                try:
                    raw = self._backend.read_frame(0.01)
                except Exception as exc:
                    if not self._stop.is_set():
                        self.transport_error.emit(str(exc))
                    break
                if raw:
                    self._rx.put(raw)
                    self.frame_received.emit(raw)
            else:
                time.sleep(0.01)
        self._cleanup()

    def _parse(self, data: bytes) -> None:
        for frame in self._parser.feed(data):
            raw = build_raw(frame.payload, frame.seq, frame.flags)
            self._rx.put(raw)
            self.frame_received.emit(raw)

    def _drain_tx(self) -> None:
        while True:
            try:
                data = self._tx.get_nowait()
            except queue.Empty:
                return
            if data is None:
                self._stop.set()
                return
            try:
                if self._serial is not None:
                    with self._lock:
                        self._serial.write(data)
                        self._serial.flush()
                elif self._backend is not None:
                    self._backend.write(data)
            except Exception as exc:
                if not self._stop.is_set():
                    self.transport_error.emit(f"serial write failed: {exc}")
                self._stop.set()
                return

    def _cleanup(self) -> None:
        try:
            if self._serial is not None:
                self._serial.close()
        except Exception:
            pass
        self._serial = None
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception:
                pass
        self._backend = None
        self._parser.reset()
        self._rx.put(None)
        self.closed.emit()

    def close(self) -> None:
        self._stop.set()
        self._tx.put(None)
        # Wake a blocked read so the loop can observe _stop without waiting
        # for its timeout; the caller (often the UI) should not block for
        # seconds. terminate() remains a last resort only.
        if self._serial is not None:
            try:
                self._serial.cancel_read()
            except Exception:
                pass
        if not self.wait(1500):
            self.terminate()
            self.wait(1000)

    # -- Transport protocol -------------------------------------------
    def write(self, data: bytes) -> None:
        if self._stop.is_set():
            raise OSError("transport closed")
        self._tx.put(data)
        # Wake the reader that is blocked in serial.read() so the queued
        # frame goes out now instead of after the read timeout.
        if self._serial is not None:
            try:
                self._serial.cancel_read()
            except Exception:
                pass

    def read_frame(self, timeout: float) -> bytes | None:
        try:
            value = self._rx.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None
        if value is None:
            # Re-queue the sentinel for the next reader.
            self._rx.put(None)
            return None
        return value

    def change_baud(self, rate: int) -> None:
        with self._lock:
            self.baudrate = int(rate)
            if self._serial is not None:
                try:
                    self._serial.baudrate = int(rate)
                    time.sleep(0.05)
                    self._serial.reset_input_buffer()
                except Exception as exc:
                    self.transport_error.emit(f"baud change failed: {exc}")
