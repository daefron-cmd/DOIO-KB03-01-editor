"""Read and control the DOIO KB03-01 over the VIA raw-HID interface (0xFF60).

No args        -> read everything (all 4 layers, both encoders, LED state).
LED flags      -> change RGB matrix lighting, then read back to confirm.

  uv run via.py
  uv run via.py --effect 11 --brightness 200 --hue 170 --sat 255
  uv run via.py --effect 1 --save          # persist to EEPROM

Hardware (from qmk keyboards/doio/kb03/keyboard.json):
  STM32F103, 1x5 matrix, 2 rotary encoders, ws2812 RGB matrix (10 LEDs).
"""

import argparse

import hid

VID, PID = 0xD010, 0x0301

# VIA command IDs
GET_PROTOCOL_VERSION = 0x01
GET_KEYBOARD_VALUE = 0x02
DYNAMIC_KEYMAP_GET_KEYCODE = 0x04
CUSTOM_SET_VALUE = 0x07
CUSTOM_GET_VALUE = 0x08
CUSTOM_SAVE = 0x09
DYNAMIC_KEYMAP_GET_LAYER_COUNT = 0x11
DYNAMIC_KEYMAP_GET_ENCODER = 0x14
KB_VALUE_UPTIME = 0x01

# Custom lighting channel + RGB-matrix value IDs
RGB_MATRIX_CHANNEL = 0x03
LIGHT_BRIGHTNESS = 0x01
LIGHT_EFFECT = 0x02
LIGHT_SPEED = 0x03
LIGHT_COLOR = 0x04

# 1x5 matrix column -> physical control (from keyboard.json LAYOUT)
KEY_LABELS = ["Key 1", "Key 2", "Key 3", "Layers", "Knob push"]

# Best-guess effect names: current QMK master include order filtered to this
# board's enabled animations. The device's v0.0.1 firmware may order these
# slightly differently -- verify by setting --effect N and watching the LEDs.
EFFECTS = [
    "SOLID_COLOR_OFF/NONE", "SOLID_COLOR", "GRADIENT_UP_DOWN",
    "GRADIENT_LEFT_RIGHT", "BREATHING", "BAND_SAT", "BAND_VAL",
    "BAND_PINWHEEL_SAT", "BAND_PINWHEEL_VAL", "BAND_SPIRAL_SAT",
    "BAND_SPIRAL_VAL", "CYCLE_ALL", "CYCLE_LEFT_RIGHT", "CYCLE_UP_DOWN",
    "RAINBOW_MOVING_CHEVRON", "CYCLE_OUT_IN", "CYCLE_OUT_IN_DUAL",
    "CYCLE_PINWHEEL", "CYCLE_SPIRAL", "DUAL_BEACON", "RAINBOW_BEACON",
    "RAINBOW_PINWHEELS", "RAINDROPS", "JELLYBEAN_RAINDROPS", "HUE_BREATHING",
    "HUE_WAVE", "SOLID_REACTIVE_SIMPLE", "SOLID_REACTIVE",
    "SOLID_REACTIVE_WIDE", "SOLID_REACTIVE_CROSS", "SOLID_REACTIVE_NEXUS",
    "SPLASH", "SOLID_SPLASH",
]

# Enough of the QMK keycode table to read a macropad: basics + media/system.
KEYCODES = {0x0000: "KC_NO", 0x0001: "KC_TRANSPARENT",
            0x0028: "KC_ENTER", 0x0029: "KC_ESCAPE",
            0x002A: "KC_BACKSPACE", 0x002B: "KC_TAB", 0x002C: "KC_SPACE"}
for _i in range(26):
    KEYCODES[0x04 + _i] = f"KC_{chr(ord('A') + _i)}"
for _i in range(9):
    KEYCODES[0x1E + _i] = f"KC_{_i + 1}"
KEYCODES[0x27] = "KC_0"
for _i in range(12):
    KEYCODES[0x3A + _i] = f"KC_F{_i + 1}"
