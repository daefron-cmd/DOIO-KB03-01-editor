"""Keycode semantics: decode/encode, the Norwegian-Mac catalog, resolve_controls.
Pure logic — no hardware, no Qt, no import of core."""

from model import Snapshot, key_id, enc_id, ControlId

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
    0x00D9: "KC_MS_WH_UP", 0x00DA: "KC_MS_WH_DOWN",
    0x00DB: "KC_MS_WH_LEFT", 0x00DC: "KC_MS_WH_RIGHT",
})
KEYCODES.update({
    0x002D: "KC_MINUS", 0x002E: "KC_EQUAL", 0x002F: "KC_LBRC",
    0x0030: "KC_RBRC", 0x0031: "KC_BSLS", 0x0032: "KC_NUHS",
    0x0033: "KC_SCLN", 0x0034: "KC_QUOTE", 0x0035: "KC_GRAVE",
    0x0036: "KC_COMMA", 0x0037: "KC_DOT", 0x0038: "KC_SLASH",
    0x0039: "KC_CAPS_LOCK",
    0x0046: "KC_PRINT_SCREEN", 0x0047: "KC_SCROLL_LOCK",
    0x0048: "KC_PAUSE", 0x0049: "KC_INSERT",
    0x004A: "KC_HOME", 0x004B: "KC_PGUP",
    0x004C: "KC_DELETE", 0x004D: "KC_END", 0x004E: "KC_PGDN",
    0x004F: "KC_RIGHT", 0x0050: "KC_LEFT",
    0x0051: "KC_DOWN", 0x0052: "KC_UP",
    0x0053: "KC_NUM_LOCK",
    0x0054: "KC_KP_SLASH", 0x0055: "KC_KP_ASTERISK",
    0x0056: "KC_KP_MINUS", 0x0057: "KC_KP_PLUS",
    0x0058: "KC_KP_ENTER",
    0x0059: "KC_KP_1", 0x005A: "KC_KP_2", 0x005B: "KC_KP_3",
    0x005C: "KC_KP_4", 0x005D: "KC_KP_5", 0x005E: "KC_KP_6",
    0x005F: "KC_KP_7", 0x0060: "KC_KP_8", 0x0061: "KC_KP_9",
    0x0062: "KC_KP_0", 0x0063: "KC_KP_DOT",
    0x0064: "KC_NUBS", 0x0065: "KC_APPLICATION",
    0x0067: "KC_KP_EQUAL", 0x0085: "KC_KP_COMMA",
    0x00E0: "KC_LCTL", 0x00E1: "KC_LSFT", 0x00E2: "KC_LALT",
    0x00E3: "KC_LGUI", 0x00E4: "KC_RCTL", 0x00E5: "KC_RSFT",
    0x00E6: "KC_RALT", 0x00E7: "KC_RGUI",
})
# F13–F24
for _i in range(12):
    KEYCODES[0x0068 + _i] = f"KC_F{_i + 13}"
