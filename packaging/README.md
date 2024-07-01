# Packaging HWVAL Studio

The application is built with PyInstaller in **one-folder** mode on each
operating system (PKG-001, PKG-002). Packages include the generated protocol
code, the SVG icons, the Inter and JetBrains Mono fonts with their OFL
licences, the help documents and the HWVAL test catalogue.

## Build

```bash
python -m pip install -e ".[packaging]"
python scripts/make_icons.py
pyinstaller packaging/hwval-studio.spec --noconfirm --clean
```

Artifacts appear in `dist/hwval-studio/`.

### Linux

```bash
packaging/build-linux.sh          # AppImage + .deb (if the tools exist)
```

The `.deb` installs the ST-LINK udev rule and documents adding the user to
`dialout`/`uucp` (PKG-006).

### macOS

```bash
packaging/build-macos.sh          # .app and .dmg
```

The `.dmg` opens with a drag-to-Applications layout. Signing/notarisation is
left to the release owner (OPEN-G03).

### Windows

```powershell
packaging\build-windows.ps1       # one-folder build and .msi (WiX)
```

The MSI adds a Start-menu entry and an uninstaller and needs WiX v4 (`wix
build`); without `wix` on `PATH` the script still writes the one-folder build to
`dist\hwval-studio\`. `make package` runs the script from Git Bash and uses the
virtualenv interpreter (`.venv\Scripts\python.exe`), which `make install`
creates with the `[dev,packaging]` extras. Signing is left to the release owner
(OPEN-G03).

## Icons

`scripts/make_icons.py` renders `packaging/hwval-studio.svg` into PNG sizes,
`hwval-studio.ico` (Pillow) and, on macOS, the iconset used by `iconutil`.
The SVG master is the only source; raster files are generated at build time
(ICN-001).

## Direct source run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
python -m hwval_studio
```

`pyproject.toml` pins the dependency ranges (PKG-007).
