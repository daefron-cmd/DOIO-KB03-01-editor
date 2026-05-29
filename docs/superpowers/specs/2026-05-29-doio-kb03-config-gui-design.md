# DOIO KB03-01 Configuration GUI — Design Spec

**Date:** 2026-05-29
**Status:** Approved design (brainstorming-duo, advisor-reviewed section by section)

## 1. Purpose

A macOS-native desktop GUI to configure a DOIO KB03-01 macropad without ever
looking up QMK keycodes by hand. It:

- displays the current keymap for any of the 4 layers and lets you remap keys
  and encoder rotations via a categorized dropdown that shows the **character it
  types on a Norwegian Mac AND the QMK keycode together** (e.g. `å  (KC_LBRC)`);
- shows a **layer selector** (you pick the layer to view/edit);
- highlights **physically pressed keys / knob turns in real time** (best effort);
- lets you change **RGB-matrix LED settings** with live preview and an explicit
  Save.

It builds directly on the existing repo code (`probe.py`, `via.py`, `listen.py`)
which already speaks the VIA raw-HID protocol (usage page `0xFF60`) via `hidapi`
and reads the keymap, encoders, and lighting state.

## 2. Scope

**In scope:** DOIO KB03-01 only, macOS only.

**Explicitly out of scope:**
- non-DOIO devices, non-macOS platforms;
- dead-key / Option-accent composed characters (combining diacritics);
- live detection of the device's *active* layer (see §10 NOTE).

## 3. Design provenance

Requirements were elicited from the user via clarifying Q&A. Decisions taken as
fixed:

- **macOS-native GUI window** — the user's explicit call, acknowledging a web or
  terminal UI would be lighter weight.
- **Keycode picker** shows character + QMK keycode together.
- **Live press display** required (user will grant Input Monitoring), but **not**
  layer-attributed.
- **Layer = app-controlled selector**; no live device-layer detection (confirmed
  not reliably doable — see §10).
- **Persistence:** keymap writes are immediate-to-EEPROM; LED changes live-preview
  with an explicit Save.

## 4. Device facts

- VID `0xD010`, PID `0x0301`. STM32F103, ws2812 RGB matrix (10 LEDs), 4 layers.
- Physical controls: **3 keys**, **2 nested rotary encoders** — an outer ring and
  an inner flush encoder with a push button.
- VIA reports a **1×5 matrix**: `[Key1, Key2, Key3, "Layers", "Knob push"]` and
  **2 encoders** (each with CCW=dir 0 / CW=dir 1).
- The keyboard exposes multiple HID interfaces: a keyboard interface
  (`0x01`/`0x06`), a consumer/mouse-shared interface, and the VIA raw-HID
  interface (`0xFF60`).

## 5. Module layout

A small package, each module with one clear job and pinned dependency direction:

```
model.py     — neutral data types (Snapshot, control_id). NO Qt, NO hardware.
core.py      — VIA transport. Owns the 0xFF60 handle. Returns RAW ints/bytes.
catalog.py   — semantics: int<->char/label, decode + encode, resolve_controls().
listener.py  — live-press worker (keyboard + consumer interfaces).
ui.py        — PySide6 presentation. Depends on core + catalog + model.
main.py      — launches the app (replaces the hello-world).
```

**Pinned dependency invariant:** `core` and `catalog` have **no dependency on
each other**. `core` = pure transport (sends VIA commands, returns raw 16-bit
ints and raw lighting bytes; **never returns strings, never imports catalog**).
`catalog` = pure semantics (no hardware, no Qt). `model.py` holds the `Snapshot`
type so that `resolve_controls(snapshot, ...)` in catalog does **not** force a
`core` import. `ui` depends on both.

Device topology constants (`KEY_LABELS`, the 1×5 column→control map, VID/PID, VIA
command IDs) live in a constants block in `core` so they survive the deletion of
`via.py`'s `main()`.

**Reuse from `via.py`:** `open_raw()`, `cmd()`, `decode()`, and `KEYCODES` are
keepers (move into `core`/`catalog`). `via.py`'s `main()` and the `read_*`/print
functions are removed. `listen.py`'s enumerate/decode logic moves into
`listener.py`. `probe.py` stays as a standalone diagnostic CLI, untouched.

## 6. Threading model

The UI thread never touches a HID handle. Two workers, two handles, two threads:

