#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/dist/DOIO KB03-01.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
EXEC="$MACOS/DOIOKB03"

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"

/usr/libexec/PlistBuddy -c "Clear dict" "$CONTENTS/Info.plist" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDevelopmentRegion string en" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string DOIO KB03-01" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable string DOIOKB03" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string local.usb-probe.kb03" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleInfoDictionaryVersion string 6.0" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleName string DOIO KB03-01" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundlePackageType string APPL" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 0.1.0" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleSupportedPlatforms array" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleSupportedPlatforms:0 string MacOSX" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 1" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 13.0" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSInputMonitoringUsageDescription string DOIO KB03-01 reads keyboard HID reports to highlight macropad key presses." "$CONTENTS/Info.plist"

printf '%s\n' "$ROOT" > "$RESOURCES/project-root.txt"
clang "$ROOT/scripts/macos_launcher.c" -o "$EXEC"
printf '%s' 'APPL????' > "$CONTENTS/PkgInfo"
codesign --force --sign - "$APP" >/dev/null

touch "$APP"
echo "$APP"