# Consumer / system / browser / macOS hardware keys
KEYCODES.update({
    0x00A7: "KC_SYSTEM_WAKE",
    0x00B0: "KC_MEDIA_EJECT",
    0x00B4: "KC_WWW_SEARCH", 0x00B5: "KC_WWW_HOME",
    0x00B6: "KC_WWW_BACK", 0x00B7: "KC_WWW_FORWARD",
    0x00B8: "KC_WWW_STOP", 0x00B9: "KC_WWW_REFRESH",
    0x00BA: "KC_WWW_FAVORITES",
    0x00BB: "KC_MEDIA_FAST_FORWARD", 0x00BC: "KC_MEDIA_REWIND",
    0x00BD: "KC_BRIGHTNESS_UP", 0x00BE: "KC_BRIGHTNESS_DOWN",
    0x00C1: "KC_MISSION_CONTROL", 0x00C2: "KC_LAUNCHPAD",
})
# Mouse cursor + buttons (wheel already above)
KEYCODES.update({
    0x00CD: "KC_MS_UP", 0x00CE: "KC_MS_DOWN",
    0x00CF: "KC_MS_LEFT", 0x00D0: "KC_MS_RIGHT",
    0x00D1: "KC_MS_BTN1", 0x00D2: "KC_MS_BTN2",
    0x00D3: "KC_MS_BTN3", 0x00D4: "KC_MS_BTN4",
    0x00D5: "KC_MS_BTN5",
})
# Quantum / firmware
KEYCODES[0x7C00] = "QK_BOOT"
KEYCODES.update({
    0x7800: "BL_ON", 0x7801: "BL_OFF", 0x7802: "BL_TOGG", 0x7805: "BL_STEP",
    0x7820: "RGB_TOG", 0x7821: "RGB_MOD", 0x7822: "RGB_RMOD",
    0x7823: "RGB_HUI", 0x7824: "RGB_HUD", 0x7825: "RGB_SAI",
    0x7826: "RGB_SAD", 0x7827: "RGB_VAI", 0x7828: "RGB_VAD",
    0x7829: "RGB_SPI", 0x782A: "RGB_SPD",
})

# --- named base keycodes used by the catalog/encoders ---
KC_A = 0x04
KC_B, KC_C, KC_D, KC_E, KC_F, KC_G, KC_H, KC_I, KC_J = (
    0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D)
KC_K, KC_L, KC_M, KC_N, KC_O, KC_P, KC_Q, KC_R, KC_S = (
    0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16)
KC_T, KC_U, KC_V, KC_W, KC_X, KC_Y, KC_Z = (
    0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D)
KC_1, KC_2, KC_3, KC_4, KC_5, KC_6, KC_7, KC_8, KC_9, KC_0 = (
    0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27)
KC_NO, KC_TRNS = 0x0000, 0x0001
KC_MINUS, KC_EQUAL, KC_LBRC, KC_RBRC, KC_BSLS = 0x2D, 0x2E, 0x2F, 0x30, 0x31
KC_NUHS, KC_SCLN, KC_QUOTE, KC_GRAVE = 0x32, 0x33, 0x34, 0x35
KC_COMMA, KC_DOT, KC_SLASH, KC_NUBS = 0x36, 0x37, 0x38, 0x64
KC_TAB, KC_SPACE, KC_BSPC, KC_ENTER, KC_ESC = 0x2B, 0x2C, 0x2A, 0x28, 0x29
KC_DELETE = 0x4C
KC_UP, KC_DOWN, KC_LEFT, KC_RIGHT = 0x52, 0x51, 0x50, 0x4F

# --- modifier bits (QMK 5-bit field) ---
CTRL, SHIFT, ALT, GUI = 0x01, 0x02, 0x04, 0x08
RIGHT = 0x10

# --- layer ops (high bits within 0x52xx) ---
TO, MO, DF, TG, OSL, TT = 0x00, 0x20, 0x40, 0x60, 0x80, 0xC0

# Apple-convention display order: Control, Option, Shift, Command.
_MODS = ((0x01, "⌃"), (0x04, "⌥"), (0x02, "⇧"), (0x08, "⌘"))
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
        # Apple-style stacked symbols, optional 'R' prefix for the right side
        # (QMK's 5-bit field encodes side as one shared bit, not per-modifier).
        stack = "".join(sym for bit, sym in _MODS if mods & bit)
        prefix = ("R" if mods & 0x10 else "") + stack
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


# Base catalog uses US-Mac defaults. Active layout sets overlay onto this —
# overriding the human name (and category) for codes that exist, appending
# entries for codes that don't. (category, display_label, keycode_int);
# keycode_int must be unique within the final CATALOG.
_BASE_CATALOG: list[tuple[str, str, int]] = []


def _add(cat: str, label: str, code: int) -> None:
    _BASE_CATALOG.append((cat, label, code))