- **Control worker** — single owner of the `0xFF60` handle; processes VIA
  requests **serially** (VIA is strictly request/response, one `cmd()` at a time).
  Each `cmd()` is a blocking `dev.read(32, timeout=1000)`; running it off the UI
  thread is what prevents an up-to-1s GUI freeze on a slow/dropped reply.
- **Listener worker** — owns the keyboard + consumer handles; push-reads in a loop
  (`set_nonblocking(1)`), emits events on change.

**Threading invariant (pinned):** use the **worker-QObject-moved-to-QThread**
pattern (`moveToThread`) with **queued** signal/slot connections for *both*
workers — **not** a `QThread` subclass whose methods the UI calls directly (those
would run on the UI thread and touch the handle from the wrong thread). **The HID
handle is created inside an init slot that runs on the worker thread** (not in
`__init__` then moved), so only the worker thread ever touches it. This is what
makes "only the worker touches the handle" actually true.

## 7. Control worker — public API (coarse-grained)

Startup is ~40 sequential round-trips (4 layers × 5 cols keymap = 20; 4 × 2 enc ×
2 dir = 16; lighting ~4). The UI must not micromanage 40 replies, so the API is
snapshot-level:

- `load_all()` → performs all startup reads on the worker thread, emits **one**
  `snapshot_ready(snapshot)` signal. `Snapshot` = plain data: per-layer keymap
  ints, per-layer encoder ints, lighting values.
- `set_key(layer, col, keycode)`, `set_encoder(layer, enc, dir, keycode)` — each
  emits a small success/failure ack.
- `get_key(layer, col)`, `get_encoder(layer, enc, dir)` — single-cell reads
  (GET_KEYCODE `0x04` / GET_ENCODER `0x14` already exist in `via.py`); used for
  targeted failure-resync without a full `load_all()`.
- `set_lighting(...)` for scalars **brightness / effect / speed**, and
  `set_color(hue, sat)` which sends hue+sat as **one** `LIGHT_COLOR` command.
- `save()` → `CUSTOM_SAVE` (persists lighting to EEPROM).

`set_*` requires the **encode** path (the SET command IDs are new — only the GET
variants exist today).

## 8. Keycode catalog (`catalog.py`) — the testable heart

Pure logic, hardware-free, no Qt, no `core` import.

- `KEYCODES` (moved from `via.py`): int → QMK name.
- `decode(int) -> str` (moved from `via.py`): structural renderer — direct
  lookup, basic+mods (`code < 0x2000` → `mods<<8 | base`), layer ops (`0x52xx`),
  macros, QK_KB, USER, else `0xXXXX`.
- **encode helpers** (new code; exact inverse of decode, and they build the
  catalog table so the table doubles as test fixtures):
  - `mod(base, *mods, right=False) -> int` → `(mods<<8) | base`; side bit `0x10`
    if `right`.
  - `layer(op, n) -> int` → `0x5200 | op_bits | (n & 0x1F)` with `op_bits` from
    MO/TO/TG/DF/OSL/TT.
- **`CATALOG`** — entries grouped by category: letters / symbols / numbers /
  media / modifiers / layers / lighting / **basic-special**; mouse keys available
  from `via.py` but optional. Each entry = `(category, display_label,
  keycode_int)`; `display_label` shows char + keycode, e.g. `å  (KC_LBRC)`,
  `{  (S+A+KC_8)`, `vol+  (KC_AUDIO_VOL_UP)`, `MO(1)`.
  - **Norwegian-Mac letters:** a–z = `KC_A..KC_Z`; **å = KC_LBRC (0x2F)**, **ø =
    KC_SCLN (0x33)**, **æ = KC_QUOTE (0x34)**.
  - **Norwegian-Mac symbols** via `mod()`: `{ = mod(KC_8, SHIFT, ALT)`,
    `[ = mod(KC_8, ALT)`, `} = mod(KC_9, SHIFT, ALT)`, `] = mod(KC_9, ALT)`, etc.
  - **layers** via `layer()`: `layer(MO, 1)`, `layer(TO, 2)`, …
  - media/modifiers/lighting: direct `KEYCODES` ints.
  - **basic-special:** `KC_NO (0x0000)` ("disable this key"), `KC_TRANSPARENT
    (0x0001)` ("fall through to the layer below" — core primitive of multi-layer
    editing, surfaced prominently), plus common basics: `KC_ENTER`, `KC_ESCAPE`,
    `KC_BACKSPACE`, `KC_TAB`, `KC_SPACE`, `KC_DELETE`, arrows, Home/End/PgUp/PgDn.

