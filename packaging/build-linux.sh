#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
# Prefer the project virtualenv when it exists; callers can override PYTHON.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON=python3
  fi
fi
export HWVAL_STUDIO_GIT_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || true)"
export HWVAL_STUDIO_BUILD_DATE="$(date -u +%F)"
"$PYTHON" scripts/make_icons.py
"$PYTHON" -m PyInstaller packaging/hwval-studio.spec --noconfirm --clean
APP="$ROOT/dist/hwval-studio"
VERSION="$("$PYTHON" -c 'import hwval_studio; print(hwval_studio.__version__)')"

# .deb -----------------------------------------------------------------
DEB="$ROOT/build/deb"
rm -rf "$DEB"
mkdir -p "$DEB/DEBIAN" "$DEB/usr/bin" "$DEB/usr/lib/hwval-studio" \
         "$DEB/usr/share/applications" "$DEB/usr/share/icons/hicolor/scalable/apps" \
         "$DEB/usr/share/hwval-studio" "$DEB/lib/udev/rules.d"
cp -a "$APP/." "$DEB/usr/lib/hwval-studio/"
cat > "$DEB/usr/bin/hwval-studio" <<'LAUNCH'
#!/bin/sh
exec /usr/lib/hwval-studio/hwval-studio "$@"
LAUNCH
chmod +x "$DEB/usr/bin/hwval-studio"
cp packaging/hwval-studio.desktop "$DEB/usr/share/applications/"
cp packaging/hwval-studio.svg "$DEB/usr/share/icons/hicolor/scalable/apps/hwval-studio.svg"
cp packaging/udev/99-stlink.rules "$DEB/lib/udev/rules.d/"
cp packaging/hwval-studio.desktop packaging/README.md "$DEB/usr/share/hwval-studio/"
cat > "$DEB/DEBIAN/control" <<CONTROL
Package: hwval-studio
Version: $VERSION
Section: devel
Priority: optional
Architecture: amd64
Depends: libc6, libx11-6, libxcb1, libgl1, libegl1
Maintainer: Sandesh Ghimire <sandesh@soccentric.com>
Description: HWVAL Studio - STM32F767ZI validation, update and flashing GUI
 Runs HWVAL tests over UART, updates applications through the A/B bootloader
 and flashes/provisions firmware over SWD with OpenOCD.
CONTROL
cat > "$DEB/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
udevadm control --reload-rules || true
udevadm trigger || true
echo "Add your user to the 'dialout' (Debian/Ubuntu) or 'uucp' group to use the serial port:"
echo "  sudo usermod -aG dialout \$USER"
POST
chmod +x "$DEB/DEBIAN/postinst"
if command -v dpkg-deb >/dev/null 2>&1; then
  dpkg-deb --build "$DEB" "$ROOT/dist/hwval-studio_${VERSION}_amd64.deb"
else
  echo "dpkg-deb not found; .deb skipped (staging tree: $DEB). Install dpkg to build it." >&2
fi

# AppImage -------------------------------------------------------------
APPDIR="$ROOT/build/HWVALStudio.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/hwval-studio" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp -a "$APP/." "$APPDIR/usr/lib/hwval-studio/"
cp packaging/hwval-studio.desktop "$APPDIR/usr/share/applications/"
cp packaging/hwval-studio.desktop "$APPDIR/hwval-studio.desktop"
cp packaging/hwval-studio.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/hwval-studio.svg"
cp packaging/hwval-studio.svg "$APPDIR/hwval-studio.svg"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/hwval-studio/hwval-studio" "$@"
RUN
chmod +x "$APPDIR/AppRun"
if command -v appimagetool >/dev/null 2>&1; then
  ARCH=x86_64 appimagetool "$APPDIR" "$ROOT/dist/HWVAL_Studio-${VERSION}-x86_64.AppImage"
else
  echo "appimagetool not found; AppDir is in $APPDIR" >&2
fi
echo "Linux packages written to $ROOT/dist"
