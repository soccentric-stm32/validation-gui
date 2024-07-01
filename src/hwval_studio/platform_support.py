"""All platform-specific code lives here (GNFR-008)."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QWidget


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def platform_name() -> str:
    return {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")


def native_menu_bar() -> bool:
    return is_macos()


def modifier_symbols() -> tuple[str, str]:
    if is_macos():
        return "⌘", "⌥"
    return "Ctrl+", "Alt+"


def serial_permission_hint(port: str, error: str) -> str:
    lowered = error.lower()
    if "permission" not in lowered and "access is denied" not in lowered:
        return ""
    if is_linux():
        return (
            f"Cannot open {port}: permission denied.\n\n"
            "Add your user to the serial group and log in again:\n"
            "  sudo usermod -aG dialout $USER      (Debian/Ubuntu)\n"
            "  sudo usermod -aG uucp $USER         (Arch/Fedora variants)\n\n"
            "Install the ST-LINK udev rules if the probe is not accessible.\n"
            "See the user guide (Help > HWVAL User Guide)."
        )
    if is_macos():
        return (
            f"Cannot open {port}: permission denied.\n\n"
            "Check that no other application (serial terminal, debugger) holds the port. "
            "On macOS the ST-LINK VCP is usually /dev/cu.usbmodem*."
        )
    return (
        f"Cannot open {port}: access denied.\n\n"
        "Close any serial terminal or debugger using the port, then retry."
    )


def bring_to_front(widget: QWidget) -> None:
    widget.show()
    widget.raise_()
    widget.activateWindow()
    if is_macos():
        try:
            from AppKit import NSApp

            NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass


def alert_sound() -> None:
    QApplication.beep()


def request_attention(widget: QWidget) -> None:
    """Bounce the Dock icon on macOS or flash the taskbar button elsewhere."""
    if is_macos():
        try:
            from AppKit import NSApp, NSInformationalRequest

            NSApp.requestUserAttention_(NSInformationalRequest)
            return
        except Exception:
            pass
    if is_windows():
        try:
            import ctypes

            hwnd = int(widget.winId())
            ctypes.windll.user32.FlashWindow(hwnd, True)
        except Exception:
            pass


def _windows_taskbar_progress(widget: QWidget, value: int, maximum: int) -> bool:
    # The raw ITaskbarList3 vtable call that used to live here used the wrong
    # indices and never passed the COM `this` pointer, which is undefined
    # behaviour on every connect/disconnect.  Until a Qt WinExtras taskbar
    # button is available, use the window-title fallback below.
    return False


def set_progress(widget: QWidget, value: int, maximum: int) -> None:
    """Show progress in the Dock tile (macOS) or taskbar/window title."""
    if is_macos():
        try:
            from AppKit import NSApp

            if maximum <= 0:
                NSApp.dockTile().setBadgeLabel_(None)
            else:
                NSApp.dockTile().setBadgeLabel_(f"{int(100 * value / maximum)}%")
            return
        except Exception:
            pass
    if is_windows() and _windows_taskbar_progress(widget, value, maximum):
        return
    title = widget.windowTitle()
    if title.startswith("[") and "] " in title:
        title = title.split("] ", 1)[1]
    if maximum > 0:
        widget.setWindowTitle(f"[{int(100 * value / maximum)}%] {title}")
    else:
        widget.setWindowTitle(title)


def reveal_path(path: str | Path) -> bool:
    p = Path(path)
    if p.is_file():
        p = p.parent
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def open_url(url: str) -> bool:
    return QDesktopServices.openUrl(QUrl(url))


def default_monospace() -> str:
    if is_macos():
        return "SF Mono"
    if is_windows():
        return "Consolas"
    return "DejaVu Sans Mono"


def python_version_text() -> str:
    return f"Python {platform.python_version()} on {platform_name()} {platform.machine()}"
