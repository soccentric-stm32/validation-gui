#!/usr/bin/env python3
"""Render the SVG master into PNG/ICO/ICNS app icon sources (ICN-001)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "packaging" / "hwval-studio.svg"
OUT = ROOT / "packaging"


def main() -> int:
    from PySide6.QtCore import QByteArray, QSize, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(SVG.read_bytes()))
    sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    images = {}
    for size in sizes:
        image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        image.save(str(OUT / f"hwval-studio-{size}.png"))
        images[size] = image
    try:
        from PIL import Image

        ico = Image.open(str(OUT / "hwval-studio-256.png"))
        ico.save(str(OUT / "hwval-studio.ico"), sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    except Exception as exc:
        print(f"ico not generated: {exc}", file=sys.stderr)
    if sys.platform == "darwin":
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "hwval-studio.iconset"
            iconset.mkdir()
            for size in (16, 32, 128, 256, 512):
                images[size].save(str(iconset / f"icon_{size}x{size}.png"))
                # @2x must be the double-size bitmap, not a copy of 1x.
                images[size * 2].save(str(iconset / f"icon_{size}x{size}@2x.png"))
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "hwval-studio.icns")], check=False)
    print(f"icons written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
