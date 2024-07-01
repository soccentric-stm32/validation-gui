"""Firmware image parsing and validation (SRS-BOOT-F767 section 5.1).

The GUI validates an image locally before uploading it (FW-002).  The 256-byte
header is the one BOOT stores in its metadata sector, so the GUI and BOOT agree
byte for byte.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAGIC = 0x48574249  # "IBWH" little-endian
HEADER_VERSION = 1
HEADER_SIZE = 256
IMAGE_TYPE_APPLICATION = 1
LOAD_ADDRESS = 0x0800C000
SLOT_SIZE = 0x000F4000  # 976 KB
RAM_START = 0x20000000
RAM_END = 0x20080000

IMAGE_HEADER = struct.Struct("<IHHIIIIIII20s32s164sI")


class ImageError(RuntimeError):
    """Invalid or unsupported firmware image."""


@dataclass(slots=True)
class FirmwareImage:
    path: Path
    header: dict[str, Any]
    body: bytes
    sha256: str
    warnings: list[str] = field(default_factory=list)

    @property
    def version(self) -> int:
        return int(self.header.get("version", 0))

    @property
    def version_text(self) -> str:
        value = self.version
        return f"{(value >> 24) & 0xFF}.{(value >> 16) & 0xFF}.{value & 0xFF}"

    @property
    def name(self) -> str:
        return str(self.header.get("name", ""))

    @property
    def size(self) -> int:
        return len(self.body)

    @property
    def crc32(self) -> int:
        return int(self.header.get("image_crc32", 0))

    def header_dict(self) -> dict[str, Any]:
        return dict(self.header)

    def describe(self) -> str:
        return (
            f"{self.name or self.path.name} {self.version_text}, "
            f"{self.size} bytes, CRC 0x{self.crc32:08X}"
        )

    def to_metadata(self) -> dict[str, Any]:
        return dict(self.header)


def _parse_header(path: Path, raw: bytes) -> tuple[dict[str, Any], bytes]:
    if len(raw) < HEADER_SIZE:
        raise ImageError(f"{path.name}: shorter than a {HEADER_SIZE}-byte image header")
    (
        magic,
        header_version,
        header_size,
        image_type,
        version,
        image_size,
        image_crc32,
        load_address,
        entry_address,
        build_timestamp,
        git_commit,
        name,
        _reserved,
        header_crc32,
    ) = IMAGE_HEADER.unpack_from(raw, 0)
    header = {
        "magic": magic,
        "header_version": header_version,
        "header_size": header_size,
        "image_type": image_type,
        "version": version,
        "image_size": image_size,
        "image_crc32": image_crc32,
        "load_address": load_address,
        "entry_address": entry_address,
        "build_timestamp": build_timestamp,
        "git_commit": git_commit,
        "name": name.rstrip(b"\x00").decode("ascii", "replace"),
        "header_crc32": header_crc32,
    }
    body = raw[HEADER_SIZE:]
    if magic != MAGIC:
        raise ImageError(f"{path.name}: bad image magic (0x{magic:08X})")
    if header_version != HEADER_VERSION:
        raise ImageError(f"{path.name}: unsupported header version {header_version}")
    if header_size != HEADER_SIZE:
        raise ImageError(f"{path.name}: unsupported header size {header_size}")
    if image_type != IMAGE_TYPE_APPLICATION:
        raise ImageError(f"{path.name}: unsupported image type {image_type}")
    if load_address != LOAD_ADDRESS:
        raise ImageError(
            f"{path.name}: load address 0x{load_address:08X} is not 0x{LOAD_ADDRESS:08X}"
        )
    if image_size > SLOT_SIZE:
        raise ImageError(f"{path.name}: image size {image_size} exceeds the 976 KB slot")
    if zlib.crc32(raw[:252]) & 0xFFFFFFFF != header_crc32:
        raise ImageError(f"{path.name}: header CRC32 mismatch")
    if len(body) != image_size:
        raise ImageError(
            f"{path.name}: image_size {image_size} does not match the file body ({len(body)} bytes)"
        )
    if zlib.crc32(body) & 0xFFFFFFFF != image_crc32:
        raise ImageError(f"{path.name}: image CRC32 mismatch")
    return header, body


def validate_vectors(path: Path, body: bytes) -> None:
    if len(body) < 8:
        raise ImageError(f"{path.name}: image is too small for a vector table")
    sp, entry = struct.unpack_from("<II", body, 0)
    if not (RAM_START < sp <= RAM_END) or (sp & 0x7):
        raise ImageError(f"{path.name}: initial stack pointer 0x{sp:08X} is not in internal RAM")
    entry_addr = entry & ~1
    if not (entry & 1) or not (LOAD_ADDRESS <= entry_addr < LOAD_ADDRESS + SLOT_SIZE):
        raise ImageError(f"{path.name}: reset vector 0x{entry:08X} is outside the slot")


def parse_image(path: str | Path) -> FirmwareImage:
    p = Path(path)
    if not p.is_file():
        raise ImageError(f"image not found: {p}")
    raw = p.read_bytes()
    header, body = _parse_header(p, raw)
    warnings: list[str] = []
    try:
        validate_vectors(p, body)
    except ImageError as exc:
        warnings.append(str(exc))
    return FirmwareImage(
        path=p,
        header=header,
        body=body,
        sha256=hashlib.sha256(raw).hexdigest(),
        warnings=warnings,
    )


def build_image(
    payload: bytes,
    *,
    version: str = "0.1.0",
    name: str = "stm32-application",
    commit: str = "",
    timestamp: int = 0,
) -> bytes:
    """Build a BOOT image (used by tests and developers; not the firmware)."""
    parts = version.split(".")
    if len(parts) != 3:
        raise ImageError("version must be major.minor.patch")
    version_value = (
        ((int(parts[0]) & 0xFF) << 24)
        | ((int(parts[1]) & 0xFF) << 16)
        | (int(parts[2]) & 0xFF)
    )
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<I", header, 0, MAGIC)
    struct.pack_into("<H", header, 4, HEADER_VERSION)
    struct.pack_into("<H", header, 6, HEADER_SIZE)
    struct.pack_into("<I", header, 8, IMAGE_TYPE_APPLICATION)
    struct.pack_into("<I", header, 12, version_value)
    struct.pack_into("<I", header, 16, len(payload))
    struct.pack_into("<I", header, 20, zlib.crc32(payload) & 0xFFFFFFFF)
    struct.pack_into("<I", header, 24, LOAD_ADDRESS)
    entry = struct.unpack_from("<I", payload, 4)[0] if len(payload) >= 8 else 0
    struct.pack_into("<I", header, 28, entry)
    struct.pack_into("<I", header, 32, timestamp)
    commit_bytes = bytes(20)
    if commit:
        try:
            commit_bytes = bytes.fromhex(commit[:40])
        except ValueError:
            commit_bytes = commit[:20].encode("ascii", "replace").ljust(20, b"\x00")
    header[36:56] = commit_bytes
    header[56:88] = name.encode("ascii", "replace")[:32].ljust(32, b"\x00")
    struct.pack_into("<I", header, 252, zlib.crc32(header[:252]) & 0xFFFFFFFF)
    return bytes(header) + payload


def compare_versions(image: FirmwareImage, slot: dict[str, Any]) -> list[str]:
    """Warnings required by FW-008."""
    warnings: list[str] = []
    if not slot.get("present"):
        return warnings
    slot_version = int(slot.get("version", 0))
    if image.version <= slot_version:
        warnings.append(
            f"image version {image.version_text} is not newer than the active slot "
            f"({slot.get('version_text', '0.0.0')})"
        )
    slot_name = str(slot.get("name", ""))
    if slot_name and image.name and image.name != slot_name:
        warnings.append(
            f"image name '{image.name}' differs from the active slot name '{slot_name}'"
        )
    return warnings
