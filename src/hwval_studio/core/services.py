"""Role services on top of one shared :class:`Client`/``LinkSession`` (ARC-004).

The Qt controller uses these thin services for role-specific operations; the
underlying request/response and framing code is shared and Qt-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hwval_studio.core.client import Client, RunController, Selection
from hwval_studio.firmware.image import FirmwareImage
from hwval_studio.firmware.openocd import OpenOcdRunner


class HwvalService:
    def __init__(self, client: Client) -> None:
        self.client = client

    def device_info(self) -> dict[str, Any]:
        return self.client.get_device_info()

    def catalogue(self) -> tuple[list[Any], list[Any]]:
        return self.client.load_catalogue()

    def harness(self) -> dict[str, Any]:
        return self.client.load_harness()

    def run(self, selection: Selection, **callbacks: Any) -> RunController:
        return self.client.start_run(selection, **callbacks)

    def results(self) -> list[dict[str, Any]]:
        return self.client.get_results()

    def clear_results(self) -> None:
        self.client.clear_results()

    def report(self) -> dict[str, Any]:
        return self.client.get_report()


class BootService:
    def __init__(self, client: Client) -> None:
        self.client = client

    def info(self) -> dict[str, Any]:
        return self.client.get_boot_info()

    def update(self, image: FirmwareImage, **kwargs: Any) -> dict[str, Any]:
        return self.client.update_image(image, **kwargs)

    def activate(self) -> None:
        self.client.activate()

    def abort(self) -> None:
        self.client.abort_update()


class DemoService:
    def __init__(self, client: Client) -> None:
        self.client = client

    def status(self) -> dict[str, Any]:
        return self.client.get_status()

    def set_led(self, led: int, pattern: int, period_ms: int) -> None:
        self.client.set_led(led, pattern, period_ms)

    def set_led_all(self, pattern: int, period_ms: int) -> None:
        self.client.set_led_all(pattern, period_ms)

    def clear_fault(self) -> None:
        self.client.clear_fault()

    def enter_bootloader(self) -> None:
        self.client.enter_bootloader()


class SwdService:
    """One OpenOCD process per operation; never holds the ST-LINK."""

    def __init__(self, openocd: str = "openocd", log: Any = None) -> None:
        self.openocd = openocd
        self.log = log

    def runner(self) -> OpenOcdRunner:
        return OpenOcdRunner(executable=self.openocd, log=self.log)

    def read_info(self) -> dict[str, Any]:
        runner = self.runner()
        try:
            return runner.read_info()
        finally:
            runner.stop()

    def flash_hwval(self, image: str | Path) -> dict[str, Any]:
        runner = self.runner()
        try:
            return runner.flash_hwval(image)
        finally:
            runner.stop()

    def provision_product(self, boot_image: str | Path) -> dict[str, Any]:
        runner = self.runner()
        try:
            return runner.provision_product(boot_image)
        finally:
            runner.stop()

    def restore_bench(self, hwval_image: str | Path | None = None) -> dict[str, Any]:
        runner = self.runner()
        try:
            return runner.restore_bench(hwval_image)
        finally:
            runner.stop()
