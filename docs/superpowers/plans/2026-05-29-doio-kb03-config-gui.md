# DOIO KB03-01 Configuration GUI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A macOS-native PySide6 GUI to view/remap the DOIO KB03-01's keys, encoders, layers, and RGB lighting over VIA raw-HID, with a Norwegian-Mac keycode picker (char + QMK code) and a best-effort live key-press highlight.

**Architecture:** Layered, with a pinned dependency direction. `model.py` holds neutral data types; `core.py` is pure VIA transport (returns raw ints/bytes, never imports catalog); `catalog.py` is pure semantics (decode/encode + the Norwegian-Mac table + `resolve_controls`, never imports core); `listener.py` and the control worker run on QThreads via `moveToThread`; `ui.py` is pure presentation depending on all three. The testable heart (catalog + `resolve_controls` + VIA frame construction) is unit-tested with zero hardware; device I/O and the GUI are exercised by an explicit hardware checklist and a manual golden-path gate.

**Tech Stack:** Python 3.13, `uv`, `hidapi`/`pyusb`/`libusb-package` (present), `PySide6 >= 6.8`, `pytest`.

**Reference:** Full design at `docs/superpowers/specs/2026-05-29-doio-kb03-config-gui-design.md`.

---

## File structure

| File | Responsibility |
|---|---|
| `model.py` | Neutral data types: `Snapshot` dataclass; `control_id` helpers (`key_id`, `enc_id`). No Qt, no hardware. |
| `core.py` | VIA transport. Owns the `0xFF60` handle. Topology + command-ID constants. `open_raw`, `cmd`, `read_all`→`Snapshot`, `set_key`/`set_encoder`/`get_key`/`get_encoder`, lighting set/`set_color`/`save`. Returns raw ints/bytes. |
| `catalog.py` | Semantics: `KEYCODES`, base-keycode + modifier + layer-op constants, `decode`, `encode` helpers `mod()`/`layer()`, `CATALOG` + reverse index + `render`, `CONSUMER_USAGE` bridge, `resolve_controls`. Pure logic. |
| `listener.py` | Live-press worker (`QObject`, `moveToThread`): opens keyboard + consumer handles in an init slot, decodes reports, emits `input_event` / `permission_state`. Pure report-decode helper is unit-tested. |
| `worker.py` | Control worker (`QObject`, `moveToThread`): wraps `core` for threaded `load_all`/`set_*`/`get_*`/`save`, emits `snapshot_ready`/ack/`device_state`. |
| `ui.py` | PySide6 `QMainWindow`: banners, device widget + live highlight, layer selector, key editor, LED panel. |
| `main.py` | Entry point: builds workers + threads + window, starts the app. |
| `tests/` | `test_catalog.py`, `test_resolve.py`, `test_core_frames.py`, `test_listener_decode.py`. |

`via.py` and `listen.py` are consumed: `open_raw`/`cmd`/`decode`/`KEYCODES` relocate into `core`/`catalog`; both files are deleted once their logic is moved. `probe.py` stays untouched as a diagnostic CLI.

---

## Task 1: Project setup — deps and test harness

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

Edit the `[project]` dependencies and add a dev group:

```toml
dependencies = [
    "hidapi>=0.15.0",
    "libusb-package>=1.0.26.3",
    "pyusb>=1.3.1",
    "PySide6>=6.8",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
]
```

- [ ] **Step 2: Sync the environment**

Run: `uv sync`
Expected: resolves and installs PySide6 + pytest with no errors.

- [ ] **Step 3: Write a smoke test**

`tests/__init__.py`: empty file.

`tests/test_smoke.py`:
```python
def test_imports_work():
    import hid  # noqa: F401
    assert True
```

- [ ] **Step 4: Run it**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/test_smoke.py
git commit -m "chore: add PySide6 + pytest, test harness"
```

---

## Task 2: `model.py` — neutral data types

**Files:**
- Create: `model.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing test**

`tests/test_model.py`:
```python
from model import Snapshot, key_id, enc_id


def test_control_id_helpers_are_neutral_tuples():
    assert key_id(2) == ("key", 2)
    assert enc_id(0, 1) == ("encoder", 0, 1)


def test_snapshot_holds_layered_data():
    snap = Snapshot(
        keymap=[[0] * 5 for _ in range(4)],
        encoders=[[[0, 0] for _ in range(2)] for _ in range(4)],
        brightness=200, effect=4, speed=128, hue=170, sat=255,
    )
    assert snap.keymap[1][2] == 0
    assert snap.encoders[0][1][0] == 0
    assert snap.brightness == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'model'`.

- [ ] **Step 3: Implement `model.py`**

```python
"""Neutral data types shared by core, catalog and ui. No Qt, no hardware."""

from dataclasses import dataclass

# control_id is a neutral structural position, never a core-owned type.
ControlId = tuple


def key_id(col: int) -> ControlId:
    return ("key", col)


def enc_id(enc: int, direction: int) -> ControlId:
    return ("encoder", enc, direction)


@dataclass
class Snapshot:
    keymap: list[list[int]]            # [layer][col] -> 16-bit keycode
    encoders: list[list[list[int]]]    # [layer][enc][dir] -> 16-bit keycode
    brightness: int
    effect: int
    speed: int
    hue: int
    sat: int
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add model.py tests/test_model.py
git commit -m "feat: model.py neutral data types (Snapshot, control_id)"
```

