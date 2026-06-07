#!/usr/bin/env python3
"""Create a macOS .icns file from PNG files in an .iconset directory."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


ICON_TYPES = [
    ("icon_16x16.png", "icp4"),
    ("icon_16x16@2x.png", "icp5"),
    ("icon_32x32.png", "icp5"),
    ("icon_32x32@2x.png", "icp6"),
    ("icon_128x128.png", "ic07"),
    ("icon_128x128@2x.png", "ic08"),
    ("icon_256x256.png", "ic08"),
    ("icon_256x256@2x.png", "ic09"),
    ("icon_512x512.png", "ic09"),
    ("icon_512x512@2x.png", "ic10"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("iconset", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    entries = []
    for filename, icon_type in ICON_TYPES:
        path = args.iconset / filename
        if not path.exists():
            continue
        data = path.read_bytes()
        entries.append(icon_type.encode("ascii") + struct.pack(">I", len(data) + 8) + data)

    if not entries:
        raise SystemExit(f"no PNG files found in {args.iconset}")

    body = b"".join(entries)
    args.output.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