# basic / special
_add("basic", "(disable)  (KC_NO)", KC_NO)
_add("basic", "(transparent)  (KC_TRANSPARENT)", KC_TRNS)
for _code, _name in ((0x0028, "Enter"), (0x0029, "Esc"), (0x002A, "Backspace"),
                     (0x002B, "Tab"), (0x002C, "Space"), (0x004C, "Delete"),
                     (0x0052, "Up"), (0x0051, "Down"), (0x0050, "Left"),
                     (0x004F, "Right"), (0x004A, "Home"), (0x004D, "End"),
                     (0x004B, "PgUp"), (0x004E, "PgDn")):
    _add("basic", f"{_name}  ({KEYCODES[_code]})", _code)

# function row — F1–F24
for _i in range(24):
    _add("function", f"F{_i + 1}  ({KEYCODES[0x003A + _i if _i < 12 else 0x0068 + _i - 12]})",
         0x003A + _i if _i < 12 else 0x0068 + _i - 12)

# letters a–z (US-Mac base; layouts add their layout-specific letters by
# overriding the punctuation codes those layouts assign them to — e.g. NO-Mac
# overrides KC_LBRC → å.)
for _i in range(26):
    _ch = chr(ord("a") + _i)
    _add("letters", f"{_ch}  ({KEYCODES[KC_A + _i]})", KC_A + _i)

# numbers 0–9
for _n, _code in ((1, KC_1), (2, KC_2), (3, KC_3), (4, KC_4), (5, KC_5),
                  (6, KC_6), (7, KC_7), (8, KC_8), (9, KC_9), (0, KC_0)):
    _add("numbers", f"{_n}  ({KEYCODES[_code]})", _code)

# numpad
for _code, _name in (
    (0x0059, "1"), (0x005A, "2"), (0x005B, "3"), (0x005C, "4"),
    (0x005D, "5"), (0x005E, "6"), (0x005F, "7"), (0x0060, "8"),
    (0x0061, "9"), (0x0062, "0"), (0x0063, "."),
    (0x0054, "/"), (0x0055, "*"), (0x0056, "-"), (0x0057, "+"),
    (0x0058, "Enter"), (0x0067, "="), (0x0085, ","),
):
    _add("numpad", f"KP {_name}  ({KEYCODES[_code]})", _code)

# symbols — US-Mac defaults. NO-Mac overrides [/;/' to letters and adds its
# Option-combos for the bracket family. Other punctuation passes through.
for _code, _name in (
    (KC_MINUS, "-"), (KC_EQUAL, "="), (KC_LBRC, "["), (KC_RBRC, "]"),
    (KC_BSLS, "\\"), (KC_SCLN, ";"), (KC_QUOTE, "'"), (KC_GRAVE, "`"),
    (KC_COMMA, ","), (KC_DOT, "."), (KC_SLASH, "/"),
    (KC_NUHS, "ISO # (layout-dependent)"),
    (KC_NUBS, "ISO \\ (layout-dependent)"),
):
    _add("symbols", f"{_name}  ({KEYCODES[_code]})", _code)

# system / OS-level keys. `(Mac: no-op)` marker = the host's macOS HID stack
# doesn't act on this code by default. The firmware still sends it; another
# OS (or a Karabiner-style remapper) may pick it up.
for _code, _name in (
    (0x0039, "Caps Lock"),
    (0x0046, "Print Screen (Mac: no-op)"),
    (0x0047, "Scroll Lock (Mac: no-op)"),
    (0x0048, "Pause (Mac: no-op)"),
    (0x0049, "Insert"),
    (0x0053, "Num Lock (Mac: no-op)"),
    (0x0065, "Application / Menu (Mac: no-op)"),
    (0x00A5, "System Power (Mac: no-op)"),
    (0x00A6, "System Sleep"),
    (0x00A7, "System Wake"),
    (0x00BD, "Brightness +"), (0x00BE, "Brightness -"),
    (0x00C1, "Mission Control"), (0x00C2, "Launchpad"),
    (0x7C00, "Bootloader (QK_BOOT)"),
):
    _add("system", f"{_name}  ({KEYCODES[_code]})", _code)