KEYCODES.update({
    0x00A5: "KC_SYSTEM_POWER", 0x00A6: "KC_SYSTEM_SLEEP",
    0x00A8: "KC_AUDIO_MUTE", 0x00A9: "KC_AUDIO_VOL_UP",
    0x00AA: "KC_AUDIO_VOL_DOWN", 0x00AB: "KC_MEDIA_NEXT_TRACK",
    0x00AC: "KC_MEDIA_PREV_TRACK", 0x00AD: "KC_MEDIA_STOP",
    0x00AE: "KC_MEDIA_PLAY_PAUSE", 0x00AF: "KC_MEDIA_SELECT",
    0x00B1: "KC_MAIL", 0x00B2: "KC_CALCULATOR", 0x00B3: "KC_MY_COMPUTER",
})
KEYCODES.update({  # punctuation, nav, arrows, modifiers
    0x002D: "KC_MINUS", 0x002E: "KC_EQUAL", 0x002F: "KC_LBRC",
    0x0030: "KC_RBRC", 0x0031: "KC_BSLS", 0x0033: "KC_SCLN",
    0x0034: "KC_QUOTE", 0x0035: "KC_GRAVE", 0x0036: "KC_COMMA",
    0x0037: "KC_DOT", 0x0038: "KC_SLASH", 0x0039: "KC_CAPS",
    0x0046: "KC_PSCR", 0x0049: "KC_INSERT", 0x004A: "KC_HOME",
    0x004B: "KC_PGUP", 0x004C: "KC_DELETE", 0x004D: "KC_END",
    0x004E: "KC_PGDN", 0x004F: "KC_RIGHT", 0x0050: "KC_LEFT",
    0x0051: "KC_DOWN", 0x0052: "KC_UP",
    0x00E0: "KC_LCTL", 0x00E1: "KC_LSFT", 0x00E2: "KC_LALT",
    0x00E3: "KC_LGUI", 0x00E4: "KC_RCTL", 0x00E5: "KC_RSFT",
    0x00E6: "KC_RALT", 0x00E7: "KC_RGUI",
})
KEYCODES.update({  # QK_LIGHTING block (RGB/backlight control keycodes)
    0x7800: "BL_ON", 0x7801: "BL_OFF", 0x7802: "BL_TOGG", 0x7805: "BL_STEP",
    0x7820: "RGB_TOG", 0x7821: "RGB_MOD", 0x7822: "RGB_RMOD",
    0x7823: "RGB_HUI", 0x7824: "RGB_HUD", 0x7825: "RGB_SAI",
    0x7826: "RGB_SAD", 0x7827: "RGB_VAI", 0x7828: "RGB_VAD",
    0x7829: "RGB_SPI", 0x782A: "RGB_SPD", 0x782B: "RGB_M_PLAIN",
    0x782C: "RGB_M_BREATHE", 0x782D: "RGB_M_RAINBOW", 0x782E: "RGB_M_SWIRL",
    0x782F: "RGB_M_SNAKE", 0x7830: "RGB_M_KNIGHT", 0x7832: "RGB_M_GRADIENT",
})
KEYCODES.update({  # QMK mouse keys (legacy basic-range numbering 0xCD-0xDD)
    0x00CD: "KC_MS_UP", 0x00CE: "KC_MS_DOWN", 0x00CF: "KC_MS_LEFT",
    0x00D0: "KC_MS_RIGHT", 0x00D1: "KC_MS_BTN1", 0x00D2: "KC_MS_BTN2",
    0x00D3: "KC_MS_BTN3", 0x00D4: "KC_MS_BTN4", 0x00D5: "KC_MS_BTN5",
    0x00D9: "KC_MS_WH_UP", 0x00DA: "KC_MS_WH_DOWN", 0x00DB: "KC_MS_WH_LEFT",
    0x00DC: "KC_MS_WH_RIGHT", 0x00DD: "KC_MS_ACCEL0",
})

_MODS = ((0x01, "Ctrl"), (0x02, "Shift"), (0x04, "Alt"), (0x08, "GUI"))
_LAYER_OPS = {0x00: "TO", 0x20: "MO", 0x40: "DF", 0x60: "TG",
              0x80: "OSL", 0xC0: "TT"}


def decode(code: int) -> str:
    if code in KEYCODES:
        return KEYCODES[code]
    if code < 0x2000:  # basic keycode, possibly with modifier(s) applied
        mods, base = (code >> 8) & 0x1F, code & 0xFF
        name = KEYCODES.get(base, f"0x{base:02X}")
        if not mods:
            return name
        side = "R" if mods & 0x10 else "L"
        prefix = "+".join(side + n for bit, n in _MODS if mods & bit)
        return f"{prefix}+{name}"
    if 0x5200 <= code <= 0x52FF:  # layer-switch keycodes
        op = _LAYER_OPS.get(code & 0xE0)
        if op:
            return f"{op}({code & 0x1F})"
    if 0x7700 <= code <= 0x777F:
        return f"MACRO({code - 0x7700})"
    if 0x7E00 <= code <= 0x7E3F:
        return f"QK_KB({code - 0x7E00})"
    if 0x7E40 <= code <= 0x7FFF:
        return f"USER({code - 0x7E40})"
    return f"0x{code:04X}"


