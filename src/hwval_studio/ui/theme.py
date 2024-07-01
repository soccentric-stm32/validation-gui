"""Studio colour names, icons and theme entry points (SRS section 4).

Colours, fonts and the style sheet come from the shared ``soc_theme`` module."""

from __future__ import annotations

from importlib import resources

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QColor, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from hwval_studio.ui import soc_icons, soc_theme


def _palette(t: soc_theme.Tokens) -> dict[str, str]:
    """Studio's colour names, filled from the shared SoCcentric tokens."""
    return {
        "window": t.window, "bg": t.window, "sidebar": t.sidebar,
        "sidebar_alt": t.surface_alt, "separator": t.hairline,
        "border": t.border, "text": t.text, "secondary": t.text_secondary,
        "muted": t.text_tertiary, "accent": t.accent,
        "accent_dark": t.accent_pressed, "accent_soft": t.accent_soft,
        "pass": t.success, "pass_soft": t.success_soft,
        "fail": t.danger, "fail_soft": t.danger_soft,
        "skip": t.warning, "skip_soft": t.warning_soft,
        "na": t.text_tertiary, "na_soft": t.surface_alt,
        "warning": t.warning, "running": t.accent, "selected": t.accent_soft,
        "surface": t.surface, "surface_alt": t.surface_alt,
        "row_alt": t.surface_alt, "shadow": "rgba(0,0,0,0.08)",
    }


# Mutated in place by apply_theme() so every module sees the active scheme.
COLORS: dict[str, str] = _palette(soc_theme.LIGHT)

_STATE_KEYS = {
    "PASS": "pass", "FAIL": "fail", "SKIP": "skip", "N/A": "na", "NA": "na",
    "RUNNING": "running", "NOT RUN": "muted", "IDLE": "muted",
    "WARN": "warning", "ERROR": "fail", "INFO": "accent", "DEBUG": "muted",
}
STATE_COLORS: dict[str, str] = {k: COLORS[v] for k, v in _STATE_KEYS.items()}

STATE_ICONS = {
    "PASS": "check",
    "FAIL": "x",
    "SKIP": "skip",
    "N/A": "na",
    "NA": "na",
    "RUNNING": "running",
    "NOT RUN": "dot",
    "IDLE": "dot",
    "WARN": "warning",
    "ERROR": "warning",
}

_RESOURCE_PACKAGE = "hwval_studio.resources"


def icon(name: str, color: str | None = None, size: int = 24) -> QIcon:
    """A glyph of the shared SoCcentric set (``soc_icons``), tinted ``color``.

    The icon is live: it renders at whatever size the widget asks for."""
    return soc_icons.icon(name, color or COLORS["text"], size)


def nav_icon(name: str, size: int = 17) -> QIcon:
    """Sidebar icon: secondary text normally, full text on the selected row."""
    return soc_icons.icon(name, "text_secondary", size, selected="text")


def state_icon(state: str, size: int = 18) -> QIcon:
    key = state.upper().replace("_", " ")
    return icon(STATE_ICONS.get(key, "dot"), STATE_COLORS.get(key, COLORS["muted"]), size)


def state_color(state: str) -> QColor:
    return QColor(STATE_COLORS.get(state.upper().replace("_", " "), COLORS["muted"]))


def apply_theme(app: QApplication, dark: bool | None = None) -> None:
    """Apply the shared SoCcentric theme (Fusion, palette, font, style sheet)."""
    tokens = soc_theme.apply(app, dark)
    COLORS.update(_palette(tokens))
    STATE_COLORS.update({k: COLORS[v] for k, v in _STATE_KEYS.items()})
    load_fonts(app)
    app.setFont(soc_theme.ui_font())


def load_fonts(app: QApplication) -> None:
    """Load bundled open-licence fonts when present (LNF-005)."""
    try:
        font_dir = resources.files(_RESOURCE_PACKAGE).joinpath("fonts")
        entries = list(font_dir.iterdir())
    except (FileNotFoundError, ModuleNotFoundError):
        return
    for entry in entries:
        if entry.name.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFontFromData(QByteArray(entry.read_bytes()))


def color_for_state(state: str) -> QColor:
    return QColor(STATE_COLORS.get(state.upper().replace("_", " "), COLORS["muted"]))


def apply_zoom(app: QApplication, percent: int) -> None:
    """Scale the stylesheet and application font (GNFR-006 View > Zoom)."""
    import re

    factor = max(0.7, min(2.0, percent / 100.0))
    css = soc_theme.stylesheet(soc_theme.current())

    def scale(match: re.Match[str]) -> str:
        return f"font-size: {float(match.group(1)) * factor:.1f}px"

    app.setStyleSheet(re.sub(r"font-size: (\d+(?:\.\d+)?)px", scale, css))
    font = soc_theme.ui_font()
    font.setPixelSize(round(13 * factor))
    app.setFont(font)