# mouse — emits HID mouse events. Requires the KB03 QMK image to be compiled
# with MOUSEKEY_ENABLE=yes; if not, VIA still stores them but they're no-op.
for _code, _short in (
    (0x00CD, "cursor ↑"), (0x00CE, "cursor ↓"),
    (0x00CF, "cursor ←"), (0x00D0, "cursor →"),
    (0x00D1, "button 1 (left)"), (0x00D2, "button 2 (right)"),
    (0x00D3, "button 3 (middle)"), (0x00D4, "button 4"),
    (0x00D5, "button 5"),
    (0x00D9, "wheel ↑"), (0x00DA, "wheel ↓"),
    (0x00DB, "wheel ←"), (0x00DC, "wheel →"),
):
    _add("mouse", f"{_short}  ({KEYCODES[_code]})", _code)

# media / consumer keys
for _code, _short in (
    (0x00A9, "vol+"), (0x00AA, "vol-"), (0x00A8, "mute"),
    (0x00AB, "next"), (0x00AC, "prev"), (0x00AD, "stop"),
    (0x00AE, "play/pause"), (0x00AF, "media select"),
    (0x00B0, "eject"),
    (0x00BB, "fast forward"), (0x00BC, "rewind"),
    (0x00B1, "mail (Mac: no-op)"),
    (0x00B2, "calculator (Mac: no-op)"),
    (0x00B3, "my computer (Mac: no-op)"),
):
    _add("media", f"{_short}  ({KEYCODES[_code]})", _code)

# browser / WWW keys — Windows-era HID consumer codes; Safari/Chrome on macOS
# don't bind any of them by default. Listed for completeness (and for users
# who route through Karabiner / a custom remapper).
for _code, _short in (
    (0x00B4, "search"), (0x00B5, "home"),
    (0x00B6, "back"), (0x00B7, "forward"),
    (0x00B8, "stop"), (0x00B9, "refresh"),
    (0x00BA, "favorites"),
):
    _add("browser", f"www {_short} (Mac: no-op)  ({KEYCODES[_code]})", _code)

# modifiers — macOS-style display: SYMBOL Side Name. QMK name kept in parens
# so the picker's search still hits 'LCTL', 'LGUI', etc. Right-side modifiers
# included so binding a key to e.g. Right Option is one click, not impossible.
for _code, _name in (
    (0x00E0, "⌃ Left Control"),  (0x00E4, "⌃ Right Control"),
    (0x00E1, "⇧ Left Shift"),    (0x00E5, "⇧ Right Shift"),
    (0x00E2, "⌥ Left Option"),   (0x00E6, "⌥ Right Option"),
    (0x00E3, "⌘ Left Command"),  (0x00E7, "⌘ Right Command"),
):
    _add("modifiers", f"{_name}  ({KEYCODES[_code]})", _code)

