#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python3"
OUTPUT_ROOT="$ROOT/dist/releases"
BUILD_ROOT="$ROOT/dist/release-build"
APP="$OUTPUT_ROOT/DOIO KB03-01.app"
ICONSET="$BUILD_ROOT/DOIOKB03.iconset"
ICON="$BUILD_ROOT/DOIOKB03.icns"
LICENSES="$BUILD_ROOT/third-party-licenses"
SPEC="$ROOT/scripts/doio_kb03.spec"

if [[ ! -x "$PYTHON" ]]; then
    echo "$PYTHON is missing; run 'uv sync --group package' first" >&2
    exit 1
fi

VERSION="$(PYTHONPATH="$ROOT" "$PYTHON" -c 'from version import APP_VERSION; print(APP_VERSION)')"
ARCH="$(uname -m)"
case "$ARCH" in
    arm64|x86_64) ;;
    *)
        echo "unsupported release architecture: $ARCH" >&2
        exit 1
        ;;
esac

if [[ -n "${GITHUB_REF_NAME:-}" && "$GITHUB_REF_NAME" != "v$VERSION" ]]; then
    echo "tag $GITHUB_REF_NAME does not match application version v$VERSION" >&2
    exit 1
fi

ARCHIVE_NAME="DOIO-KB03-01-v${VERSION}-macOS-${ARCH}.zip"
ARCHIVE="$OUTPUT_ROOT/$ARCHIVE_NAME"
CHECKSUM="$ARCHIVE.sha256"

for target in "$BUILD_ROOT" "$APP" "$ARCHIVE" "$CHECKSUM"; do
    case "$target" in
        "$ROOT"/dist/*) ;;
        *)
            echo "refusing unsafe build target: $target" >&2
            exit 1
            ;;
    esac
    if [[ -L "$target" ]]; then
        echo "refusing to replace symlink: $target" >&2
        exit 1
    fi
done

rm -rf -- "$BUILD_ROOT" "$APP"
rm -f -- "$ARCHIVE" "$CHECKSUM"
mkdir -p "$OUTPUT_ROOT" "$ICONSET"

for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ROOT/pictures/icon.png" \
        --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z "$((size * 2))" "$((size * 2))" "$ROOT/pictures/icon.png" \
        --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
/usr/bin/python3 "$ROOT/scripts/png_to_icns.py" "$ICONSET" "$ICON"
"$PYTHON" "$ROOT/scripts/collect_licenses.py" "$LICENSES"

DOIO_PROJECT_ROOT="$ROOT" \
DOIO_VERSION="$VERSION" \
DOIO_ICON="$ICON" \
DOIO_LICENSES="$LICENSES" \
DOIO_TARGET_ARCH="$ARCH" \
PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/pyinstaller-cache" \
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/doio-kb03-uv-cache}" \
uv run --frozen --group package pyinstaller \
    --noconfirm \
    --clean \
    --distpath "$OUTPUT_ROOT" \
    --workpath "$BUILD_ROOT/pyinstaller" \
    "$SPEC"

EXEC="$APP/Contents/MacOS/DOIOKB03"
if [[ ! -x "$EXEC" ]]; then
    echo "release executable was not created: $EXEC" >&2
    exit 1
fi

EXPECTED_VERSION="DOIO KB03-01 $VERSION"
ACTUAL_VERSION="$("$EXEC" --version)"
if [[ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]]; then
    echo "release version mismatch: expected '$EXPECTED_VERSION', got '$ACTUAL_VERSION'" >&2
    exit 1
fi
"$EXEC" --self-test

PLIST="$APP/Contents/Info.plist"
plutil -lint "$PLIST" >/dev/null
PLIST_VERSION="$(plutil -extract CFBundleShortVersionString raw "$PLIST")"
if [[ "$PLIST_VERSION" != "$VERSION" ]]; then
    echo "Info.plist version mismatch: expected $VERSION, got $PLIST_VERSION" >&2
    exit 1
fi
codesign --verify --deep --strict --verbose "$APP"

ditto -c -k --sequesterRsrc --keepParent "$APP" "$ARCHIVE"
unzip -tq "$ARCHIVE"
(
    cd "$OUTPUT_ROOT"
    shasum -a 256 "$ARCHIVE_NAME" > "$ARCHIVE_NAME.sha256"
)

echo "$ARCHIVE"
echo "$CHECKSUM"
