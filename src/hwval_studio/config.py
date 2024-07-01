"""Preferences and persisted window state (SRS section 15)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QStandardPaths

from hwval_studio import APP_ID, APP_NAME, ORG_NAME


def app_data_dir() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(location) if location else Path.home() / ".local" / "share" / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    path = (Path(location) if location else app_data_dir()) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    return app_data_dir() / "history.sqlite"


@dataclass(slots=True)
class TestPreset:
    levels: str = "L,S,E"
    allow_operator: bool = True
    allow_destructive: bool = False
    repeat: int = 1
    until_fail: bool = False
    ids: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    all_tests: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "levels": self.levels,
            "allow_operator": self.allow_operator,
            "allow_destructive": self.allow_destructive,
            "repeat": self.repeat,
            "until_fail": self.until_fail,
            "ids": self.ids,
            "groups": self.groups,
            "all": self.all_tests,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestPreset:
        return cls(
            levels=str(data.get("levels", "L,S,E")),
            allow_operator=bool(data.get("allow_operator", True)),
            allow_destructive=bool(data.get("allow_destructive", False)),
            repeat=int(data.get("repeat", 1) or 1),
            until_fail=bool(data.get("until_fail", False)),
            ids=[str(x) for x in data.get("ids", [])],
            groups=[str(x) for x in data.get("groups", [])],
            all_tests=bool(data.get("all", True)),
        )


class Preferences:
    """Thin typed wrapper around QSettings; writes apply immediately (PRF-004)."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings or QSettings(ORG_NAME, APP_NAME)
        self._last_folders: dict[str, str] = {}
        raw = self.settings.value("dialogs/folders", "{}")
        try:
            self._last_folders = json.loads(str(raw)) if raw else {}
        except (TypeError, ValueError):
            self._last_folders = {}

    # -- generic -------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.value(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings.setValue(key, value)
        self.settings.sync()

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.settings.value(key, default))
        except (TypeError, ValueError):
            return default

    # -- general -------------------------------------------------------
    @property
    def start_in_operator_mode(self) -> bool:
        return self.get_bool("general/operator_mode", False)

    @start_in_operator_mode.setter
    def start_in_operator_mode(self, value: bool) -> None:
        self.set("general/operator_mode", value)

    @property
    def show_log_on_start(self) -> bool:
        return self.get_bool("general/show_log", True)

    @show_log_on_start.setter
    def show_log_on_start(self, value: bool) -> None:
        self.set("general/show_log", value)

    @property
    def confirm_quit_during_run(self) -> bool:
        return self.get_bool("general/confirm_quit", True)

    @confirm_quit_during_run.setter
    def confirm_quit_during_run(self, value: bool) -> None:
        self.set("general/confirm_quit", value)

    # -- connection ----------------------------------------------------
    @property
    def auto_connect(self) -> bool:
        return self.get_bool("connection/auto_connect", True)

    @auto_connect.setter
    def auto_connect(self, value: bool) -> None:
        self.set("connection/auto_connect", value)

    @property
    def fast_baud(self) -> bool:
        return self.get_bool("connection/fast_baud", True)

    @fast_baud.setter
    def fast_baud(self, value: bool) -> None:
        self.set("connection/fast_baud", value)

    @property
    def last_port(self) -> str:
        return str(self.settings.value("connection/last_port", ""))

    @last_port.setter
    def last_port(self, value: str) -> None:
        self.set("connection/last_port", value)

    @property
    def default_port(self) -> str:
        return str(self.settings.value("connection/default_port", ""))

    @default_port.setter
    def default_port(self, value: str) -> None:
        self.set("connection/default_port", value)

    # -- tests ---------------------------------------------------------
    @property
    def test_preset(self) -> TestPreset:
        raw = self.settings.value("tests/preset", "")
        if raw:
            try:
                return TestPreset.from_dict(json.loads(str(raw)))
            except (TypeError, ValueError):
                pass
        return TestPreset(
            levels=str(self.settings.value("tests/levels", "L,S,E")),
            allow_operator=self.get_bool("tests/allow_operator", True),
            allow_destructive=False,
        )

    @test_preset.setter
    def test_preset(self, preset: TestPreset) -> None:
        self.set("tests/preset", json.dumps(preset.to_dict()))
        self.set("tests/levels", preset.levels)
        self.set("tests/allow_operator", preset.allow_operator)

    @property
    def operator_preset(self) -> TestPreset:
        raw = self.settings.value("operator/preset", "")
        if raw:
            try:
                return TestPreset.from_dict(json.loads(str(raw)))
            except (TypeError, ValueError):
                pass
        return TestPreset(levels="S", allow_operator=True, allow_destructive=False)

    @operator_preset.setter
    def operator_preset(self, preset: TestPreset) -> None:
        self.set("operator/preset", json.dumps(preset.to_dict()))

    # -- firmware ------------------------------------------------------
    @property
    def openocd_path(self) -> str:
        return str(self.settings.value("firmware/openocd_path", ""))

    @openocd_path.setter
    def openocd_path(self, value: str) -> None:
        self.set("firmware/openocd_path", value)

    @property
    def auto_activate(self) -> bool:
        return self.get_bool("firmware/auto_activate", True)

    @auto_activate.setter
    def auto_activate(self, value: bool) -> None:
        self.set("firmware/auto_activate", value)

    @property
    def image_folder(self) -> str:
        return str(self.settings.value("firmware/image_folder", ""))

    @image_folder.setter
    def image_folder(self, value: str) -> None:
        self.set("firmware/image_folder", value)

    # -- history -------------------------------------------------------
    @property
    def database_path(self) -> str:
        return str(self.settings.value("history/database_path", ""))

    @database_path.setter
    def database_path(self, value: str) -> None:
        self.set("history/database_path", value)

    @property
    def retention_days(self) -> int:
        return self.get_int("history/retention_days", 0)

    @retention_days.setter
    def retention_days(self, value: int) -> None:
        self.set("history/retention_days", value)

    @property
    def auto_export_folder(self) -> str:
        return str(self.settings.value("history/auto_export_folder", ""))

    @auto_export_folder.setter
    def auto_export_folder(self, value: str) -> None:
        self.set("history/auto_export_folder", value)

    # -- operator ------------------------------------------------------
    @property
    def operator_pin(self) -> str:
        return str(self.settings.value("operator/pin", ""))

    @operator_pin.setter
    def operator_pin(self, value: str) -> None:
        self.set("operator/pin", value)

    @property
    def operator_name(self) -> str:
        return str(self.settings.value("operator/name", ""))

    @operator_name.setter
    def operator_name(self, value: str) -> None:
        self.set("operator/name", value)

    @property
    def operator_names(self) -> list[str]:
        raw = self.settings.value("operator/names", "[]")
        try:
            values = json.loads(str(raw))
            return [str(v) for v in values] if isinstance(values, list) else []
        except (TypeError, ValueError):
            return []

    @operator_names.setter
    def operator_names(self, value: list[str]) -> None:
        self.set("operator/names", json.dumps(value))

    @property
    def operator_auto_export(self) -> bool:
        return self.get_bool("operator/auto_export", True)

    @operator_auto_export.setter
    def operator_auto_export(self, value: bool) -> None:
        self.set("operator/auto_export", value)

    # -- file dialogs --------------------------------------------------
    @property
    def last_folders(self) -> dict[str, str]:
        return dict(self._last_folders)

    def last_folder(self, kind: str) -> str:
        if kind in self._last_folders:
            return self._last_folders[kind]
        if kind in {"image", "firmware"}:
            return self.image_folder
        if kind == "export":
            return self.auto_export_folder
        return str(Path.home())

    def set_last_folder(self, kind: str, folder: str) -> None:
        if not folder:
            return
        self._last_folders[kind] = folder
        self.set("dialogs/folders", json.dumps(self._last_folders))

    # -- window state --------------------------------------------------
    def save_window_state(self, geometry: bytes, state: bytes, sidebar_width: int, splitter: bytes) -> None:
        self.settings.setValue("window/geometry", geometry)
        self.settings.setValue("window/state", state)
        self.settings.setValue("window/sidebar_width", sidebar_width)
        self.settings.setValue("window/splitter", splitter)
        self.settings.sync()

    def restore_window_state(self) -> tuple[bytes, bytes, int, bytes]:
        geometry = self.settings.value("window/geometry", b"")
        state = self.settings.value("window/state", b"")
        width = self.get_int("window/sidebar_width", 248)
        splitter = self.settings.value("window/splitter", b"")
        return (
            geometry if isinstance(geometry, bytes) else bytes(geometry or b""),
            state if isinstance(state, bytes) else bytes(state or b""),
            width,
            splitter if isinstance(splitter, bytes) else bytes(splitter or b""),
        )

    @property
    def last_selected_item(self) -> str:
        return str(self.settings.value("window/selected_item", "all"))

    @last_selected_item.setter
    def last_selected_item(self, value: str) -> None:
        self.set("window/selected_item", value)
