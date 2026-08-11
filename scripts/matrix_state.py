#!/usr/bin/env python3
"""Print physical KB03-01 matrix presses reported by VIA raw HID.

Close the GUI before running this script. VIA raw HID is single-owner.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=float,
        default=0.05,
        help="poll interval in seconds (default: 0.05)",
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    dev = core.open_raw()
    if dev is None:
        print("No DOIO VIA raw-HID interface found.", file=sys.stderr)
        return 1

    previous: list[int] | None = None
    print("Watching matrix state. Press Ctrl-C to stop.", file=sys.stderr)
    try:
        while True:
            pressed = core.pressed_cols(dev)
            if pressed is None:
                print(
                    "switch_matrix_state is unsupported or returned an invalid reply.",
                    file=sys.stderr,
                )
                return 2
            if pressed != previous:
                print(f"pressed cols: {pressed}", flush=True)
                previous = pressed
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main())
