"""Keycode semantics: decode/encode, the Norwegian-Mac catalog, resolve_controls.
Pure logic — no hardware, no Qt, no import of core."""

# --- keycode table (moved from via.py) ---
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
KEYCODES.update({
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
KEYCODES.update({
    0x7800: "BL_ON", 0x7801: "BL_OFF", 0x7802: "BL_TOGG", 0x7805: "BL_STEP",
    0x7820: "RGB_TOG", 0x7821: "RGB_MOD", 0x7822: "RGB_RMOD",
    0x7823: "RGB_HUI", 0x7824: "RGB_HUD", 0x7825: "RGB_SAI",
    0x7826: "RGB_SAD", 0x7827: "RGB_VAI", 0x7828: "RGB_VAD",
    0x7829: "RGB_SPI", 0x782A: "RGB_SPD",
})

# --- named base keycodes used by the catalog/encoders ---
KC_A = 0x04
KC_1, KC_2, KC_3, KC_4, KC_5, KC_6, KC_7, KC_8, KC_9, KC_0 = (
    0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27)
KC_NO, KC_TRNS = 0x0000, 0x0001
KC_LBRC, KC_SCLN, KC_QUOTE = 0x2F, 0x33, 0x34

# --- modifier bits (QMK 5-bit field) ---
CTRL, SHIFT, ALT, GUI = 0x01, 0x02, 0x04, 0x08
RIGHT = 0x10

# --- layer ops (high bits within 0x52xx) ---
TO, MO, DF, TG, OSL, TT = 0x00, 0x20, 0x40, 0x60, 0x80, 0xC0

_MODS = ((0x01, "Ctrl"), (0x02, "Shift"), (0x04, "Alt"), (0x08, "GUI"))
_LAYER_OPS = {0x00: "TO", 0x20: "MO", 0x40: "DF", 0x60: "TG",
              0x80: "OSL", 0xC0: "TT"}


def decode(code: int) -> str:
    if code in KEYCODES:
        return KEYCODES[code]
    if code < 0x2000:
        mods, base = (code >> 8) & 0x1F, code & 0xFF
        name = KEYCODES.get(base, f"0x{base:02X}")
        if not mods:
            return name
        side = "R" if mods & 0x10 else "L"
        prefix = "+".join(side + n for bit, n in _MODS if mods & bit)
        return f"{prefix}+{name}"
    if 0x5200 <= code <= 0x52FF:
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


def mod(base: int, *mods: int, right: bool = False) -> int:
    """Combine a base keycode with QMK modifier bits → 16-bit keycode."""
    bits = 0
    for m in mods:
        bits |= m
    if right and bits:
        bits |= RIGHT
    return (bits << 8) | base


def layer(op: int, n: int) -> int:
    """Layer-switch keycode, e.g. layer(MO, 1)."""
    return 0x5200 | op | (n & 0x1F)


# (category, display_label, keycode_int). keycode_int must be unique.
CATALOG: list[tuple[str, str, int]] = []


def _add(cat: str, label: str, code: int) -> None:
    CATALOG.append((cat, label, code))


# basic / special
_add("basic", "(disable)  (KC_NO)", KC_NO)
_add("basic", "(transparent)  (KC_TRANSPARENT)", KC_TRNS)
for _code, _name in ((0x0028, "Enter"), (0x0029, "Esc"), (0x002A, "Backspace"),
                     (0x002B, "Tab"), (0x002C, "Space"), (0x004C, "Delete"),
                     (0x0052, "Up"), (0x0051, "Down"), (0x0050, "Left"),
                     (0x004F, "Right"), (0x004A, "Home"), (0x004D, "End"),
                     (0x004B, "PgUp"), (0x004E, "PgDn")):
    _add("basic", f"{_name}  ({KEYCODES[_code]})", _code)

# letters a–z
for _i in range(26):
    _ch = chr(ord("a") + _i)
    _add("letters", f"{_ch}  ({KEYCODES[KC_A + _i]})", KC_A + _i)
# Norwegian dedicated letters
_add("letters", f"å  ({KEYCODES[KC_LBRC]})", KC_LBRC)
_add("letters", f"ø  ({KEYCODES[KC_SCLN]})", KC_SCLN)
_add("letters", f"æ  ({KEYCODES[KC_QUOTE]})", KC_QUOTE)

# numbers 0–9
for _n, _code in ((1, KC_1), (2, KC_2), (3, KC_3), (4, KC_4), (5, KC_5),
                  (6, KC_6), (7, KC_7), (8, KC_8), (9, KC_9), (0, KC_0)):
    _add("numbers", f"{_n}  ({KEYCODES[_code]})", _code)

# Norwegian-Mac symbols (verified empirically per spec §15 item 5)
_add("symbols", "[  (A+KC_8)", mod(KC_8, ALT))
_add("symbols", "{  (S+A+KC_8)", mod(KC_8, SHIFT, ALT))
_add("symbols", "]  (A+KC_9)", mod(KC_9, ALT))
_add("symbols", "}  (S+A+KC_9)", mod(KC_9, SHIFT, ALT))

# media
for _code in (0x00A9, 0x00AA, 0x00A8, 0x00AB, 0x00AC, 0x00AD, 0x00AE):
    _short = {0x00A9: "vol+", 0x00AA: "vol-", 0x00A8: "mute",
              0x00AB: "next", 0x00AC: "prev", 0x00AD: "stop",
              0x00AE: "play/pause"}[_code]
    _add("media", f"{_short}  ({KEYCODES[_code]})", _code)

# modifiers
for _code in (0x00E0, 0x00E1, 0x00E2, 0x00E3):
    _add("modifiers", f"{KEYCODES[_code]}", _code)

# layers
for _op, _name in ((MO, "MO"), (TO, "TO"), (TG, "TG")):
    for _n in range(4):
        _add("layers", f"{_name}({_n})", layer(_op, _n))

# lighting
for _code in (0x7820, 0x7821, 0x7823, 0x7824, 0x7827, 0x7828):
    _add("lighting", f"{KEYCODES[_code]}", _code)

# unique-keycode assertion (fail fast — a duplicate is an authoring bug)
_seen: dict[int, str] = {}
for _cat, _label, _code in CATALOG:
    assert _code not in _seen, f"duplicate keycode {_code:#06x}"
    _seen[_code] = _label


def reverse_index() -> dict[int, tuple[str, str, int]]:
    return {code: (cat, label, code) for cat, label, code in CATALOG}


_REVERSE = reverse_index()


def render(code: int) -> str:
    entry = _REVERSE.get(code)
    if entry:
        return entry[1]
    return decode(code)


# Consumer-Page usage ID -> QMK keycode (media-mapped encoders emit on the
# consumer interface, not as QMK keycodes).
CONSUMER_USAGE = {
    0xE9: 0x00A9, 0xEA: 0x00AA, 0xE2: 0x00A8,
    0xB5: 0x00AB, 0xB6: 0x00AC, 0xB7: 0x00AD, 0xCD: 0x00AE,
}


from model import Snapshot, key_id, enc_id, ControlId


def _fold_mods(report_mods: int) -> int:
    """HID 8-bit L/R mod byte → QMK 5-bit field (+0x10 right side)."""
    low = report_mods & 0x0F
    high = (report_mods >> 4) & 0x0F
    return (high | RIGHT) if high else low


def _reconstruct(iface_kind: str, report_mods: int, code: int) -> int | None:
    """Turn one report entry into a 16-bit QMK keycode to match the snapshot."""
    if iface_kind == "consumer":
        qmk = CONSUMER_USAGE.get(code)
        return qmk
    qmk_mods = _fold_mods(report_mods)
    return ((qmk_mods << 8) | code) if qmk_mods else code


def resolve_controls(snapshot: Snapshot, iface_kind: str,
                     mods: int, keycodes: list[int]) -> list[ControlId]:
    """Best-effort: which physical control(s) produced this report, matched
    against the UNION of all layers. Not layer-specific (per design)."""
    targets: set[int] = set()
    for code in keycodes:
        if not code:
            continue
        rc = _reconstruct(iface_kind, report_mods=mods, code=code)
        if rc is not None:
            targets.add(rc)
    if not targets:
        return []
    hits: list[ControlId] = []
    seen: set[ControlId] = set()
    for layer_map in snapshot.keymap:
        for col, value in enumerate(layer_map):
            cid = key_id(col)
            if value in targets and cid not in seen:
                seen.add(cid)
                hits.append(cid)
    for layer_encs in snapshot.encoders:
        for enc, dirs in enumerate(layer_encs):
            for direction, value in enumerate(dirs):
                cid = enc_id(enc, direction)
                if value in targets and cid not in seen:
                    seen.add(cid)
                    hits.append(cid)
    return hits