---

## Task 3: `catalog.py` primitives — constants, `decode`, `encode`

**Files:**
- Create: `catalog.py`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write the failing test**

`tests/test_catalog.py`:
```python
from catalog import (
    KEYCODES, decode, mod, layer,
    SHIFT, ALT, MO,
    KC_8, KC_9,
)


def test_known_encode_values():
    # KC_8 HID usage is 0x25 (KC_1..KC_9 = 0x1E..0x26; 0x1F is KC_2).
    assert KC_8 == 0x25
    assert mod(KC_8, SHIFT, ALT) == 0x0625   # Norwegian Mac '{'
    assert layer(MO, 1) == 0x5221
    assert KEYCODES[0x002F] == "KC_LBRC"      # Norwegian 'å'


def test_right_side_mod_fold_is_distinct():
    # Right Alt encodes as 0x04 | 0x10 = 0x14 in the keycode mod field.
    assert mod(KC_8, ALT, right=True) == 0x1425
    assert mod(KC_8, ALT, right=True) != mod(KC_8, ALT)  # left != right


def test_decode_roundtrips_modded_value():
    assert decode(mod(KC_8, SHIFT, ALT)) == "LShift+LAlt+KC_8"
    assert decode(layer(MO, 1)) == "MO(1)"
    assert decode(0x002F) == "KC_LBRC"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog'`.

- [ ] **Step 3: Implement `catalog.py` primitives**

Move `KEYCODES` and `decode` verbatim from `via.py`, add named base/modifier/layer constants and the `mod`/`layer` encoders:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add catalog.py tests/test_catalog.py
git commit -m "feat: catalog primitives — KEYCODES, decode, mod/layer encoders"
```

---

## Task 4: `CATALOG` table, reverse index, `render`

**Files:**
- Modify: `catalog.py`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_catalog.py`)**

```python
from catalog import CATALOG, render, reverse_index


def test_catalog_keycodes_are_unique():
    seen = {}
    for cat, label, code in CATALOG:
        assert code not in seen, f"dup {code:#06x}: {label} vs {seen[code]}"
        seen[code] = label


def test_render_prefers_friendly_label_then_falls_back():
    # 'å' is in the catalog → friendly label with the QMK name.
    assert render(0x002F) == "å  (KC_LBRC)"
    # An arbitrary non-catalog int falls back to structural decode().
    assert render(0x7821) == "RGB_MOD"  # only if not added as a catalog entry
    assert render(0x1234) == decode(0x1234)


def test_basic_special_present():
    codes = {code for _, _, code in CATALOG}
    assert 0x0000 in codes  # KC_NO
    assert 0x0001 in codes  # KC_TRANSPARENT
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_catalog.py -k "catalog or render or basic" -v`
Expected: FAIL — `cannot import name 'CATALOG'`.

- [ ] **Step 3: Implement the catalog table + render**

Append to `catalog.py`:

```python
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
```

Note: `test_render_prefers_friendly_label_then_falls_back` asserts `render(0x7821) == "RGB_MOD"`. RGB_MOD *is* added under lighting with label `"RGB_MOD"`, so that holds; if you change the lighting label, update the test to match the friendly label.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catalog.py tests/test_catalog.py
git commit -m "feat: catalog table, reverse index, render with decode fallback"
```

---

## Task 5: `CONSUMER_USAGE` bridge table

**Files:**
- Modify: `catalog.py`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from catalog import CONSUMER_USAGE


def test_consumer_usage_bridges_to_qmk_keycodes():
    assert CONSUMER_USAGE[0xE9] == 0x00A9   # Vol+  -> KC_AUDIO_VOL_UP
    assert CONSUMER_USAGE[0xEA] == 0x00AA   # Vol-  -> KC_AUDIO_VOL_DOWN
    assert CONSUMER_USAGE[0xE2] == 0x00A8   # Mute  -> KC_AUDIO_MUTE
    assert CONSUMER_USAGE[0xB5] == 0x00AB   # Next  -> KC_MEDIA_NEXT_TRACK
    assert CONSUMER_USAGE[0xB6] == 0x00AC   # Prev  -> KC_MEDIA_PREV_TRACK
    assert CONSUMER_USAGE[0xB7] == 0x00AD   # Stop  -> KC_MEDIA_STOP
    assert CONSUMER_USAGE[0xCD] == 0x00AE   # Play  -> KC_MEDIA_PLAY_PAUSE
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_catalog.py -k consumer -v`
Expected: FAIL — `cannot import name 'CONSUMER_USAGE'`.

- [ ] **Step 3: Implement (append to `catalog.py`)**

