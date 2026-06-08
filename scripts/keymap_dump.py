#!/usr/bin/env python3
"""Read-only matrix + encoder dump over the VIA raw-HID interface.

Useful for discovering the matrix shape of an unknown QMK keyboard, or for
capturing a reference snapshot of the current keymap before flashing new
firmware. Pure read; no EEPROM writes, no flash, no reset.

The known KB03-01 matrix is 1x5 + 2 encoders, which `core.read_all` already
covers — this script exists to probe a generous rectangle (8x8 by default) so
the bounding box of non-empty cells reveals the real matrix on devices the
catalog doesn't yet describe.

Close the GUI before running this. VIA raw-HID is single-owner — see the
top-level README caveat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import catalog
import core


def get_keycode(dev, layer: int, row: int, col: int) -> int | None:
    r = core.cmd(dev, core.DYNAMIC_KEYMAP_GET_KEYCODE, layer, row, col)
    if not r or r[0] != core.DYNAMIC_KEYMAP_GET_KEYCODE:
        return None
    return (r[4] << 8) | r[5]


def get_encoder(dev, layer: int, index: int, clockwise: int) -> int | None:
    r = core.cmd(dev, core.DYNAMIC_KEYMAP_GET_ENCODER, layer, index, clockwise)
    if not r or r[0] != core.DYNAMIC_KEYMAP_GET_ENCODER:
        return None
    return (r[4] << 8) | r[5]


def fmt_keycode(kc: int | None) -> str:
    if kc is None:
        return "??"
    return f"0x{kc:04X} {catalog.decode(kc)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=8,
                        help="rows to probe (0..rows-1)")
    parser.add_argument("--cols", type=int, default=8,
                        help="cols to probe (0..cols-1)")
    parser.add_argument("--encoders", type=int, default=4,
                        help="encoder indices to probe (0..encoders-1)")
    args = parser.parse_args()

    dev = core.open_raw()
    if dev is None:
        raise SystemExit("No DOIO VIA raw-HID interface found.")

    try:
        layers = core.layer_count(dev)
        print(f"Layer count: {layers}\n")

        print(f"=== Matrix probe (rows 0..{args.rows-1}, cols 0..{args.cols-1}) ===")
        cells: dict[tuple[int, int, int], int | None] = {}
        max_row = max_col = -1
        for layer in range(layers):
            for row in range(args.rows):
                for col in range(args.cols):
                    kc = get_keycode(dev, layer, row, col)
                    cells[(layer, row, col)] = kc
                    if kc not in (None, 0x0000):
                        max_row = max(max_row, row)
                        max_col = max(max_col, col)

        if max_row < 0:
            print("  (all cells KC_NO — unexpected)")
        else:
            print(
                f"  Bounding box of non-empty cells: rows 0..{max_row}, "
                f"cols 0..{max_col}  =>  matrix is at least "
                f"{max_row+1}x{max_col+1}"
            )
            print()
            for layer in range(layers):
                print(f"  Layer {layer}:")
                for row in range(max_row + 1):
                    parts = [fmt_keycode(cells[(layer, row, col)])
                             for col in range(max_col + 1)]
                    print(f"    R{row}: " + " | ".join(parts))
                print()

        print(f"=== Encoder probe (index 0..{args.encoders-1}) ===")
        any_encoder = False
        for index in range(args.encoders):
            rows = []
            present = False
            for layer in range(layers):
                ccw = get_encoder(dev, layer, index, 0)
                cw = get_encoder(dev, layer, index, 1)
                if ccw not in (None, 0x0000) or cw not in (None, 0x0000):
                    present = True
                rows.append((layer, ccw, cw))
            if present:
                any_encoder = True
                print(f"  Encoder #{index}:")
                for layer, ccw, cw in rows:
                    print(f"    Layer {layer}: "
                          f"CCW={fmt_keycode(ccw)}  CW={fmt_keycode(cw)}")
        if not any_encoder:
            print("  (no encoders configured)")

    finally:
        dev.close()


if __name__ == "__main__":
    main()
