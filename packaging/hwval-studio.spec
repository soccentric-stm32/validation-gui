# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Relative paths in a PyInstaller spec are resolved against the spec file, not
# the directory the build is started from. Derive the repository root from
# SPECPATH so the build works from any working directory.
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
sys.path.insert(0, os.path.join(ROOT, "src"))

datas = collect_data_files("hwval_studio")
datas += [(os.path.join(ROOT, "protocol", "hwlink.fbs"), "protocol")]
hiddenimports = collect_submodules("hwval_studio.protocol.generated.hwlink")
hiddenimports += ["flatbuffers", "serial", "serial.tools.list_ports"]

# The launcher icon has to be the native format: scripts/make_icons.py writes an
# .ico on Windows (via Pillow) and an .icns on macOS (via iconutil).  PyInstaller
# rejects a foreign format on both platforms.
ICON = {
    "win32": os.path.join(ROOT, "packaging", "hwval-studio.ico"),
    "darwin": os.path.join(ROOT, "packaging", "hwval-studio.icns"),
}.get(sys.platform)
if ICON is None or not os.path.exists(ICON):
    ICON = None

a = Analysis(
    [os.path.join(ROOT, "src", "hwval_studio", "app.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # flatbuffers.compat imports numpy when it is installed, so the analysis
    # dragged numpy, numpy.libs and yaml into the bundle; the app never uses them.
    excludes=["tkinter", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hwval-studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="hwval-studio",
)
