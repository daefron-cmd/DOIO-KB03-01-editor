"""VIA raw-HID transport for the DOIO KB03-01. Returns raw ints/bytes only —
never strings, never imports catalog. Topology + command-ID constants live here."""

import hid

from model import Snapshot

VID, PID = 0xD010, 0x0301

# device topology
KEY_LABELS = ["Key 1", "Key 2", "Key 3", "Layers", "Knob push"]
N_COLS = 5
N_ENCODERS = 2

# Verified on hardware 2026-05-29 (Task 11):
#  - Encoders: enc 1 = OUTER ring (ships as volume), enc 0 = INNER knob (ships as
#    track prev/next). Physical index↔ring confirmed by the user; the dir 0/1 ↔
#    CCW/CW mapping follows QMK convention and was not directionally retested.
#  - col 3 "Layers" is a REAL key, not a phantom: it holds a TO(n) hard cycle —
#    TO(1)/TO(2)/TO(3)/TO(0) on layers 0/1/2/3 — i.e. the back button steps
#    0->1->2->3->0. It is the only physical layer switch; overwriting it on a
#    layer breaks the cycle at that point (the app can rewrite it back).

# VIA command IDs
GET_PROTOCOL_VERSION = 0x01
GET_KEYBOARD_VALUE = 0x02
SWITCH_MATRIX_STATE = 0x03
DYNAMIC_KEYMAP_GET_KEYCODE = 0x04
DYNAMIC_KEYMAP_SET_KEYCODE = 0x05
CUSTOM_SET_VALUE = 0x07
CUSTOM_GET_VALUE = 0x08
CUSTOM_SAVE = 0x09
DYNAMIC_KEYMAP_GET_LAYER_COUNT = 0x11
DYNAMIC_KEYMAP_GET_ENCODER = 0x14
DYNAMIC_KEYMAP_SET_ENCODER = 0x15

# RGB-matrix custom channel + value IDs
RGB_MATRIX_CHANNEL = 0x03
LIGHT_BRIGHTNESS = 0x01
LIGHT_EFFECT = 0x02
LIGHT_SPEED = 0x03
LIGHT_COLOR = 0x04


def open_raw():
    """Open the 0xFF60 VIA raw-HID interface; return a handle or None.

    WARNING — single owner only. VIA is strictly request/response over one
    shared handle. Do NOT run a CLI script that calls open_raw() while the GUI
    (main.py) is running, or vice versa: two processes reading/writing 0xFF60
    concurrently desync the protocol stream and the device appears to "stop
    responding" (control dies, the listener stalls) until everything is closed
    — a replug won't fix it because it's a host-side handle clash, not the
    device. Symptom looks like a severed connection; cause is contention.
    """
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] == 0xFF60 and d["usage"] == 0x61:
            dev = hid.device()
            dev.open_path(d["path"])
            return dev
    return None


def cmd(dev, *payload, timeout=1000) -> list[int]:
    body = bytes(payload) + bytes(32 - len(payload))
    dev.write(bytes([0x00]) + body)
    return dev.read(32, timeout)


# --- reads ---
def layer_count(dev) -> int:
    return cmd(dev, DYNAMIC_KEYMAP_GET_LAYER_COUNT)[1]


def get_key(dev, layer: int, col: int) -> int:
    r = cmd(dev, DYNAMIC_KEYMAP_GET_KEYCODE, layer, 0, col)
    return (r[4] << 8) | r[5]


def get_encoder(dev, layer: int, enc: int, direction: int) -> int:
    r = cmd(dev, DYNAMIC_KEYMAP_GET_ENCODER, layer, enc, direction)
    return (r[4] << 8) | r[5]


def _light(dev, value_id: int) -> list[int]:
    return cmd(dev, CUSTOM_GET_VALUE, RGB_MATRIX_CHANNEL, value_id)


def pressed_cols(dev) -> list[int] | None:
    """Return currently pressed matrix columns, or None if unsupported.

    VIA's switch_matrix_state reports physical switch closures. On this device
    that is a 1-row bitmask for columns 0..4.
    """
    r = cmd(dev, GET_KEYBOARD_VALUE, SWITCH_MATRIX_STATE, 0x00, timeout=100)
    if not r or r[0] == 0xFF or len(r) < 4:
        return None
    if r[0] != GET_KEYBOARD_VALUE or r[1] != SWITCH_MATRIX_STATE:
        return None
    row = r[3]
    return [col for col in range(N_COLS) if row & (1 << col)]


def read_all(dev, layers: int = 4) -> Snapshot:
    keymap = [[get_key(dev, ly, c) for c in range(N_COLS)] for ly in range(layers)]
    encoders = [[[get_encoder(dev, ly, e, d) for d in range(2)]
                 for e in range(N_ENCODERS)] for ly in range(layers)]
    col = _light(dev, LIGHT_COLOR)
    return Snapshot(
        keymap=keymap, encoders=encoders,
        brightness=_light(dev, LIGHT_BRIGHTNESS)[3],
        effect=_light(dev, LIGHT_EFFECT)[3],
        speed=_light(dev, LIGHT_SPEED)[3],
        hue=col[3], sat=col[4],
    )


# --- writes ---
def set_key(dev, layer: int, col: int, keycode: int) -> list[int]:
    return cmd(dev, DYNAMIC_KEYMAP_SET_KEYCODE, layer, 0, col,
               (keycode >> 8) & 0xFF, keycode & 0xFF)


def set_encoder(dev, layer: int, enc: int, direction: int, keycode: int):
    return cmd(dev, DYNAMIC_KEYMAP_SET_ENCODER, layer, enc, direction,
               (keycode >> 8) & 0xFF, keycode & 0xFF)


def set_light_scalar(dev, value_id: int, value: int):
    return cmd(dev, CUSTOM_SET_VALUE, RGB_MATRIX_CHANNEL, value_id, value)


def set_color(dev, hue: int, sat: int):
    return cmd(dev, CUSTOM_SET_VALUE, RGB_MATRIX_CHANNEL, LIGHT_COLOR, hue, sat)


def save_lighting(dev):
    return cmd(dev, CUSTOM_SAVE, RGB_MATRIX_CHANNEL)