def open_raw():
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] == 0xFF60 and d["usage"] == 0x61:
            dev = hid.device()
            dev.open_path(d["path"])
            return dev
    return None


def cmd(dev, *payload, timeout=1000) -> list[int]:
    """Send a VIA command (padded to 32B, 0x00 report-id prefix), read reply."""
    body = bytes(payload) + bytes(32 - len(payload))
    dev.write(bytes([0x00]) + body)
    return dev.read(32, timeout)


def read_identity(dev) -> int:
    proto = cmd(dev, GET_PROTOCOL_VERSION)
    up = cmd(dev, GET_KEYBOARD_VALUE, KB_VALUE_UPTIME)
    layers = cmd(dev, DYNAMIC_KEYMAP_GET_LAYER_COUNT)[1]
    print(f"VIA protocol : {(proto[1] << 8) | proto[2]}   "
          f"uptime : {int.from_bytes(bytes(up[2:6]), 'big') / 1000:.0f}s   "
          f"layers : {layers}")
    return layers


def read_keymap(dev, layers: int) -> None:
    print("\n--- KEYMAP (all layers) ---")
    for layer in range(layers):
        print(f"  layer {layer}:")
        for col, label in enumerate(KEY_LABELS):
            r = cmd(dev, DYNAMIC_KEYMAP_GET_KEYCODE, layer, 0, col)
            print(f"    {label:10s} : {decode((r[4] << 8) | r[5])}")


def read_encoders(dev, layers: int) -> None:
    print("\n--- ENCODERS (knob rotation) ---")
    for enc in range(2):
        print(f"  encoder {enc}:")
        for layer in range(layers):
            ccw = cmd(dev, DYNAMIC_KEYMAP_GET_ENCODER, layer, enc, 0)
            cw = cmd(dev, DYNAMIC_KEYMAP_GET_ENCODER, layer, enc, 1)
            l = decode((ccw[4] << 8) | ccw[5])
            r = decode((cw[4] << 8) | cw[5])
            print(f"    layer {layer}:  CCW {l:24s}  CW {r}")


def get_light(dev, value_id: int) -> list[int]:
    return cmd(dev, CUSTOM_GET_VALUE, RGB_MATRIX_CHANNEL, value_id)


def read_lighting(dev) -> None:
    print("\n--- RGB MATRIX LIGHTING ---")
    bri = get_light(dev, LIGHT_BRIGHTNESS)[3]
    eff = get_light(dev, LIGHT_EFFECT)[3]
    spd = get_light(dev, LIGHT_SPEED)[3]
    col = get_light(dev, LIGHT_COLOR)
    name = EFFECTS[eff] if eff < len(EFFECTS) else "?"
    print(f"  brightness : {bri}/255  (firmware caps render at 200)")
    print(f"  effect     : {eff}  (~{name})")
    print(f"  speed      : {spd}/255")
    print(f"  color      : hue {col[3]}/255  sat {col[4]}/255")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brightness", type=int)
    ap.add_argument("--effect", type=int)
    ap.add_argument("--speed", type=int)
    ap.add_argument("--hue", type=int)
    ap.add_argument("--sat", type=int)
    ap.add_argument("--save", action="store_true",
                    help="persist lighting to EEPROM")
    args = ap.parse_args()

    dev = open_raw()
    if dev is None:
        print("No VIA raw-HID interface found — plugged in / allowed?")
        return

    writes = {LIGHT_BRIGHTNESS: args.brightness, LIGHT_EFFECT: args.effect,
              LIGHT_SPEED: args.speed}
    if any(v is not None for v in writes.values()) or args.hue is not None \
            or args.sat is not None:
        for vid, val in writes.items():
            if val is not None:
                cmd(dev, CUSTOM_SET_VALUE, RGB_MATRIX_CHANNEL, vid, val)
        if args.hue is not None or args.sat is not None:
            cur = get_light(dev, LIGHT_COLOR)
            hue = args.hue if args.hue is not None else cur[3]
            sat = args.sat if args.sat is not None else cur[4]
            cmd(dev, CUSTOM_SET_VALUE, RGB_MATRIX_CHANNEL, LIGHT_COLOR, hue, sat)
        if args.save:
            cmd(dev, CUSTOM_SAVE, RGB_MATRIX_CHANNEL)
            print("saved lighting to EEPROM")
        read_lighting(dev)
        return

    layers = read_identity(dev)
    read_keymap(dev, layers)
    read_encoders(dev, layers)
    read_lighting(dev)


if __name__ == "__main__":
    main()
