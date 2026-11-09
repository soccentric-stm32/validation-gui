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
VERSION="$("$PYTHON" -c 'import hwval_studio; print(hwval_studio.__version__)')"
APP="$ROOT/dist/hwval-studio.app"
if [ ! -d "$APP" ]; then
  # On macOS PyInstaller creates a .app bundle when windowed=True; the
  # one-folder output is wrapped here if only a folder was produced.
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  cp -a "$ROOT/dist/hwval-studio/." "$APP/Contents/MacOS/"
  cp packaging/hwval-studio.icns "$APP/Contents/Resources/" 2>/dev/null || true
  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>hwval-studio</string>
<key>CFBundleIdentifier</key><string>com.soccentric.hwval-studio</string>
<key>CFBundleName</key><string>HWVAL Studio</string>
<key>CFBundleShortVersionString</key><string>${VERSION}</string>
<key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
PLIST
fi
DMG="$ROOT/dist/HWVAL_Studio-${VERSION}.dmg"
STAGE="$ROOT/build/dmg"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "HWVAL Studio" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "macOS package: $DMG"