```python
# Consumer-Page usage ID -> QMK keycode (media-mapped encoders emit on the
# consumer interface, not as QMK keycodes).
CONSUMER_USAGE = {
    0xE9: 0x00A9, 0xEA: 0x00AA, 0xE2: 0x00A8,
    0xB5: 0x00AB, 0xB6: 0x00AC, 0xB7: 0x00AD, 0xCD: 0x00AE,
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_catalog.py -k consumer -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catalog.py tests/test_catalog.py
git commit -m "feat: consumer-usage -> QMK keycode bridge table"
```

---

## Task 6: `resolve_controls` — the pure matching function

**Files:**
- Modify: `catalog.py`
- Test: `tests/test_resolve.py`

- [ ] **Step 1: Write the failing test**

`tests/test_resolve.py`:
```python
from model import Snapshot, key_id, enc_id
from catalog import resolve_controls, KC_A, mod, SHIFT, ALT, MO, layer


def _snap(keymap, encoders=None):
    enc = encoders or [[[0, 0] for _ in range(2)] for _ in range(4)]
    return Snapshot(keymap=keymap, encoders=enc,
                    brightness=0, effect=0, speed=0, hue=0, sat=0)


def test_unique_keyboard_match():
    # layer 0 col 1 = KC_A; pressing 'a' (base 0x04, no mods) → that one key.
    km = [[0, KC_A, 0, 0, 0]] + [[0] * 5 for _ in range(3)]
    snap = _snap(km)
    assert resolve_controls(snap, "keyboard", 0x00, [KC_A]) == [key_id(1)]


def test_flash_all_on_ambiguity():
    # KC_A on both col 0 and col 3 (even on different layers) → both flash.
    km = [[KC_A, 0, 0, 0, 0], [0, 0, 0, KC_A, 0]] + [[0] * 5 for _ in range(2)]
    snap = _snap(km)
    got = resolve_controls(snap, "keyboard", 0x00, [KC_A])
    assert set(got) == {key_id(0), key_id(3)}


def test_non_emitting_keycode_returns_empty():
    # MO(1) is mapped but never appears in a HID report → empty.
    km = [[layer(MO, 1), 0, 0, 0, 0]] + [[0] * 5 for _ in range(3)]
    snap = _snap(km)
    assert resolve_controls(snap, "keyboard", 0x00, []) == []


def test_right_side_modded_match():
    code = mod(KC_A, SHIFT, ALT)  # left Shift+Alt + A
    km = [[code, 0, 0, 0, 0]] + [[0] * 5 for _ in range(3)]
    snap = _snap(km)
    # report mod byte 0x06 = LShift|LAlt, base KC_A → matches.
    assert resolve_controls(snap, "keyboard", 0x06, [KC_A]) == [key_id(0)]


def test_consumer_media_match():
    # encoder 0 dir 1 mapped to KC_AUDIO_VOL_UP (0x00A9); consumer report
    # carries usage 0xE9, which bridges to 0x00A9.
    enc = [[[0, 0x00A9], [0, 0]]] + [[[0, 0], [0, 0]] for _ in range(3)]
    snap = _snap([[0] * 5 for _ in range(4)], encoders=enc)
    assert resolve_controls(snap, "consumer", 0x00, [0xE9]) == [enc_id(0, 1)]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: FAIL — `cannot import name 'resolve_controls'`.

- [ ] **Step 3: Implement (append to `catalog.py`)**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: PASS (all five cases).

- [ ] **Step 5: Commit**

```bash
git add catalog.py tests/test_resolve.py
git commit -m "feat: resolve_controls — pure union-match with mod fold + consumer bridge"
```

---

## Task 7: `core.py` — VIA transport + frame construction

**Files:**
- Create: `core.py`
- Test: `tests/test_core_frames.py`
- Delete: `via.py` (after moving `open_raw`/`cmd`)

This task is partly unit-tested (the exact bytes written for each VIA command, via a fake HID device) and partly hardware-only (`open_raw`, real reads — exercised by the Task 11 checklist and the golden-path gate).

- [ ] **Step 1: Write the failing test (frame construction with a fake device)**

`tests/test_core_frames.py`:
```python
import core


class FakeHID:
    def __init__(self, replies=None):
        self.writes = []
        self._replies = list(replies or [])

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, length, timeout=0):
        return self._replies.pop(0) if self._replies else [0] * length


def test_set_key_frame():
    dev = FakeHID()
    core.set_key(dev, layer=1, col=2, keycode=0x0625)
    # report-id 0x00, then [SET_KEYCODE, layer, row=0, col, hi, lo] padded to 32
    body = dev.writes[0]
    assert body[0] == 0x00
    assert body[1] == core.DYNAMIC_KEYMAP_SET_KEYCODE
    assert body[2] == 1 and body[3] == 0 and body[4] == 2
    assert body[5] == 0x06 and body[6] == 0x25
    assert len(body) == 33  # 0x00 + 32-byte body


def test_set_encoder_frame():
    dev = FakeHID()
    core.set_encoder(dev, layer=0, enc=1, direction=1, keycode=0x00A9)
    body = dev.writes[0]
    assert body[1] == core.DYNAMIC_KEYMAP_SET_ENCODER
    assert body[2] == 0 and body[3] == 1 and body[4] == 1
    assert body[5] == 0x00 and body[6] == 0xA9


