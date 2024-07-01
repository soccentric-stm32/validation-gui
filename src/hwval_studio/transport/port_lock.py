"""Cross-process advisory lock so one window holds a serial port (CON-010)."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

_HELD: set[Path] = set()


def _lock_path(port: str) -> Path:
    digest = hashlib.sha256(port.encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"hwval-studio-{digest}.lock"


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) sends CTRL_C_EVENT on Windows instead of probing.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def acquire_port(port: str) -> Path | None:
    path = _lock_path(port)
    if path in _HELD:
        return None
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(str(os.getpid()))
            _HELD.add(path)
            return path
        except FileExistsError:
            try:
                pid = int(path.read_text().strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid and pid != os.getpid() and _pid_alive(pid):
                return None
            try:
                path.unlink()
            except OSError:
                return None
    return None


def release_port(path: Path | None) -> None:
    if path is None:
        return
    _HELD.discard(path)
    try:
        path.unlink()
    except OSError:
        pass
