#!/usr/bin/env bash
# Build a QMK keymap for the DOIO KB03-01.
#
# Usage:  ./build.sh <keymap>
#         ./build.sh default
#         ./build.sh vegar
#
# Expects a QMK checkout at ./qmk_firmware (gitignored — see README.md).
# Custom keymaps live in ./keymaps/<name>/ and are symlinked into the
# QMK tree on first build so editing them in place updates the build.

set -euo pipefail

KEYMAP="${1:-default}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QMK="$ROOT/qmk_firmware"

if [[ ! -d "$QMK" ]]; then
    echo "error: $QMK not found. Clone QMK there — see firmware/README.md." >&2
    exit 1
fi

# Symlink any local keymaps into the QMK tree if not already linked.
KB03_KEYMAPS="$QMK/keyboards/doio/kb03/keymaps"
if [[ -d "$ROOT/keymaps" ]]; then
    for src in "$ROOT/keymaps"/*/; do
        name="$(basename "$src")"
        target="$KB03_KEYMAPS/$name"
        if [[ "$name" == "default" ]]; then
            continue  # never shadow QMK's stock default
        fi
        if [[ ! -e "$target" ]]; then
            ln -s "$src" "$target"
        fi
    done
fi

# The QMK toolchain installed via Homebrew's qmk tap is keg-only
# (versioned formulas), so we prepend the correct bin directories.
export PATH="/opt/homebrew/opt/arm-none-eabi-gcc@8/bin:/opt/homebrew/opt/arm-none-eabi-binutils/bin:$PATH"

exec make -C "$QMK" "doio/kb03:$KEYMAP"