def test_set_color_sends_both_channels_in_one_command():
    dev = FakeHID()
    core.set_color(dev, hue=170, sat=255)
    body = dev.writes[0]
    assert body[1] == core.CUSTOM_SET_VALUE
    assert body[2] == core.RGB_MATRIX_CHANNEL
    assert body[3] == core.LIGHT_COLOR
    assert body[4] == 170 and body[5] == 255
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_core_frames.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core'`.

- [ ] **Step 3: Implement `core.py`**

```python
"""VIA raw-HID transport for the DOIO KB03-01. Returns raw ints/bytes only —
never strings, never imports catalog. Topology + command-ID constants live here."""

import hid

from model import Snapshot

VID, PID = 0xD010, 0x0301

# device topology
KEY_LABELS = ["Key 1", "Key 2", "Key 3", "Layers", "Knob push"]
N_COLS = 5
N_ENCODERS = 2

# VIA command IDs
GET_PROTOCOL_VERSION = 0x01
GET_KEYBOARD_VALUE = 0x02
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
    """Open the 0xFF60 VIA raw-HID interface; return a handle or None."""
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_core_frames.py -v`
Expected: PASS.

- [ ] **Step 5: Delete `via.py` and fix the `listen.py` import**

`via.py`'s useful parts now live in `core` (`open_raw`/`cmd`) and `catalog` (`decode`/`KEYCODES`). Delete it:
```bash
git rm via.py
```
`listen.py` currently does `from via import KEYCODES`. It will be replaced wholesale in Task 9; for now repoint it so the repo stays importable:
edit `listen.py` line 20 from `from via import KEYCODES` to `from catalog import KEYCODES`.

- [ ] **Step 6: Run the full suite + commit**

Run: `uv run pytest -v`
Expected: PASS.
```bash
git add core.py tests/test_core_frames.py listen.py
git rm via.py
git commit -m "feat: core.py VIA transport + frames; retire via.py"
```

---

## Task 8: `listener.py` — pure report decode (unit-tested) + worker shell

**Files:**
- Create: `listener.py`
- Test: `tests/test_listener_decode.py`
- Delete: `listen.py` (logic absorbed here)

Unit-tested part: turning a raw HID report into `(iface_kind, mods, keycodes)`. Hardware-only part: opening interfaces and the read loop (exercised by the Task 11 checklist).

- [ ] **Step 1: Write the failing test**

`tests/test_listener_decode.py`:
```python
from listener import decode_keyboard_report, decode_consumer_report


def test_keyboard_report_extracts_mods_and_keys():
    # byte0 = modifiers, byte1 reserved, byte2.. = keycodes
    report = [0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]
    mods, keys = decode_keyboard_report(report)
    assert mods == 0x06
    assert keys == [0x04]


def test_keyboard_report_release_is_empty():
    report = [0x00] * 8
    mods, keys = decode_keyboard_report(report)
    assert mods == 0x00 and keys == []


def test_consumer_report_le16_usage(monkeypatch):
    # CONSUMER_USAGE_OFFSET is verified on real hardware (Task 11). The decoder
    # reads a little-endian 16-bit usage at that offset.
    import listener
    listener.CONSUMER_USAGE_OFFSET = 1
    report = [0x00, 0xE9, 0x00, 0x00]  # Vol+ = 0x00E9 LE at offset 1
    assert decode_consumer_report(report) == [0xE9]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_listener_decode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'listener'`.

- [ ] **Step 3: Implement `listener.py`**

```python
"""Live-press listener. Pure report decode (unit-tested) + a QObject worker
that opens the keyboard + consumer interfaces and emits decoded events.
Stays pure of layout/snapshot knowledge — matching happens in the UI."""

import time

import hid
from PySide6.QtCore import QObject, Signal

VID, PID = 0xD010, 0x0301

# Confirmed on real hardware in Task 11 (consumer report byte offset FIRST).
# Default assumes a 16-bit LE usage immediately after a report-id byte.
CONSUMER_USAGE_OFFSET = 1


def decode_keyboard_report(report: list[int]) -> tuple[int, list[int]]:
    """(modifiers, [keycodes]) from a boot-style keyboard report."""
    mods = report[0]
    keys = [u for u in report[2:8] if u]
    return mods, keys


def decode_consumer_report(report: list[int]) -> list[int]:
    """[consumer usage ids] — single LE16 usage at the verified offset."""
    off = CONSUMER_USAGE_OFFSET
    if len(report) < off + 2:
        return []
    usage = report[off] | (report[off + 1] << 8)
    return [usage] if usage else []


class Listener(QObject):
    input_event = Signal(str, int, list)        # iface_kind, mods, keycodes
    permission_state = Signal(str)              # "" ok / "input-monitoring-denied"

    def __init__(self):
        super().__init__()
        self._running = False
        self._devs = []  # (iface_kind, hid.device)

    def start(self):
        """init slot — runs ON the worker thread (connected queued)."""
        self._open()
        self._running = True
        self._loop()

    def stop(self):
        self._running = False

    def _open(self):
        denied = False
        for d in hid.enumerate(VID, PID):
            up, u = d["usage_page"], d["usage"]
            kind = ("keyboard" if (up, u) == (0x01, 0x06)
                    else "consumer" if up in (0x01, 0x0C) and u != 0x06
                    else None)
            if kind is None:
                continue
            try:
                dev = hid.device()
                dev.open_path(d["path"])
                dev.set_nonblocking(1)
                self._devs.append((kind, dev))
            except Exception:  # noqa: BLE001 — keyboard iface needs permission
                if kind == "keyboard":
                    denied = True
        self.permission_state.emit("input-monitoring-denied" if denied else "")

    def _loop(self):
        while self._running:
            for kind, dev in self._devs:
                data = dev.read(64)
                if not data:
                    continue
                if kind == "keyboard":
                    mods, keys = decode_keyboard_report(data)
                    if keys:  # ignore mods-only transients for flashing
                        self.input_event.emit("keyboard", mods, keys)
                else:
                    usages = decode_consumer_report(data)
                    if usages:
                        self.input_event.emit("consumer", 0, usages)
            time.sleep(0.005)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_listener_decode.py -v`
