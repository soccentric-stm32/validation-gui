"""Serial port discovery and transport worker exports."""

from __future__ import annotations

from dataclasses import dataclass

from hwval_studio.transport.worker import SerialWorker, is_simulator_port, is_socket_port

STLINK_VID = 0x0483


@dataclass(slots=True)
class PortInfo:
    device: str
    description: str
    hwid: str
    vid: int | None
    pid: int | None
    serial_number: str
    is_stlink: bool = False

    def label(self) -> str:
        suffix = " · ST-LINK" if self.is_stlink else ""
        return f"{self.device} — {self.description}{suffix}"


def list_ports(include_simulators: bool = True) -> list[PortInfo]:
    ports: list[PortInfo] = []
    try:
        from serial.tools import list_ports as serial_ports

        for info in serial_ports.comports():
            ports.append(
                PortInfo(
                    device=info.device,
                    description=info.description or info.device,
                    hwid=info.hwid or "",
                    vid=info.vid,
                    pid=info.pid,
                    serial_number=info.serial_number or "",
                    is_stlink=info.vid == STLINK_VID,
                )
            )
    except Exception:
        pass
    ports.sort(key=lambda port: (not port.is_stlink, port.device))
    if include_simulators:
        for role, name in (
            ("hwval", "HWVAL validation"),
            ("boot", "BOOTLOADER"),
            ("demo", "DEMO application"),
        ):
            ports.append(
                PortInfo(
                    device=f"simulator:{role}",
                    description=f"Device simulator — {name}",
                    hwid="simulator",
                    vid=None,
                    pid=None,
                    serial_number="",
                    is_stlink=False,
                )
            )
    return ports


__all__ = ["PortInfo", "SerialWorker", "is_simulator_port", "is_socket_port", "list_ports"]