# macOS shortcut combos — common ⌘/⌥/⇧/⌃ pairs people actually bind to a
# macropad. Each one encodes a modified base via mod(); decode() renders them
# as e.g. "⌘+KC_C". The catalog label leads with the macOS shortcut form so
# they read at-a-glance in the picker.
for _label, _code in (
    ("⌘ A — select all", mod(KC_A, GUI)),
    ("⌘ C — copy",       mod(KC_C, GUI)),
    ("⌘ V — paste",      mod(KC_V, GUI)),
    ("⌘ X — cut",        mod(KC_X, GUI)),
    ("⌘ Z — undo",       mod(KC_Z, GUI)),
    ("⇧⌘ Z — redo",      mod(KC_Z, SHIFT, GUI)),
    ("⌘ S — save",       mod(KC_S, GUI)),
    ("⇧⌘ S — save as",   mod(KC_S, SHIFT, GUI)),
    ("⌘ N — new",        mod(KC_N, GUI)),
    ("⇧⌘ N — new folder", mod(KC_N, SHIFT, GUI)),
    ("⌘ T — new tab",    mod(KC_T, GUI)),
    ("⇧⌘ T — reopen tab", mod(KC_T, SHIFT, GUI)),
    ("⌘ W — close",      mod(KC_W, GUI)),
    ("⌘ Q — quit",       mod(KC_Q, GUI)),
    ("⌘ F — find",       mod(KC_F, GUI)),
    ("⌘ G — find next",  mod(KC_G, GUI)),
    ("⌘ O — open",       mod(KC_O, GUI)),
    ("⌘ P — print",      mod(KC_P, GUI)),
    ("⌘ R — reload",     mod(KC_R, GUI)),
    ("⌘ H — hide app",   mod(KC_H, GUI)),
    ("⌥⌘ H — hide others", mod(KC_H, ALT, GUI)),
    ("⌘ M — minimize",   mod(KC_M, GUI)),
    ("⌘ Space — Spotlight", mod(KC_SPACE, GUI)),
    ("⌃ Space — input source", mod(KC_SPACE, CTRL)),
    ("⌥⌘ Esc — force quit", mod(KC_ESC, ALT, GUI)),
    ("⌘ Tab — app switcher", mod(KC_TAB, GUI)),
    ("⇧⌘ Tab — reverse switcher", mod(KC_TAB, SHIFT, GUI)),
    ("⌃ Tab — next tab",  mod(KC_TAB, CTRL)),
    ("⌃⇧ Tab — prev tab", mod(KC_TAB, CTRL, SHIFT)),
    ("⇧⌘ 3 — screenshot",  mod(KC_3, SHIFT, GUI)),
    ("⇧⌘ 4 — region shot", mod(KC_4, SHIFT, GUI)),
    ("⇧⌘ 5 — screenshot menu", mod(KC_5, SHIFT, GUI)),
    ("⌃⌘ F — full screen", mod(KC_F, CTRL, GUI)),
    ("⌘ Delete — move to trash", mod(KC_DELETE, GUI)),
    ("⇧⌘ Delete — empty trash", mod(KC_DELETE, SHIFT, GUI)),
):
    _add("shortcuts", f"{_label}  ({decode(_code)})", _code)

# terminal navigation — readline / emacs-style keybindings used by bash, zsh,
# fish, and most macOS CLI tools. Cursor movement, line editing, and history
# navigation.
#
# Two flavors mixed below:
#   * ⌃-prefixed (control chars the TTY sends) — work in any terminal, period.
#     They're also macOS's system-wide emacs-style text bindings (⌃A/⌃E/⌃K/
#     ⌃D/⌃H/⌃Y/⌃T work in any text field, not just the terminal).
#   * ⌥-Arrow / ⌥-⌫ / ⌥-⌦ — macOS-native word-motion shortcuts. Terminal.app
#     and iTerm2 ship with these mapped to readline's word commands by
#     default, and they also work in every other macOS text field. No
#     "Option as Meta" toggle needed.
for _label, _code in (
    ("⌃ A — start of line",          mod(KC_A, CTRL)),
    ("⌃ E — end of line",            mod(KC_E, CTRL)),
    ("⌃ F — forward char",           mod(KC_F, CTRL)),
    ("⌃ B — backward char",          mod(KC_B, CTRL)),
    ("⌥ → — forward word",           mod(KC_RIGHT, ALT)),
    ("⌥ ← — backward word",          mod(KC_LEFT, ALT)),
    ("⌃ K — kill to end of line",    mod(KC_K, CTRL)),
    ("⌃ U — kill to start of line",  mod(KC_U, CTRL)),
    ("⌃ W — kill word back (TTY)",   mod(KC_W, CTRL)),
    ("⌥ ⌫ — delete word back",       mod(KC_BSPC, ALT)),
    ("⌥ ⌦ — delete word forward",    mod(KC_DELETE, ALT)),
    ("⌃ D — delete / EOF",           mod(KC_D, CTRL)),
    ("⌃ H — backspace",              mod(KC_H, CTRL)),
    ("⌃ Y — yank (paste killed)",    mod(KC_Y, CTRL)),
    ("⌃ T — transpose chars",        mod(KC_T, CTRL)),
    ("⌃ P — previous command",       mod(KC_P, CTRL)),
    ("⌃ N — next command",           mod(KC_N, CTRL)),
    ("⌃ R — reverse history search", mod(KC_R, CTRL)),
    ("⌃ L — clear screen",           mod(KC_L, CTRL)),
    ("⌃ C — interrupt (SIGINT)",     mod(KC_C, CTRL)),
    ("⌃ Z — suspend (SIGTSTP)",      mod(KC_Z, CTRL)),
    ("⌃ G — abort / bell",           mod(KC_G, CTRL)),
):
    _add("terminal navigation", f"{_label}  ({decode(_code)})", _code)