Expected: PASS.

- [ ] **Step 5: Delete `listen.py`, commit**

```bash
git rm listen.py
git add listener.py tests/test_listener_decode.py
git commit -m "feat: listener.py decode + worker; retire listen.py"
```

---

## Task 9: `worker.py` — threaded control worker

**Files:**
- Create: `worker.py`

No unit test (Qt + real device). Correctness is proven by the golden-path gate (Task 13). Keep it thin: it only marshals `core` calls onto its thread and emits results.

- [ ] **Step 1: Implement `worker.py`**

```python
"""Control worker: owns the 0xFF60 handle, runs core calls on its own thread,
emits snapshot/ack/device-state signals. moveToThread pattern — the handle is
created in start() which runs on the worker thread."""

from PySide6.QtCore import QObject, Signal, Slot

import core
from model import Snapshot


class ControlWorker(QObject):
    snapshot_ready = Signal(object)      # Snapshot
    device_state = Signal(str)           # "" ok / "no-device"
    set_ack = Signal(object, bool)       # control_id, ok
    loading = Signal(bool)

    def __init__(self):
        super().__init__()
        self._dev = None

    @Slot()
    def start(self):
        self._open_and_load()

    @Slot()
    def reconnect(self):
        self._open_and_load()

    def _open_and_load(self):
        self._dev = core.open_raw()
        if self._dev is None:
            self.device_state.emit("no-device")
            return
        self.device_state.emit("")
        self.load_all()

    @Slot()
    def load_all(self):
        if self._dev is None:
            return
        self.loading.emit(True)
        snap = core.read_all(self._dev)
        self.loading.emit(False)
        self.snapshot_ready.emit(snap)

    @Slot(int, int, int)
    def set_key(self, layer, col, keycode):
        ok = self._guarded(lambda: core.set_key(self._dev, layer, col, keycode))
        from model import key_id
        self.set_ack.emit(key_id(col), ok)

    @Slot(int, int, int, int)
    def set_encoder(self, layer, enc, direction, keycode):
        ok = self._guarded(
            lambda: core.set_encoder(self._dev, layer, enc, direction, keycode))
        from model import enc_id
        self.set_ack.emit(enc_id(enc, direction), ok)

    @Slot(int, int)
    def get_key(self, layer, col) -> int:
        return core.get_key(self._dev, layer, col)

    @Slot(int, int, int)
    def set_light_scalar(self, value_id, value):
        self._guarded(lambda: core.set_light_scalar(self._dev, value_id, value))

    @Slot(int, int)
    def set_color(self, hue, sat):
        self._guarded(lambda: core.set_color(self._dev, hue, sat))

    @Slot()
    def save(self):
        self._guarded(lambda: core.save_lighting(self._dev))

    def _guarded(self, fn) -> bool:
        if self._dev is None:
            return False
        try:
            fn()
            return True
        except Exception:  # noqa: BLE001 — surface as a failed ack/device-state
            self.device_state.emit("no-device")
            return False
```

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "import worker; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add worker.py
git commit -m "feat: worker.py threaded control worker over core"
```

---

## Task 10: `main.py` — wire workers, threads, window

**Files:**
- Modify: `main.py`

Window content is filled in by Tasks 11–13; this task stands up the app, threads, and signal wiring so the GUI launches.

- [ ] **Step 1: Implement `main.py`**

```python
import sys

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from listener import Listener
from ui import MainWindow
from worker import ControlWorker


