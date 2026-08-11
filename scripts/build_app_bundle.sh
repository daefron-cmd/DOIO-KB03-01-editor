#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/dist/DOIO KB03-01.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
EXEC="$MACOS/DOIOKB03"
ICON_SRC="$ROOT/pictures/icon.png"
ICONSET="$ROOT/dist/DOIOKB03.iconset"
PYTHON="$ROOT/.venv/bin/python3"
INSTALL=0
BUNDLE_ID="io.github.daefron-cmd.doio-kb03-01"

if [[ "${1:-}" == "--install" ]]; then
    INSTALL=1
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "$PYTHON is missing; run 'uv sync' before building the app" >&2
    exit 1
fi

VERSION="$(PYTHONPATH="$ROOT" "$PYTHON" -c 'from version import APP_VERSION; print(APP_VERSION)')"

PYTHON_INCLUDE="$($PYTHON -c 'import sysconfig; print(sysconfig.get_config_var("INCLUDEPY"))')"
PYTHON_LIBDIR="$($PYTHON -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
PYTHON_LIBRARY="$($PYTHON -c 'import sysconfig; print(sysconfig.get_config_var("LDLIBRARY"))')"
if [[ ! -f "$PYTHON_INCLUDE/Python.h" || ! -f "$PYTHON_LIBDIR/$PYTHON_LIBRARY" ]]; then
    echo "Python embedding headers or library are missing" >&2
    exit 1
fi

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"

/usr/libexec/PlistBuddy -c "Clear dict" "$CONTENTS/Info.plist" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDevelopmentRegion string en" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string DOIO KB03-01" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable string DOIOKB03" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string DOIOKB03" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleInfoDictionaryVersion string 6.0" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleName string DOIO KB03-01" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundlePackageType string APPL" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleSupportedPlatforms array" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleSupportedPlatforms:0 string MacOSX" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 1" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 13.0" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSInputMonitoringUsageDescription string DOIO KB03-01 reads keyboard HID reports to highlight macropad key presses." "$CONTENTS/Info.plist"

rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ICON_SRC" \
        --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z "$((size * 2))" "$((size * 2))" "$ICON_SRC" \
        --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
/usr/bin/python3 "$ROOT/scripts/png_to_icns.py" "$ICONSET" "$RESOURCES/DOIOKB03.icns"
rm -rf "$ICONSET"

printf '%s\n' "$ROOT" > "$RESOURCES/project-root.txt"
clang -std=c11 -Wall -Wextra -Werror \
    -I"$PYTHON_INCLUDE" \
    "$ROOT/scripts/macos_launcher.c" \
    "$PYTHON_LIBDIR/$PYTHON_LIBRARY" \
    -o "$EXEC"
printf '%s' 'APPL????' > "$CONTENTS/PkgInfo"
codesign --force --sign - "$APP" >/dev/null

touch "$APP"
if [[ "$INSTALL" -eq 1 ]]; then
    rm -rf "/Applications/DOIO KB03-01.app"
    cp -R "$APP" /Applications/
    touch "/Applications/DOIO KB03-01.app"
    echo "/Applications/DOIO KB03-01.app"
fi
echo "$APP"
