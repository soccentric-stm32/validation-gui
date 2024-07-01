"""OpenOCD process control for flashing and provisioning (SRS section 10).

Every operation starts a fresh OpenOCD process and stops it when the operation
ends so the ST-LINK is released (ARC-003, HWVAL CL-006).  Output is streamed to
the caller line by line.  No function in this module writes RDP, WRP or
BOOT_ADD (SWD-007); only nDBANK/nDBOOT are changed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, QProcessEnvironment

FLASH_OPTCR = 0x40023C14
FLASH_OPTCR1 = 0x40023C18
FLASH_KEYR = 0x40023C04
FLASH_OPTKEYR = 0x40023C08
FLASH_SR = 0x40023C0C
FLASH_CR = 0x40023C10
DBGMCU_IDCODE = 0xE0042000
FLASH_SIZE_REG = 0x1FF0F442

RDP_MASK = 0xFF00
WRP1_MASK = 0x0FFF0000
NDBOOT = 1 << 28
NDBANK = 1 << 29


class OpenOcdError(RuntimeError):
    """OpenOCD failed to start, exited, timed out or reported an error."""


@dataclass(slots=True)
class OptionBytes:
    optcr: int = 0
    optcr1: int = 0
    raw: dict[str, int] = field(default_factory=dict)

    @property
    def rdp(self) -> int:
        return (self.optcr >> 8) & 0xFF

    @property
    def bor_level(self) -> int:
        return (self.optcr >> 2) & 0x3

    @property
    def ndbank(self) -> int:
        return (self.optcr >> 29) & 0x1

    @property
    def ndboot(self) -> int:
        return (self.optcr >> 28) & 0x1

    @property
    def bank1_wrp(self) -> int:
        return (self.optcr >> 16) & 0xFFF

    @property
    def bank2_wrp(self) -> int:
        return self.optcr1 & 0xFFF

    @property
    def flash_mode(self) -> str:
        return "SINGLE_BANK" if self.ndbank else "DUAL_BANK"

    def as_dict(self) -> dict[str, int | str]:
        return {
            "OPTCR": self.optcr,
            "OPTCR1": self.optcr1,
            "RDP": self.rdp,
            "BOR_LEV": self.bor_level,
            "nDBANK": self.ndbank,
            "nDBOOT": self.ndboot,
            "WRP_BANK1": self.bank1_wrp,
            "WRP_BANK2": self.bank2_wrp,
            "flash_mode": self.flash_mode,
        }


def find_openocd(preferred: str = "") -> str | None:
    if preferred:
        path = Path(preferred).expanduser()
        if path.is_file():
            return str(path)
        found = shutil.which(preferred)
        if found:
            return found
        return None
    return shutil.which("openocd")


def openocd_version(executable: str) -> str:
    try:
        out = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OpenOcdError(f"cannot run OpenOCD: {exc}") from exc
    text = (out.stdout or "") + (out.stderr or "")
    match = re.search(r"(\d+)\.(\d+)", text)
    if not match:
        raise OpenOcdError(f"cannot parse OpenOCD version from: {text.strip()[:120]}")
    return f"{match.group(1)}.{match.group(2)}"


def version_supported(version: str) -> bool:
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= (0, 12)


def install_hint() -> str:
    return (
        "OpenOCD 0.12 or newer is required.\n\n"
        "macOS:   brew install openocd\n"
        "Windows: winget install OpenOCD.OpenOCD  (or xPack OpenOCD)\n"
        "Linux:   sudo apt install openocd   /   sudo dnf install openocd\n\n"
        "Set an explicit path in Preferences > Firmware if it is not on PATH."
    )


def _parse_mdw(output: str, address: int) -> int | None:
    pattern = re.compile(rf"0x{address:08X}:\s*((?:0x)?[0-9A-Fa-f]+)", re.IGNORECASE)
    match = pattern.search(output)
    if match:
        value = match.group(1)
        return int(value, 16)
    # The address may be printed with a different case / spacing.
    for line in output.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        try:
            line_address = int(left.strip().split()[-1], 16)
        except (ValueError, IndexError):
            continue
        if line_address == address:
            token = right.strip().split()[0]
            try:
                return int(token, 16)
            except (ValueError, IndexError):
                return None
    return None


def parse_option_output(output: str, *, optcr: int = 0, optcr1: int = 0) -> OptionBytes:
    raw: dict[str, int] = {"OPTCR": optcr, "OPTCR1": optcr1}
    match = re.search(r"user_options\s+0x([0-9A-Fa-f]+)", output)
    if match:
        # OpenOCD 0.12 prints a 12-bit view, not OPTCR: bits 0-7 are OPTCR
        # bits 0-7 and bits 8-11 are OPTCR bits 28-31 (nDBOOT, nDBANK,
        # DB1M, SPRMOD). RDP and WRP are not included. Only use it to
        # rebuild OPTCR when the raw register read was not available.
        user = int(match.group(1), 16)
        raw["USER_OPTIONS"] = user
        if not optcr:
            optcr = (user & 0x0FF) | ((user & 0xF00) << 20)
            raw["OPTCR"] = optcr
    match = re.search(r"boot_add0\s+0x([0-9A-Fa-f]+)", output)
    if match:
        raw["BOOT_ADD0"] = int(match.group(1), 16)
    match = re.search(r"boot_add1\s+0x([0-9A-Fa-f]+)", output)
    if match:
        raw["BOOT_ADD1"] = int(match.group(1), 16)
    match = re.search(r"nWRP\s+0x([0-9A-Fa-f]+)", output)
    if match:
        raw["nWRP"] = int(match.group(1), 16)
    match = re.search(r"RDP\s+(?:0x)?([0-9A-Fa-f]+)", output)
    if match:
        raw["RDP"] = int(match.group(1), 16)
    return OptionBytes(optcr=optcr, optcr1=optcr1, raw=raw)


class OpenOcdRunner:
    """Runs one OpenOCD process with a list of Tcl commands."""

    def __init__(
        self,
        *,
        executable: str = "openocd",
        interface_cfg: str = "interface/stlink.cfg",
        target_cfg: str = "target/stm32f7x.cfg",
        extra_args: list[str] | None = None,
        log: Any = None,
    ) -> None:
        self.executable = executable
        self.interface_cfg = interface_cfg
        self.target_cfg = target_cfg
        self.extra_args = extra_args or []
        self.log = log
        self.process: QProcess | None = None
        self.output = ""
        self._lines: list[str] = []

    def _emit(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        self._lines.append(line)
        if self.log:
            self.log(line)

    def run(self, commands: list[str], *, timeout: float = 120.0, shutdown: bool = True) -> str:
        args: list[str] = []
        if self.interface_cfg:
            args += ["-f", self.interface_cfg]
        if self.target_cfg:
            args += ["-f", self.target_cfg]
        args += self.extra_args
        for command in commands:
            args += ["-c", command]
        if shutdown:
            args += ["-c", "shutdown"]
        self._emit("$ " + " ".join([self.executable, *args]))
        process = QProcess()
        self.process = process
        env = QProcessEnvironment.systemEnvironment()
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.start(self.executable, args)
        if not process.waitForStarted(5000):
            self.process = None
            raise OpenOcdError(f"cannot start OpenOCD ({self.executable}): {process.errorString()}")
        started = time.monotonic()
        pending = ""
        try:
            while True:
                if process.waitForReadyRead(100):
                    chunk = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
                    pending += chunk
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        self._emit(line)
                if process.state() == QProcess.ProcessState.NotRunning:
                    break
                if time.monotonic() - started > timeout:
                    process.kill()
                    process.waitForFinished(2000)
                    raise OpenOcdError(f"OpenOCD timed out after {timeout:.0f}s: {pending[-500:]}")
            remaining = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
            if remaining:
                pending += remaining
            for line in pending.splitlines():
                self._emit(line)
            self.output = "\n".join(self._lines)
            exit_code = process.exitCode()
            if exit_code != 0:
                raise OpenOcdError(f"OpenOCD exited with code {exit_code}: {self.output[-800:]}")
            if re.search(r"(?m)^Error:", self.output):
                raise OpenOcdError(self.output[-1000:])
            return self.output
        finally:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(2000)
            self.process = None
            self._lines = []
            # OpenOCD is stopped for every operation so the probe is free.
            time.sleep(0.05)

    def stop(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.waitForFinished(2000)
            self.process = None

    # -- high level ----------------------------------------------------
    def read_info(self) -> dict[str, Any]:
        commands = [
            "init",
            "reset halt",
            f"mdw 0x{DBGMCU_IDCODE:08X} 1",
            f"mdw 0x{FLASH_SIZE_REG:08X} 1",
            f"mdw 0x{FLASH_OPTCR:08X} 1",
            f"mdw 0x{FLASH_OPTCR1:08X} 1",
            "flash probe 0",
        ]
        output = self.run(commands, timeout=30.0)
        idcode = _parse_mdw(output, DBGMCU_IDCODE) or 0
        dev_id = idcode & 0xFFF
        rev_id = (idcode >> 16) & 0xFFFF
        flash_kb = _parse_mdw(output, FLASH_SIZE_REG) or 0
        if not flash_kb:
            match = re.search(r"flash size\s*=\s*(\d+)\s*k", output, re.IGNORECASE)
            if match:
                flash_kb = int(match.group(1))
        optcr = _parse_mdw(output, FLASH_OPTCR) or 0
        optcr1 = _parse_mdw(output, FLASH_OPTCR1) or 0
        options = OptionBytes(optcr=optcr, optcr1=optcr1, raw={"OPTCR": optcr, "OPTCR1": optcr1})
        return {
            "dev_id": dev_id,
            "dev_id_hex": f"{dev_id:03X}",
            "rev_id": rev_id,
            "rev_id_hex": f"{rev_id:04X}",
            "flash_size_kb": flash_kb,
            "optcr": optcr,
            "optcr1": optcr1,
            "options": options.as_dict(),
            "probe": "stlink",
            "target": "stm32f7x",
            "output": output,
        }

    def read_option_bytes(self) -> OptionBytes:
        # Read the raw registers. "stm32f2x options_read" is not OPTCR: it
        # prints a 12-bit user_options value without RDP/WRP, so parsing it
        # as OPTCR made nDBANK/nDBOOT read as 0 and the write path refuse
        # the (bogus) RDP change.
        output = self.run(
            [
                "init",
                "reset halt",
                f"mdw 0x{FLASH_OPTCR:08X} 1",
                f"mdw 0x{FLASH_OPTCR1:08X} 1",
            ],
            timeout=20.0,
        )
        optcr = _parse_mdw(output, FLASH_OPTCR)
        optcr1 = _parse_mdw(output, FLASH_OPTCR1)
        if optcr is None or optcr1 is None:
            # Last resort: decode the OpenOCD view (no RDP/WRP).
            output = self.run(
                ["init", "reset halt", "stm32f2x options_read 0"], timeout=20.0
            )
            return parse_option_output(output, optcr=optcr or 0, optcr1=optcr1 or 0)
        options = OptionBytes(
            optcr=optcr, optcr1=optcr1, raw={"OPTCR": optcr, "OPTCR1": optcr1}
        )
        # BOOT_ADD0/1 only come from options_read; keep them for the write.
        try:
            text = self.run(["init", "reset halt", "stm32f2x options_read 0"], timeout=20.0)
        except OpenOcdError:
            return options
        for key, value in parse_option_output(text).raw.items():
            if key.startswith("BOOT_ADD"):
                options.raw[key] = value
        return options

    def write_option_bytes(
        self,
        optcr: int,
        optcr1: int,
        *,
        boot_add0: int = 0x0080,
        boot_add1: int = 0x0040,
    ) -> None:
        # Never write RDP or WRP through this path (SWD-007).
        if ((optcr >> 8) & 0xFF) not in (0, 0xAA) and ((optcr >> 8) & 0xFF) != 0xCC:
            raise OpenOcdError("refusing to change RDP; only nDBANK/nDBOOT may be written")
        # OpenOCD 0.12 on F7 takes <bank> <user_options> <boot_add0>
        # <boot_add1>, where user_options is the same 12-bit view used by
        # options_read. RDP/WRP are preserved by OpenOCD itself.
        user_options = (optcr & 0x0FF) | ((optcr >> 20) & 0xF00)
        commands = [
            "init",
            "reset halt",
            (
                f"stm32f2x options_write 0 0x{user_options:03X} "
                f"0x{boot_add0:04X} 0x{boot_add1:04X}"
            ),
        ]
        try:
            self.run(commands, timeout=45.0)
            actual = self.read_option_bytes()
            if (actual.optcr & (NDBANK | NDBOOT)) == (optcr & (NDBANK | NDBOOT)):
                return
        except OpenOcdError:
            pass
        # Register fallback for OpenOCD builds without the F7 options_write
        # argument set (OPEN-G04).  Only the two bank bits differ.
        registers = [
            "init",
            "reset halt",
            f"mww 0x{FLASH_OPTKEYR:08X} 0x08192A3B",
            f"mww 0x{FLASH_OPTKEYR:08X} 0x4C5D6E7F",
            f"mww 0x{FLASH_OPTCR:08X} 0x{optcr & ~0x1:08X}",
            f"mww 0x{FLASH_OPTCR1:08X} 0x{optcr1:08X}",
            f"mww 0x{FLASH_OPTCR:08X} 0x{(optcr & ~0x1) | 0x2:08X}",
            "sleep 100",
            f"mww 0x{FLASH_OPTCR:08X} 0x{optcr | 0x1:08X}",
            "reset halt",
        ]
        output = self.run(registers, timeout=45.0)
        actual = self.read_option_bytes()
        if (actual.optcr & (NDBANK | NDBOOT)) != (optcr & (NDBANK | NDBOOT)):
            raise OpenOcdError(
                "option-byte read-back failed; set nDBANK/nDBOOT with STM32CubeProgrammer "
                f"(OPEN-G04). OpenOCD output: {output[-400:]}"
            )

    def ensure_flash_mode(self, single_bank: bool) -> bool:
        current = self.read_option_bytes()
        wanted_bank = 1 if single_bank else 0
        wanted_boot = 1  # dual boot disabled in both bench and product configurations
        if current.ndbank == wanted_bank and current.ndboot == wanted_boot:
            return False
        new = current.optcr
        new &= ~(NDBANK | NDBOOT)
        if wanted_bank:
            new |= NDBANK
        if wanted_boot:
            new |= NDBOOT
        # Preserve every other bit, including RDP, WRP and BOOT_ADD1 (the
        # ST system-memory recovery path). Reset defaults are used when the
        # options_read output was unavailable.
        self.write_option_bytes(
            new,
            current.optcr1,
            boot_add0=int(current.raw.get("BOOT_ADD0", 0x0080)),
            boot_add1=int(current.raw.get("BOOT_ADD1", 0x0040)),
        )
        return True

    def mass_erase(self) -> None:
        try:
            self.run(["init", "reset halt", "stm32f2x mass_erase 0"], timeout=180.0)
        except OpenOcdError:
            self.run(
                [
                    "init",
                    "reset halt",
                    "flash erase_address 0x08000000 0x00200000",
                ],
                timeout=180.0,
            )

    def program(self, path: str | Path, *, verify: bool = True, reset: bool = True) -> None:
        p = Path(path)
        if not p.is_file():
            raise OpenOcdError(f"firmware file not found: {p}")
        command = f'program "{p.resolve()}"'
        if p.suffix.lower() == ".bin":
            # A raw .bin carries no address; SWD-003 puts firmware at flash.
            command += " 0x08000000"
        if verify:
            command += " verify"
        if reset:
            command += " reset run"
        self.run(["init", "reset halt", command], timeout=240.0)

    def flash_hwval(self, image: str | Path) -> dict[str, Any]:
        changed = self.ensure_flash_mode(single_bank=True)
        self.mass_erase()
        self.program(image, verify=True, reset=True)
        info = self.read_info()
        info["option_bytes_changed"] = changed
        return info

    def provision_product(self, boot_image: str | Path) -> dict[str, Any]:
        changed = self.ensure_flash_mode(single_bank=False)
        self.mass_erase()
        self.program(boot_image, verify=True, reset=True)
        info = self.read_info()
        info["option_bytes_changed"] = changed
        return info

    def restore_bench(self, hwval_image: str | Path | None = None) -> dict[str, Any]:
        changed = self.ensure_flash_mode(single_bank=True)
        self.mass_erase()
        if hwval_image:
            self.program(hwval_image, verify=True, reset=True)
        else:
            self.run(["init", "reset halt", "reset run"], timeout=20.0)
        info = self.read_info()
        info["option_bytes_changed"] = changed
        return info
