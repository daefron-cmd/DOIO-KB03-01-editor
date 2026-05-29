"""Listen to the DOIO's live HID input reports while you press keys / turn knobs.

Opens every HID interface the device exposes and prints decoded reports as
they arrive. The keyboard interface shows modifiers + keycodes; the shared
(mouse/consumer) interface is shown as raw + signed bytes so wheel/pan deltas
are visible.

  uv run listen.py --seconds 60

macOS note: opening the *keyboard* interface may need Input Monitoring
permission (System Settings > Privacy & Security). The mouse/consumer
interface usually opens without it, which is enough to see wheel events.
"""

import argparse
import time

import hid

from via import KEYCODES

VID, PID = 0xD010, 0x0301
MOD_NAMES = ["LCtrl", "LShift", "LAlt", "LGUI", "RCtrl", "RShift", "RAlt", "RGUI"]


def signed(b: int) -> int:
    return b - 256 if b > 127 else b


def decode_keyboard(data: list[int]) -> str:
    mods = [n for i, n in enumerate(MOD_NAMES) if data[0] & (1 << i)]
    keys = [KEYCODES.get(u, f"0x{u:02X}") for u in data[2:8] if u]
    if not mods and not keys:
        return "(release)"
    return " + ".join(mods + keys)


def open_interfaces():
    """Return list of (label, kind, device) for each unique interface path."""
    by_path: dict[bytes, dict] = {}
    for d in hid.enumerate(VID, PID):
        p = by_path.setdefault(d["path"], {"iface": d["interface_number"],
                                           "usages": set()})
        p["usages"].add((d["usage_page"], d["usage"]))
    opened = []
    for path, info in sorted(by_path.items(), key=lambda kv: kv[1]["iface"]):
        kind = "keyboard" if (0x01, 0x06) in info["usages"] else \
               "mouse/shared" if (0x01, 0x02) in info["usages"] else "raw"
        label = f"iface{info['iface']} ({kind})"
        try:
            dev = hid.device()
            dev.open_path(path)
            dev.set_nonblocking(1)
            opened.append((label, kind, dev))
            print(f"  opened {label}")
        except Exception as e:  # noqa: BLE001
            print(f"  could NOT open {label}: {type(e).__name__} "
                  "— likely needs Input Monitoring permission")
    return opened


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=60)
    args = ap.parse_args()

    print("opening interfaces...")
    devices = open_interfaces()
    if not devices:
        print("No interfaces opened.")
        return
    print(f"listening for {args.seconds}s — press keys / turn the knobs now\n")

    last: dict[str, list[int]] = {}
    end = time.time() + args.seconds
    while time.time() < end:
        for label, kind, dev in devices:
            data = dev.read(64)
            if not data or data == last.get(label):
                continue
            last[label] = data
            t = time.strftime("%H:%M:%S")
            hexs = " ".join(f"{b:02X}" for b in data)
            if kind == "keyboard":
                print(f"[{t}] {label}: {decode_keyboard(data)}    ({hexs})")
            else:
                sig = " ".join(f"{signed(b):+d}" for b in data[1:])
                print(f"[{t}] {label}: raw [{hexs}]  signed[{sig}]")
        time.sleep(0.005)
    print("\ndone listening.")


if __name__ == "__main__":
    main()