**Bidirectional:**
- *Picking* (encode direction): dropdown built from `CATALOG` → `entry.keycode_int`
  → `core.set_key`.
- *Displaying* (decode direction): build a reverse index `keycode_int -> entry`
  **once**; `render(int)` returns the friendly `å (KC_LBRC)` if present, else
  falls back to structural `decode(int)`. So a device value with no catalog entry
  still renders sanely.

**Collision policy:** `keycode_int` must be **unique** across `CATALOG`;
construction **asserts** uniqueness (fail-fast — a duplicate is an authoring bug;
the assertion doubles as a test). No silent first-wins.

**Norwegian-Mac table correctness** (the real risk): the table is the reverse of
the Norwegian Apple layout — "which US-position base key + which modifiers
produce char X on a Norwegian Mac." QMK sends the HID usage + mods; macOS applies
them through the active layout. Source from the known Norwegian Apple layout, then
**verify empirically** with our own live listener (map a key to a candidate
keycode, press it, confirm the character macOS produces) — closing the loop with
the tool we're building.

## 9. Resolution logic — `resolve_controls()` (pure function)

The "which physical control flashed" logic is the branchiest code in the app and
is extracted **out of any Qt slot** into a pure, hardware-free function in
`catalog.py`:

```
resolve_controls(snapshot, iface_kind, mods, keycodes) -> list[control_id]
```

It:
1. **Folds modifiers** — the HID report's mod byte is 8-bit with separate L/R
   bits (`bit0..7 = LCtrl/LShift/LAlt/LGUI/RCtrl/RShift/RAlt/RGUI`), but QMK's
   keycode mod field is 5-bit (`0x01 Ctrl / 0x02 Shift / 0x04 Alt / 0x08 GUI /
   0x10 = right side`). A naive `(report << 8) | base` is **wrong** for any
   right-side mod. The fold:
   ```
   low  = report & 0x0F
   high = (report >> 4) & 0x0F
   qmk_mods = (high | 0x10) if high else low   # single side; QMK can't mix L+R
   ```
   **Trap:** LShift+LAlt makes report `0x06 == qmk 0x06` by coincidence, so the
   naive version passes the Norwegian-char demo and hides the bug until a
   right-side mapping. A right-side unit test guards this.
2. **Translates consumer usages** (when `iface_kind` is consumer) via the bridge
   table in §11 — media-mapped encoders emit Consumer-Page usages, not QMK
   keycodes.
3. **Reconstructs** the 16-bit keycode(s) and **matches the UNION of all 4
   layers** in the snapshot — deliberately *not* layer-specific (per the user).
4. Returns matching control ids: unique → one; same keycode on multiple controls
   → **all** (flash-all on ambiguity); non-matching / non-emitting → empty.

`control_id` is a **neutral structural position** — a plain tuple like
`("key", col)` or `("encoder", enc, dir)`, defined in `model.py`, **never a
`core`-owned type**. So `catalog` returns positions (not core types) and never
imports `core`; the UI maps those positions to widgets/labels using `core`'s
topology map. This preserves the pinned core↔catalog independence (the same
reason `Snapshot` lives in `model.py`).

## 10. Live-press listener (`listener.py`)

A QObject worker (`moveToThread`, queued connections); handles opened in the
worker-thread init slot.

- Opens the **keyboard** interface (`0x01`/`0x06`, needs Input Monitoring) and the
  **consumer/mouse-shared** interface (opens without permission; encoder turns may
  surface on **either** interface depending on mapping — `listen.py` already opens
  both, carried forward).
- **Stays pure** — it does not know the physical layout or the snapshot. It only
  decodes raw HID reports and emits `input_event(iface_kind, modifiers, keycodes)`.
  Semantic matching lives in the UI (which calls `resolve_controls`), keeping
  `core`/`catalog`/`listener` independent. (Moving the mod-fold into
  `resolve_controls` keeps the listener emitting *raw* mods.)
- **Flash lifecycle:** timed **decay** (flash ~150 ms then fade), **not** strict
  press/release pairing, so a missed/coalesced release can't leave a stuck
  highlight. Mods-only transient reports (mods set, no base keycode) are ignored
  for flashing.
