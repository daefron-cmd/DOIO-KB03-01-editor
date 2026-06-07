#!/usr/bin/env python3
"""Interactively verify KB03 RGB-matrix effect indices.

Close the GUI before running this. VIA raw-HID is single-owner request/response;
running this while the app is open can desync the device handle.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core


@dataclass
class LightingBackup:
    brightness: int
    effect: int
    speed: int
    hue: int
    sat: int


def _get(dev, value_id: int) -> list[int]:
    return core.cmd(dev, core.CUSTOM_GET_VALUE, core.RGB_MATRIX_CHANNEL, value_id)


def _backup(dev) -> LightingBackup:
    color = _get(dev, core.LIGHT_COLOR)
    return LightingBackup(
        brightness=_get(dev, core.LIGHT_BRIGHTNESS)[3],
        effect=_get(dev, core.LIGHT_EFFECT)[3],
        speed=_get(dev, core.LIGHT_SPEED)[3],
        hue=color[3],
        sat=color[4],
    )


def _restore(dev, backup: LightingBackup) -> None:
    core.set_light_scalar(dev, core.LIGHT_BRIGHTNESS, backup.brightness)
    core.set_light_scalar(dev, core.LIGHT_SPEED, backup.speed)
    core.set_light_scalar(dev, core.LIGHT_EFFECT, backup.effect)
    core.set_color(dev, backup.hue, backup.sat)


def _read_effect(dev) -> int:
    return _get(dev, core.LIGHT_EFFECT)[3]


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    ans = input(f"{prompt}{suffix}: ").strip()
    return ans or default


def _write_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [
        "# KB03 LED Effect Probe Results",
        "",
        "| Requested | Readback | Status | Label | Notes |",
        "|---:|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['requested']} | {row['readback']} | {row['status']} | "
            f"`{row['label']}` | {row['notes']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-index", type=int, default=31,
                        help="highest effect index to request")
    parser.add_argument("--brightness", type=int, default=150,
                        help="temporary brightness while probing, capped by firmware")
    parser.add_argument("--speed", type=int, default=160,
                        help="temporary speed while probing")
    parser.add_argument("--hue", type=int, default=None,
                        help="temporary hue; defaults to current hue")
    parser.add_argument("--sat", type=int, default=255,
                        help="temporary saturation while probing")
    parser.add_argument("--out", type=Path,
                        default=Path("docs/KB03_led_effect_probe_results.md"))
    args = parser.parse_args()

    dev = core.open_raw()
    if dev is None:
        raise SystemExit("No DOIO VIA raw-HID interface found.")

    backup = _backup(dev)
    print("Backed up lighting:")
    print(f"  brightness={backup.brightness} effect={backup.effect} "
          f"speed={backup.speed} hue={backup.hue} sat={backup.sat}")
    print("\nClose the GUI while this runs. Ctrl-C restores the live state.")
    print("For status, use: visible, same-as-N, no-op, broken, unknown.\n")

    rows: list[dict[str, str]] = []
    try:
        core.set_light_scalar(dev, core.LIGHT_BRIGHTNESS, args.brightness)
        core.set_light_scalar(dev, core.LIGHT_SPEED, args.speed)
        core.set_color(dev, backup.hue if args.hue is None else args.hue, args.sat)

        for index in range(args.max_index + 1):
            core.set_light_scalar(dev, core.LIGHT_EFFECT, index)
            readback = _read_effect(dev)
            print(f"\nRequested effect {index}; firmware readback {readback}.")
            status = _ask("status", "visible")
            if status.lower() == "q":
                break
            label = _ask("label", f"EFFECT_{index}")
            notes = _ask("notes", "")
            rows.append({
                "requested": str(index),
                "readback": str(readback),
                "status": status,
                "label": label,
                "notes": notes,
            })
    finally:
        _restore(dev, backup)
        print("\nRestored original live lighting state.")

    if rows:
        _write_markdown(args.out, rows)
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
