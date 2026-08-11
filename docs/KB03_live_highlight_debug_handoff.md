# DOIO KB03-01 Live Highlight Debug Handoff

**Date:** 2026-06-07  
**Repo:** this repository
**User-facing symptom:** the GUI can highlight DOIO controls only when those
controls are mapped to media/consumer functions. Controls mapped to ordinary
keyboard keys do not highlight.

> This is a historical investigation record. The `scratch_*` scripts mentioned
> in some captured steps were disposable diagnostics and were not retained.
> Use `scripts/matrix_state.py` for the maintained VIA matrix-state probe.

## Current Status

The PySide GUI launches and can read/write the DOIO over VIA raw HID. Keymap,
encoder mappings, and LED settings are visible and editable. Media-mapped encoder
turns still produce live feedback because they arrive over the consumer HID
interface.

Normal keyboard-key feedback does not work. The GUI currently shows:

```text
Keyboard HID is blocked; key highlights are using VIA fallback
```

The first VIA fallback attempt did not flash physical keys because it parsed the
wrong byte. That has now been patched; see "VIA Matrix Fallback Parse Fix" below.

## Relevant Files

- `main.py` starts the PySide app, two worker threads, and the main window.
- `core.py` owns VIA raw-HID transport helpers.
- `worker.py` owns the VIA raw-HID handle on a `QThread`.
- `listener.py` opens keyboard/consumer HID interfaces for live input reports.
- `ui.py` displays the GUI and flashes controls.
- `scratch_keyboard_dump.py` dumps raw keyboard-interface HID reports.
- `scripts/matrix_state.py` dumps VIA `switch_matrix_state` physical key state.
- `scripts/build_app_bundle.sh` builds a macOS `.app` wrapper.
- `scripts/macos_launcher.c` is the native launcher used by the `.app`.

## Architecture Summary

There are two live-highlight paths:

1. **HID listener path**

   `listener.py` opens:

   - keyboard interface: usage page `0x01`, usage `0x06`
   - consumer/shared interface: usage page `0x01`/`0x0C`, non-keyboard usages

   It emits:

   ```python
   input_event(iface_kind, mods, keycodes)
   ```

   Then `ui.py` calls `catalog.resolve_controls(snapshot, iface_kind, mods,
   keycodes)` and flashes matching controls.

2. **VIA fallback path**

   Added during debugging. `worker.py` polls:

   ```python
   core.pressed_cols(dev)
   ```

   which sends VIA:

   ```text
   GET_KEYBOARD_VALUE (0x02), SWITCH_MATRIX_STATE (0x03)
   ```

   Expected result: a 1-row bitmask for physical matrix columns `0..4`. The
   worker emits `matrix_press(key_id(col))`, and `ui.py` flashes that physical
   key directly.

## Observations

### Media/Consumer Reports Work

Media-mapped controls highlight. This path uses the consumer interface, not the
keyboard interface.

Previously hardware-verified consumer reports:

```text
04 E9 00 = Volume Up usage 0x00E9
04 EA 00 = Volume Down usage 0x00EA
04 00 00 = release
```

`listener.CONSUMER_USAGE_OFFSET = 1`.

The catalog maps consumer usages to QMK keycodes:

```python
0xE9 -> KC_AUDIO_VOL_UP   (0x00A9)
0xEA -> KC_AUDIO_VOL_DOWN (0x00AA)
0xE2 -> KC_AUDIO_MUTE     (0x00A8)
0xB5 -> KC_MEDIA_NEXT_TRACK
0xB6 -> KC_MEDIA_PREV_TRACK
0xB7 -> KC_MEDIA_STOP
0xCD -> KC_MEDIA_PLAY_PAUSE
```

### Keyboard HID Open Fails

From both Terminal and Ghostty, after granting Input Monitoring, the diagnostic:

```bash
uv run python scratch_keyboard_dump.py
```

prints:

```text
FAIL keyboard iface 0: open failed
No keyboard interface opened. Check macOS Input Monitoring.
```

So the process cannot open the keyboard HID interface at all. This is lower-level
than shortcut interception. No ordinary keyboard reports are available to the app.

### Input Monitoring State

The user showed macOS Input Monitoring with both Ghostty and Terminal enabled.
Toggling permission and fully restarting the launching terminal did not fix the
keyboard HID open failure.

### AeroSpace

The user runs AeroSpace. Their config at `~/.aerospace.toml` binds many global
`alt-*` and `alt-shift-*` shortcuts:

```toml
alt-h = 'focus left'
alt-j = 'focus down'
alt-k = 'focus up'
alt-l = 'focus right'
alt-1 = 'workspace 1'
...
alt-shift-1 = 'move-node-to-workspace 1'
...
alt-minus = 'resize smart -50'
alt-equal = 'resize smart +50'
```