# layers — full set of common ops (MO/TO/TG/DF/OSL/TT) × layers 0..3.
# LT(layer,kc) and MT(mod,kc) need a held-base picker; out of scope here.
for _op, _name in ((MO, "MO"), (TO, "TO"), (TG, "TG"),
                   (DF, "DF"), (OSL, "OSL"), (TT, "TT")):
    for _n in range(4):
        _add("layers", f"{_name}({_n})", layer(_op, _n))

# lighting
for _code in (0x7800, 0x7801, 0x7802, 0x7805,
              0x7820, 0x7821, 0x7822, 0x7823, 0x7824,
              0x7825, 0x7826, 0x7827, 0x7828, 0x7829, 0x782A):
    _add("lighting", f"{KEYCODES[_code]}", _code)

# --- layout sets ---
#
# A layout entry overlays the base catalog: `(category, display_name, code)`.
# If `code` matches a base entry the entry is REPLACED with the new category
# and a label of `display_name  (decode(code))`; otherwise it's appended.
# The QMK code stays in parens so picker search still finds it regardless
# of the layout-specific human name.

LayoutEntry = tuple[str, str, int]  # (category, display_name, code)


LAYOUTS: dict[str, tuple[str, tuple[LayoutEntry, ...]]] = {
    "no_mac": ("Norwegian – Mac", (
        # Letters that live at US-Mac punctuation positions.
        ("letters", "å", KC_LBRC),
        ("letters", "ø", KC_SCLN),
        ("letters", "æ", KC_QUOTE),
        # Bracket symbols are ⌥/⌥⇧ combos on Norwegian-Mac, not bare codes.
        # Hardware-verified 2026-05-29 (Task 11 step 5). NB: a window manager
        # with global ⌥ hotkeys (e.g. AeroSpace, ⌥N=workspace) will intercept
        # them before any text field; disable it to verify.
        ("symbols", "[", mod(KC_8, ALT)),
        ("symbols", "{", mod(KC_8, SHIFT, ALT)),
        ("symbols", "]", mod(KC_9, ALT)),
        ("symbols", "}", mod(KC_9, SHIFT, ALT)),
    )),
}

# Hardcoded for now. A picker UI / settings file can flip this later;
# nothing else in the catalog depends on the value being a constant.
ACTIVE_LAYOUT: str = "no_mac"


def _apply_layout(base: list[tuple[str, str, int]],
                  entries: tuple[LayoutEntry, ...]
                  ) -> list[tuple[str, str, int]]:
    by_code = {code: i for i, (_, _, code) in enumerate(base)}
    result = list(base)
    for cat, name, code in entries:
        label = f"{name}  ({decode(code)})"
        if code in by_code:
            result[by_code[code]] = (cat, label, code)
        else:
            by_code[code] = len(result)
            result.append((cat, label, code))
    return result


CATALOG: list[tuple[str, str, int]] = _apply_layout(
    _BASE_CATALOG,
    LAYOUTS[ACTIVE_LAYOUT][1] if ACTIVE_LAYOUT in LAYOUTS else (),
)

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