- **Permission:** if the keyboard handle fails to open, emit
  `permission_state("input-monitoring-denied")`; the consumer interface and all
  `0xFF60` control still work (graceful degradation).

**NOTE (limitation, not a bug):** the keyboard interface emits the *mapped
keycode*, not physical position. Keys mapped to **non-emitting** keycodes — layer
switches MO/TO/TG, lighting keys (`RGB_TOG` etc.), `KC_NO` — produce no HID
report, so they **never flash and never appear in the live feed**. Two controls
sharing a keycode are indistinguishable (we flash both). A **last-input feed**
(decoded via catalog: `C`, `{`, `vol+`) is always correct regardless of matching.

**NOTE (longshot, record only — NOT a todo):** live active-layer detection might
be approachable later by polling VIA `switch_matrix_state` and reimplementing
QMK's layer state machine. A layer-switch key changes internal QMK state and
emits nothing on the USB wire, and VIA has no `get-active-layer` command, so this
is left as an explicit out-of-scope future exploration.

## 11. Consumer-usage → QMK-keycode bridge table

Media-mapped encoders emit on the **consumer interface** as Consumer-Page usages,
not QMK keycodes. `catalog.py` holds the bridge:

| Consumer usage | → QMK keycode |
|---|---|
| `0xE9` Volume Increment | `KC_AUDIO_VOL_UP` (`0xA9`) |
| `0xEA` Volume Decrement | `KC_AUDIO_VOL_DOWN` (`0xAA`) |
| `0xE2` Mute | `KC_AUDIO_MUTE` (`0xA8`) |
| `0xB5` Scan Next Track | `KC_MEDIA_NEXT_TRACK` (`0xAB`) |
| `0xB6` Scan Previous Track | `KC_MEDIA_PREV_TRACK` (`0xAC`) |
| `0xB7` Stop | `KC_MEDIA_STOP` (`0xAD`) |
| `0xCD` Play/Pause | `KC_MEDIA_PLAY_PAUSE` (`0xAE`) |

Flow: listener emits the raw consumer usage → UI/`resolve_controls` translates
usage → QMK keycode → matches snapshot + renders the feed (`vol+`).

**VERIFY (do first):** the consumer report's **byte offset** — where the 16-bit
usage sits (LE usage vs bitmap) — must be confirmed empirically on the real device
before trusting consumer decode (`listen.py` only dumps raw bytes today). The live
media decode depends on this.

## 12. UI layer (`ui.py`)

PySide6 `QMainWindow`. Pure presentation; both workers via signals; never touches
a HID handle.

1. **Banner strip:** renders `device_state` ("DOIO not found — plug it in" +
   Reconnect), `permission_state` ("Grant Input Monitoring" + a button opening the
   System Settings pane), and the **loading** state (from `load_all()` start until
   `snapshot_ready`). Non-blocking; `0xFF60` control works even if Input
   Monitoring is denied. Recovery = a Reconnect/Retry action re-running open +
   `load_all()`.
2. **Device widget:** visual match to the unit — 3 key caps in a row, the outer
   ring + inner knob (with push) below. Each control renders its current mapping
   via `catalog.render(snapshot_int)` for the **selected layer**. Controls are
   clickable to select+edit. Live highlight: `input_event` → `resolve_controls`
   → flash the returned control(s) with ~150 ms decay.
3. **Layer selector:** segmented 0/1/2/3. Switching just re-renders the widget
   from that layer's snapshot — **no device round-trip** (snapshot holds all
   layers).
4. **Key editor:** selecting a control + slot shows the categorized catalog combo.
   Editable slots: matrix keys Key1/2/3 (cols 0–2) and "Knob push" (col 4); col 3
   "Layers" lives in an **advanced/other** area (its physical meaning is a VERIFY
   item); encoders = 2 × {CCW dir 0, CW dir 1} (which enc index = outer ring vs
   inner is a VERIFY item). On pick → `set_key` / `set_encoder`.
   - **Post-set source of truth:** on a **success** ack the UI updates the local
     snapshot field directly and re-renders that control (no extra round-trip); on
     a **failure** ack it surfaces a small error and re-reads just that cell via
     `get_key`/`get_encoder`. `load_all()`/Reconnect is the authoritative full
     resync. The displayed mapping can never silently drift.
   - **Caution (advanced area):** overwriting col 3 "Layers" could remove the
     device's only physical layer-switch — the app remains the recovery path (can
     rewrite it back).