This can absolutely swallow key combinations after they become macOS keyboard
events, especially Norwegian-Mac symbols that use Option/Alt or Option+Shift.

However, AeroSpace does **not** explain:

```text
hid.device().open_path(...) -> open failed
```

That failure occurs before any keyboard event is delivered to AeroSpace.

We suggested this A/B test:

```bash
aerospace enable off
uv run python scratch_keyboard_dump.py
aerospace enable on
```

The result was not recorded here.

## Code Changes Already Made

### 1. Keyboard Report Decoder Made More Flexible

Original decoder assumed an 8-byte boot report:

```text
[mods, reserved, key1, ...]
```

We added support for report-ID-prefixed keyboard reports:

```text
[report_id, mods, reserved, key1, ...]
```

This was necessary because otherwise a report like:

```text
01 00 00 04 ...
```

would be decoded as `mods=0x01`, `key=KC_A`, causing the GUI to search for
`⌃+KC_A` instead of plain `KC_A`.

File:

```python
listener.py
```

Relevant test:

```python
tests/test_listener_decode.py::test_keyboard_report_extracts_report_id_prefixed_payload
```

But this fix cannot help while the keyboard HID interface cannot be opened.

### 2. Listener Now Reports Keyboard HID Failure Reliably

`listener.py` now treats "no keyboard interface opened" as
`input-monitoring-denied`, not only explicit exceptions.

### 3. Banner Handling Was Fixed

Previously, the control worker could clear the Input Monitoring warning after the
listener reported it. `ui.py` now tracks independent states:

```python
self._device_state
self._permission_state
self._matrix_state
self._is_loading
```

The banner now remains visible when keyboard HID is blocked.

### 4. VIA Matrix Fallback Was Added

`core.py`:

```python
SWITCH_MATRIX_STATE = 0x03

def pressed_cols(dev) -> list[int] | None:
    r = cmd(dev, GET_KEYBOARD_VALUE, SWITCH_MATRIX_STATE, 0x00, timeout=100)
    if not r or r[0] == 0xFF or len(r) < 4:
        return None
    if r[0] != GET_KEYBOARD_VALUE or r[1] != SWITCH_MATRIX_STATE:
        return None
    row = r[3]
    return [col for col in range(N_COLS) if row & (1 << col)]
```

`worker.py` polls this every 30 ms and emits physical `key_id(col)` on rising
edges.

`ui.py` connects:

```python
control.matrix_press.connect(self._flash)
```

The GUI banner says fallback is active. After the parse fix, expected raw replies
are:

```text
no key:  02 03 00 00 ...
col 0:   02 03 00 01 ...
col 1:   02 03 00 02 ...
col 2:   02 03 00 04 ...
col 3:   02 03 00 08 ...
col 4:   02 03 00 10 ...
```

Possible explanations:

- `switch_matrix_state` still returns all-zero rows because the firmware lacks
  `VIA_INSECURE` or is locked by QMK secure handling.
- `switch_matrix_state` returns a different report shape than upstream VIA.
- The polling interferes with other raw-HID commands.
- The fallback is flashing the wrong control or style reset hides it quickly.

The predecessor of `scripts/matrix_state.py` was added to investigate this
directly.

### 5. VIA Matrix Fallback Parse Fix

A consultant identified an off-by-one parse bug in the first fallback
implementation.

QMK's VIA `id_switch_matrix_state` response shape is:

```text
data[0] = command id             0x02
data[1] = value id               0x03
data[2] = offset                 0x00
data[3] = first matrix row byte
```

The previous code sent only `02 03` and read `r[2]` as the row. That reads the
offset byte, normally `0x00`, so the fallback looked "available" but always saw no
pressed columns.

Patched behavior:

```python
r = cmd(dev, GET_KEYBOARD_VALUE, SWITCH_MATRIX_STATE, 0x00, timeout=100)
row = r[3]
```

Tests now assert this exact request/reply shape in
`tests/test_core_frames.py::test_pressed_cols_reads_switch_matrix_state`.

### 6. Layer Button Capture

Captured with:

```bash
uv run python scripts/matrix_state.py
```

while pressing the DOIO layer/change button:

```text
pressed cols: [3]
pressed cols: []
pressed cols: [3]
pressed cols: []
pressed cols: [3]
pressed cols: []
pressed cols: [3]
pressed cols: []
```

So the physical layer/change button is matrix column `3`, matching the existing
`core.KEY_LABELS` comment.

The GUI originally handled raw matrix `key_id(3)` specially. It now uses a small
pure host-side layer model in `inferred_layer.py` instead:

- resolve physical matrix key presses through the current inferred active layers;
- honor `KC_TRANSPARENT` fallthrough;
- handle `TO(n)`, `MO(n)`, `TG(n)`, and `DF(n)`;
- consume matrix release events for `MO(n)`;
- update the GUI radio selector from the inferred highest active layer.

This does not read QMK's active layer state directly. It is deliberately safe:
no firmware dump, no flashing, no unknown writes, no EEPROM modification. It only
uses the already-read keymap snapshot plus read-only VIA `switch_matrix_state`.

## Tests Run

Current unit tests pass after the parse fix:

```text
25 passed
```

These tests are hardware-free. They verify frame construction and expected decode
logic, not the real macOS HID permission behavior.

## macOS App Wrapper Attempt

Because Terminal/Ghostty might have problematic TCC identity, we built a normal
`.app` wrapper.

Generated app:

```text
/Applications/DOIO KB03-01.app
```

It contains:

- a valid signed arm64 Mach-O launcher
- `NSInputMonitoringUsageDescription`
- bundle id `local.doio-kb03-01`

The original launcher attempt ran:

```bash
cd /path/to/doio-kb03-01
/opt/homebrew/bin/uv run python main.py
```

Log file:

```text
/tmp/doio-kb03-app.log
```

Result: launching through the app wrapper still shows:

```text
Keyboard HID is blocked; key highlights are using VIA fallback
```

So packaging as an app did not solve keyboard HID access.

## Recommended Next Diagnostics

### 1. Confirm VIA Matrix Report Shape

Run the maintained read-only probe with the GUI closed:

```bash
cd /path/to/doio-kb03-01
uv run python scripts/keymap_dump.py --rows 1 --cols 5
```

Press each physical key, including:

- Key 1 / col 0
- Key 2 / col 1
- Key 3 / col 2
- layer/back button / col 3
- knob push / col 4

Record output.

If it prints:

```text
switch_matrix_state unsupported or unhandled
```

then VIA fallback cannot work on stock firmware.

If it prints only:

```text
pressed cols: []
```

even while keys are held, then our `row = r[2]` assumption is likely wrong. Modify
the diagnostic to print the raw VIA reply bytes from `cmd(dev, 0x02, 0x03)`.

### 2. Print Raw `switch_matrix_state` Replies

Temporary diagnostic:

```python
import time
import core

dev = core.open_raw()
while True:
    r = core.cmd(dev, core.GET_KEYBOARD_VALUE, core.SWITCH_MATRIX_STATE, timeout=100)
    print(" ".join(f"{b:02X}" for b in r))
    time.sleep(0.1)
```

Press and hold keys while watching which byte changes.

### 3. Confirm macOS HID Open Failure Outside Python

Use a tiny native Swift or C IOHID test that tries to open the keyboard interface.
This will distinguish:

- Python/hidapi-specific failure
- macOS/TCC/IOHID permission failure for any process

If native IOHID opens the keyboard interface, the Python `hidapi` backend/path is
the issue. If native IOHID also fails, this is macOS permission/device policy.

### 4. Try Quitting AeroSpace Completely

Even though AeroSpace should not cause `open_path` failure, test it anyway:

```bash
aerospace enable off
```

or quit AeroSpace.app entirely, then run:

```bash
uv run python scratch_keyboard_dump.py
```

If the keyboard interface opens only when AeroSpace is off, then Aerospace is
doing something deeper than ordinary shortcut interception.

### 5. Check Other HID/TCC Tools

Look for other tools that may own or transform keyboard input:

- Karabiner-Elements
- BetterTouchTool
- Keyboard Maestro
- Hammerspoon
- LinearMouse
- SteerMouse
- Logitech Options/Options+

Any of these could affect event delivery, but again they should not normally
prevent opening a HID device path.

## Current Hypothesis

There are likely two separate issues:

1. **Keyboard HID interface cannot be opened** from Python/hidapi on this macOS
   setup despite visible Input Monitoring permissions.

2. **AeroSpace can swallow Option/Alt-based mapped shortcuts** after they become
   keyboard events, especially Norwegian-Mac symbols and any DOIO key mapped to
   `Alt-*` / `Alt-Shift-*`.

The first issue blocks ordinary-key live highlighting. The second issue can block
typed output or app-level behavior even after HID access is solved.

## Useful Commands

Launch GUI through terminal:

```bash
uv run python main.py
```

Launch installed app:

```bash
open "/Applications/DOIO KB03-01.app"
```

Check app log:

```bash
tail -100 /tmp/doio-kb03-app.log
```

Keyboard HID diagnostic:

```bash
uv run python scratch_keyboard_dump.py
```

VIA matrix diagnostic:

```bash
uv run python scripts/matrix_state.py
```

Rebuild app wrapper:

```bash
scripts/build_app_bundle.sh
cp -R "dist/DOIO KB03-01.app" /Applications/
```