def main() -> None:
    app = QApplication(sys.argv)

    control = ControlWorker()
    control_thread = QThread()
    control.moveToThread(control_thread)

    listener = Listener()
    listener_thread = QThread()
    listener.moveToThread(listener_thread)

    window = MainWindow(control, listener)

    # handles are created inside the workers' start slots, on their threads
    control_thread.started.connect(control.start)
    listener_thread.started.connect(listener.start)

    control_thread.start()
    listener_thread.start()
    window.show()

    code = app.exec()
    listener.stop()
    listener_thread.quit()
    control_thread.quit()
    listener_thread.wait()
    control_thread.wait()
    sys.exit(code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit (will not run until `ui.MainWindow` exists in Task 11)**

```bash
git add main.py
git commit -m "feat: main.py app wiring (workers, threads, window)"
```

---

## Task 11: HARDWARE VERIFY (early gate — needs the real device)

**Do this before trusting consumer decode or finalizing UI labels.** No code change beyond recording confirmed values as constants/comments. Requires the DOIO plugged in and Input Monitoring granted.

- [ ] **Step 1: Consumer report byte offset (FIRST).** Temporarily run a raw dump (use `probe.py` for interface discovery, then a short script that opens the consumer interface and prints `dev.read(64)` while you turn a volume-mapped knob). Confirm where the 16-bit Consumer usage sits and whether it's LE16 or a bitmap. Set `listener.CONSUMER_USAGE_OFFSET` to the confirmed offset (and adjust `decode_consumer_report` if the layout is a bitmap rather than LE16). Re-run `uv run pytest tests/test_listener_decode.py` after adjusting the test's offset to match.

- [ ] **Step 2: Encoder index ↔ ring/inner.** Turn the outer ring and inner knob; via `worker`/`core.get_encoder` or a quick script, determine which `enc` index (0/1) is the outer ring vs the inner. Record in a comment near `core.N_ENCODERS` and use it for UI labels in Task 12.

- [ ] **Step 3: col 3 "Layers" meaning.** Read `core.get_key(dev, layer, 3)` across layers and observe behavior; confirm whether col 3 is a real physical key or phantom. Record in a comment by `core.KEY_LABELS`.

- [ ] **Step 4: EFFECTS index↔name.** For a handful of effect indices, `core.set_light_scalar(dev, LIGHT_EFFECT, n)` and watch the LEDs; build the confirmed index→name list for the LED dropdown in Task 13.

- [ ] **Step 5: Norwegian table spot-check.** Map a key to `å`, `{`, `[` (Task 12 path or a script), press, confirm macOS types the expected character. Fix any `catalog` symbol entry whose `(mods, base)` is wrong and re-run `uv run pytest tests/test_catalog.py`.

- [ ] **Step 6: Commit recorded findings**

```bash
git add core.py catalog.py listener.py
git commit -m "chore: record hardware-verified constants (consumer offset, encoder map, effects)"
```

---

## Task 12: `ui.py` — window, banners, device widget, layer selector, key editor, live highlight

**Files:**
- Create: `ui.py`

Presentation only. `resolve_controls` (already tested) does the matching; the UI flashes the returned controls with a decay timer.

- [ ] **Step 1: Implement `ui.py` (window + banners + device widget + layer + editor + highlight)**

```python
"""PySide6 presentation. Depends on core (constants), catalog (semantics),
model, and the two workers via signals. Never touches a HID handle."""

from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

import core
from catalog import CATALOG, render, resolve_controls
from model import Snapshot, key_id, enc_id

# control_id -> (label, slot-setter) wiring is built from device topology.
KEY_COLS = [0, 1, 2, 4]   # Key1, Key2, Key3, Knob push (col 3 = advanced)
ENCODERS = [(0, 0), (0, 1), (1, 0), (1, 1)]  # (enc, dir); ring vs inner per Task 11


class MainWindow(QMainWindow):
    def __init__(self, control, listener):
        super().__init__()
        self.setWindowTitle("DOIO KB03-01")
        self._control = control
        self._listener = listener
        self._snapshot: Snapshot | None = None
        self._layer = 0
        self._control_buttons: dict[tuple, QPushButton] = {}
        self._selected: tuple | None = None

        root = QWidget()
        self.setCentralWidget(root)
        self._v = QVBoxLayout(root)

        self._banner = QLabel("")
        self._banner.setStyleSheet("color: #b00; font-weight: bold;")
        self._v.addWidget(self._banner)

        self._build_layer_selector()
        self._build_device_widget()
        self._build_editor()
        # LED panel added in Task 13: self._build_led_panel()

        # worker signals
        control.device_state.connect(self._on_device_state)
        control.loading.connect(self._on_loading)
        control.snapshot_ready.connect(self._on_snapshot)
        control.set_ack.connect(self._on_set_ack)
        listener.input_event.connect(self._on_input_event)
        listener.permission_state.connect(self._on_permission_state)

    # --- builders ---
    def _build_layer_selector(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Layer:"))
        self._layer_group = QButtonGroup(self)
        for ly in range(4):
            rb = QRadioButton(str(ly))
            if ly == 0:
                rb.setChecked(True)
            rb.toggled.connect(partial(self._on_layer_pick, ly))
            self._layer_group.addButton(rb)
            row.addWidget(rb)
        row.addStretch()
        self._v.addLayout(row)

    def _build_device_widget(self):
        keys_row = QHBoxLayout()
        for col in (0, 1, 2):
            btn = QPushButton("—")
            btn.clicked.connect(partial(self._select, key_id(col)))
            self._control_buttons[key_id(col)] = btn
            keys_row.addWidget(btn)
        self._v.addLayout(keys_row)

        enc_row = QHBoxLayout()
        for enc, direction in ENCODERS:
            btn = QPushButton("—")
            btn.clicked.connect(partial(self._select, enc_id(enc, direction)))
            self._control_buttons[enc_id(enc, direction)] = btn
            enc_row.addWidget(btn)
        push = QPushButton("—")  # inner push = matrix col 4
        push.clicked.connect(partial(self._select, key_id(4)))
        self._control_buttons[key_id(4)] = push
        enc_row.addWidget(push)
        self._v.addLayout(enc_row)

    def _build_editor(self):
        self._editor_label = QLabel("Select a control to edit")
        self._v.addWidget(self._editor_label)
        self._combo = QComboBox()
        for cat, label, code in CATALOG:
            self._combo.addItem(f"[{cat}] {label}", code)
        self._combo.setEnabled(False)
        self._combo.activated.connect(self._on_pick_keycode)
        self._v.addWidget(self._combo)

    # --- worker/listener slots ---
    def _on_device_state(self, state):
        self._banner.setText("DOIO not found — plug it in" if state == "no-device" else "")

    def _on_permission_state(self, state):
        if state == "input-monitoring-denied":
            self._banner.setText("Grant Input Monitoring in System Settings to see live presses")

    def _on_loading(self, busy):
        if busy:
            self._banner.setText("Reading keyboard…")
        elif self._banner.text() == "Reading keyboard…":
            self._banner.setText("")

    def _on_snapshot(self, snap: Snapshot):
        self._snapshot = snap
        self._refresh_controls()

    def _on_layer_pick(self, ly, checked):
        if checked:
            self._layer = ly
            self._refresh_controls()

    def _refresh_controls(self):
        if self._snapshot is None:
            return
        for col in (0, 1, 2, 4):
            self._control_buttons[key_id(col)].setText(
                render(self._snapshot.keymap[self._layer][col]))
        for enc, direction in ENCODERS:
            self._control_buttons[enc_id(enc, direction)].setText(
                render(self._snapshot.encoders[self._layer][enc][direction]))

    def _select(self, cid):
        self._selected = cid
        self._editor_label.setText(f"Editing {cid}")
        self._combo.setEnabled(True)

    def _on_pick_keycode(self, _index):
        if self._selected is None:
            return
        code = self._combo.currentData()
        cid = self._selected
        if cid[0] == "key":
            self._control.set_key(self._layer, cid[1], code)
        else:
            self._control.set_encoder(self._layer, cid[1], cid[2], code)

    def _on_set_ack(self, cid, ok):
        if not ok:
            self._banner.setText(f"Write failed for {cid} — resyncing")
            # targeted resync omitted for brevity; load_all() is the fallback
            self._control.load_all()
            return
        # success → update local snapshot directly (source of truth on ack)
        code = self._combo.currentData()
        if cid[0] == "key":
            self._snapshot.keymap[self._layer][cid[1]] = code
        else:
            self._snapshot.encoders[self._layer][cid[1]][cid[2]] = code
        self._refresh_controls()

    def _on_input_event(self, iface_kind, mods, keycodes):
        if self._snapshot is None:
            return
        for cid in resolve_controls(self._snapshot, iface_kind, mods, keycodes):
            self._flash(cid)

    def _flash(self, cid):
        btn = self._control_buttons.get(cid)
        if btn is None:
            return
        btn.setStyleSheet("background: #6cf;")
        QTimer.singleShot(150, lambda: btn.setStyleSheet(""))
```

- [ ] **Step 2: Launch the app against the real device**

Run: `uv run main.py`
Expected: window opens; with the DOIO plugged in, all four layers' mappings render; clicking a key + choosing a catalog entry remaps it; pressing keys flashes the matching control.

- [ ] **Step 3: Commit**

```bash
git add ui.py
git commit -m "feat: ui.py window, device widget, layer selector, editor, live highlight"
```

---

## Task 13: LED panel — effect dropdown, throttled sliders, color-as-unit, Save

**Files:**
- Modify: `ui.py`

- [ ] **Step 1: Add the LED panel builder + throttled slider handling**

Add to `ui.py` (call `self._build_led_panel()` in `__init__` after `_build_editor()`):

```python
from PySide6.QtWidgets import QSlider, QGridLayout
from PySide6.QtCore import QTimer

# index -> name, confirmed in Task 11 (best-guess until verified).
EFFECTS = [
    "SOLID_COLOR_OFF/NONE", "SOLID_COLOR", "GRADIENT_UP_DOWN",
    "GRADIENT_LEFT_RIGHT", "BREATHING", "BAND_SAT", "BAND_VAL",
]  # extend/correct per Task 11

# ... inside MainWindow ...

def _build_led_panel(self):
    grid = QGridLayout()
    self._effect = QComboBox()
    for i, name in enumerate(EFFECTS):
        self._effect.addItem(f"{i} — {name}", i)
    self._effect.activated.connect(
        lambda _i: self._control.set_light_scalar(
            core.LIGHT_EFFECT, self._effect.currentData()))
    grid.addWidget(QLabel("Effect"), 0, 0)
    grid.addWidget(self._effect, 0, 1)

    self._sliders = {}
    self._pending = {}                 # value_id/"color" -> latest value
    self._tick = QTimer(self)          # ~25 Hz coalescing flush
    self._tick.setInterval(40)
    self._tick.timeout.connect(self._flush_sliders)
    self._tick.start()

    specs = [("Brightness", core.LIGHT_BRIGHTNESS, 200),
             ("Speed", core.LIGHT_SPEED, 255),
             ("Hue", "hue", 255),
             ("Sat", "sat", 255)]
    for r, (name, key, maximum) in enumerate(specs, start=1):
        s = QSlider(Qt.Horizontal)
        s.setMaximum(maximum)          # brightness capped at 200 (render cap)
        s.valueChanged.connect(partial(self._on_slider, key))
        self._sliders[key] = s
        grid.addWidget(QLabel(name), r, 0)
        grid.addWidget(s, r, 1)

    save = QPushButton("Save to keyboard")
    save.clicked.connect(self._control.save)
    grid.addWidget(save, len(specs) + 1, 1)
    self._v.addLayout(grid)

def _on_slider(self, key, value):
    self._pending[key] = value         # coalesce to latest; flushed at 25 Hz

def _flush_sliders(self):
    if not self._pending:
        return
    pend = self._pending
    self._pending = {}
    if "hue" in pend or "sat" in pend:
        hue = self._sliders["hue"].value()
        sat = self._sliders["sat"].value()
        self._control.set_color(hue, sat)   # both channels, one command
    for key, value in pend.items():
        if key in (core.LIGHT_BRIGHTNESS, core.LIGHT_SPEED):
            self._control.set_light_scalar(key, value)
```

Also extend `_on_snapshot` to initialize the panel from the snapshot:
```python
    # in _on_snapshot, after self._snapshot = snap:
    self._effect.setCurrentIndex(min(snap.effect, self._effect.count() - 1))
    self._sliders[core.LIGHT_BRIGHTNESS].setValue(min(snap.brightness, 200))
    self._sliders[core.LIGHT_SPEED].setValue(snap.speed)
    self._sliders["hue"].setValue(snap.hue)
    self._sliders["sat"].setValue(snap.sat)
```

- [ ] **Step 2: Launch and exercise the LED panel**

Run: `uv run main.py`
Expected: dragging brightness/speed/hue/sat live-previews on the device without lag; moving hue alone does not zero sat; Save persists.

- [ ] **Step 3: Commit**

```bash
git add ui.py
git commit -m "feat: LED panel — effect dropdown, throttled sliders, color-as-unit, Save"
```

---

## Task 14: Completion gate — manual golden-path acceptance

**Not claimed on green unit tests alone.** Requires the real device + Input Monitoring.

- [ ] **Step 1: Walk the golden path and check each step**
  1. `uv run main.py` → window opens.
  2. DOIO detected (no "not found" banner); all 4 layers load.
  3. Remap Key 1 on layer 0 to `å` via the dropdown.
  4. In a text field, press Key 1 → macOS types `å`.
  5. Press Key 1 → the Key 1 control flashes (live highlight).
  6. Turn a volume-mapped knob → the matching encoder control flashes and the feed/highlight reflects it.
  7. Drag an LED slider → live preview on the device.
  8. Click Save.

- [ ] **Step 2: Record the result** in the PR/commit description (pass/fail per step). If any step fails, open a fix task before proceeding.

---

## Task 15: Completion gate — replug persistence

- [ ] **Step 1: Keymap persistence.** After remapping Key 1 (Task 14), unplug and replug the DOIO. Reopen the app → Key 1 still maps to `å` (immediate EEPROM, no Save needed).

- [ ] **Step 2: LED non-persistence without Save.** Change the effect/brightness but do NOT click Save; unplug/replug → the LED setting reverts (live-only).

- [ ] **Step 3: LED persistence with Save.** Change the LED setting again, click Save, unplug/replug → the setting persists (CUSTOM_SAVE → EEPROM).

- [ ] **Step 4: Record the result** in the PR/commit description.

---

## Self-review notes (spec coverage)

- Norwegian-Mac char+keycode picker → Tasks 3–4 (`CATALOG`, `render`), verified in Task 11/14.
- Bidirectional catalog → `render` (Task 4) + `mod`/`layer` encode (Task 3).
- `resolve_controls` four cases → Task 6.
- Consumer bridge + byte-offset verify → Tasks 5, 8, 11.
- Two handles / two threads / `moveToThread` + init-slot handle creation → Tasks 8–10.
- Coarse worker API (`load_all`/`set_*`/`get_*`/`set_color`/`save`) → Tasks 7, 9.
- Layer selector as snapshot re-render; post-set source-of-truth (update on ack, resync on failure) → Task 12.
- LED color-as-unit, ~25 Hz throttle/coalesce, brightness cap 200, effect index labels, Save → Task 13.
- Banners for no-device / Input-Monitoring-denied → Tasks 9, 12.
- EEPROM-immediate vs LED-Save persistence → Task 15.
- Hardware VERIFY checklist with consumer-offset FIRST → Task 11.