5. **LED panel:** effect dropdown showing **index alongside name** (`N —
   <name>`; effect names are best-guess — see VERIFY), brightness / speed / hue
   / sat sliders. Brightness slider capped at **200** (firmware render cap) with a
   small annotation. Each slider change → throttled/coalesced worker call (see
   below), applied **live** on the device. Color: moving **either** hue or sat
   sends `set_color(current_hue, current_sat)` — never a one-channel write that
   would zero the other. **"Save to keyboard"** button → `save()` (CUSTOM_SAVE).
   Initial values from snapshot.

**Slider throttle/coalesce:** a Qt slider's `valueChanged` fires continuously
while dragging; without limiting, every tick becomes a queued VIA round-trip on
the single serial worker, backing the queue up (laggy preview AND delayed
`set_key` behind the flood). Rate-limit slider→worker to **~25 Hz** and **coalesce
to the latest value** — while the worker is busy, drop intermediates and send only
the most recent when it frees up.

## 13. Persistence

- **Keymap / encoder writes** (`DYNAMIC_KEYMAP_SET_*`) persist to EEPROM
  **immediately** and survive reboot.
- **LED changes** apply **live** but persist across unplug/reboot **only** after an
  explicit `save()` (`CUSTOM_SAVE`). The UI gives live preview + a Save button.

## 14. Error / edge handling

- **Device absent:** `open_raw()` → `None` → `device_state("no-device")` →
  banner + disabled editing.
- **Input Monitoring denied:** `permission_state("input-monitoring-denied")` →
  banner; live highlighting degrades, the rest of the app still works.
- **VIA timeout / dropped reply:** worker emits a failure ack; the post-set
  failure branch resyncs the affected cell; persistent failure surfaces via the
  device banner + Reconnect.

## 15. Testing & verification

**Unit tests (hardware-free — the testable heart):**
- `mod(KC_8, SHIFT, ALT) == 0x0625`, `layer(MO, 1) == 0x5221`, `å == 0x002F`.
  (Note: KC_8's HID usage is `0x25` — `via.py` numbers KC_1..KC_9 as
  `0x1E..0x26`; `0x1F` is KC_2. `0x0625` is the correct value, not `0x061F`.)
- modifier-fold **right-side** case: report mod `0x40` (RAlt) + base → `qmk_mods
  0x14` → `0x14xx` (guards the LShift+LAlt `0x06` coincidence).
- `decode(entry.keycode_int)` renders the expected structural name for **every**
  catalog entry (roundtrip), modded entries prioritized.
- `CATALOG` keycode_int uniqueness assertion.
- consumer-usage bridge values (`0xE9 → 0xA9`, …) and reverse-index `render()`
  with `decode()` fallback for non-catalog ints.
- **`resolve_controls()` cases:** unique match → one control; same keycode on two
  controls → both (flash-all); non-matching / non-emitting → empty; consumer
  media (raw `0xE9` → `KC_AUDIO_VOL_UP` → matches a volume-mapped encoder).

**Hardware verification checklist (early, on the real device — confirmations, not
speculative todos):**
1. **Consumer report byte offset** (LE usage vs bitmap) — **do first**; the live
   media decode depends on it.
2. Encoder index ↔ outer ring vs inner.
3. col 3 "Layers" physical meaning (phantom vs real key).
4. EFFECTS index↔name ordering (set effect N, watch the LEDs).
5. Norwegian-Mac table: map → press → confirm the char macOS emits, per entry.

**Manual acceptance walkthrough (golden path — completion is NOT claimed on green
unit tests alone):** launch → DOIO detected → all 4 layers load → remap a key →
confirm macOS actually types the expected Norwegian char → live highlight flashes
the correct control → LED slider live-previews → Save.

**Persistence check via replug:** after `set_key`, unplug/replug → keymap
persisted (immediate EEPROM); LED change → unplug/replug **without** Save → did
**not** persist; change again → Save → replug → **did** persist (CUSTOM_SAVE).

## 16. Dependencies & running

- Add **`PySide6 >= 6.8`** (supports Python 3.13) to `pyproject` deps;
  `hidapi` / `pyusb` / `libusb-package` already present. Python 3.13
  (`.python-version`).
- Entry point: `main.py` launches the PySide6 app (`uv run main.py`). `probe.py`
  remains a standalone diagnostic CLI.
- First run: the app detects missing Input Monitoring and shows the banner + a
  System Settings button.
