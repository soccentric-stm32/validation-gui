"""Synchronous serial and socket transports for the CLI and tools."""

from __future__ import annotations

import queue
import socket
import threading
import time

from hwval_studio.protocol.link import FrameParser, TransportError, build_raw


class SyncSerialTransport:
    def __init__(self, port: str, baudrate: int = 115200) -> None:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover
            raise TransportError("pyserial is required: pip install pyserial") from exc
        try:
            self._serial = serial.Serial(port, baudrate, timeout=0.05, write_timeout=3)
        except Exception as exc:
            raise TransportError(f"cannot open {port}: {exc}") from exc
        self._parser = FrameParser()
        self._frames: queue.Queue[bytes] = queue.Queue()
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("transport closed")
        try:
            self._serial.write(data)
            self._serial.flush()
        except Exception as exc:
            raise TransportError(f"serial write failed: {exc}") from exc

    def read_frame(self, timeout: float) -> bytes | None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self._frames.get_nowait()
            except queue.Empty:
                pass
            if self._closed:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                waiting = self._serial.in_waiting
                data = self._serial.read(min(max(1, waiting), 4096))
            except Exception as exc:
                raise TransportError(f"serial read failed: {exc}") from exc
            for frame in self._parser.feed(data):
                self._frames.put(build_raw(frame.payload, frame.seq, frame.flags))
            if not data:
                time.sleep(0.001)

    def close(self) -> None:
        self._closed = True
        try:
            self._serial.close()
        except Exception:
            pass


class SocketTransport:
    def __init__(self, host: str = "127.0.0.1", port: int = 7000, timeout: float = 5.0) -> None:
        try:
            self._socket = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise TransportError(f"cannot connect to {host}:{port}: {exc}") from exc
        self._parser = FrameParser()
        self._frames: queue.Queue[bytes] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()

    def write(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("transport closed")
        try:
            with self._lock:
                self._socket.sendall(data)
        except OSError as exc:
            raise TransportError(f"socket write failed: {exc}") from exc

    def read_frame(self, timeout: float) -> bytes | None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self._frames.get_nowait()
            except queue.Empty:
                pass
            if self._closed:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._socket.settimeout(min(0.05, max(0.001, remaining)))
            try:
                data = self._socket.recv(4096)
            except TimeoutError:
                continue
            except OSError as exc:
                raise TransportError(f"socket read failed: {exc}") from exc
            if not data:
                self._closed = True
                return None
            for frame in self._parser.feed(data):
                self._frames.put(build_raw(frame.payload, frame.seq, frame.flags))

    def close(self) -> None:
        self._closed = True
        try:
            self._socket.close()
        except Exception:
            pass
