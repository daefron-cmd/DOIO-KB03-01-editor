# doio-kb03-01

A macOS GUI to inspect and configure the **DOIO KB03-01** macropad (3 keys + a
dedicated Layers key + 1 push-knob + 2 rotary encoders) over the VIA raw-HID
interface, plus a small set of standalone probes for poking at the device's USB
and HID layers.

The repo started as a one-off `probe.py` to identify the hardware and grew into
a PySide6 app for remapping keys, binding encoder directions, driving the RGB
matrix lighting, and live-highlighting which physical control just emitted a
report.

## Target device

| Field | Value |
|---|---|
| Product | DOIO KB03-01 (current revision) |
| USB VID/PID | `0xD010` / `0x0301` |
| MCU | STM32F103 or APM32F103CBT6 — indistinguishable while running |
| Firmware | mainline QMK `keyboards/doio/kb03` with VIA enabled |
| VIA raw-HID interface | usage page `0xFF60`, usage `0x61` |
| Lighting | ws2812 RGB matrix on VIA custom channel `0x03` |

If you have the original 2023 ATmega32U4 unit (`0xFEED/0x6060`, `qmk_rgblight`),
this code will not talk to it — only the current STM32/APM32 revision is
supported. See `docs/KB03_layer_state_handoff.md` for revision details.

## What the app does

- Reads the full 4-layer × 5-column keymap and both encoders (2 encoders × 2
  directions × 4 layers) and lets you remap them from a Norwegian-Mac keycode
  catalog.
- Drives RGB matrix lighting end-to-end: live preview of effect index, speed,
  brightness, hue and saturation, with a separate `Save lighting` step that
  sends VIA `CUSTOM_SAVE` to persist.
- Highlights the physical control that produced the most recent HID report,
  matched against the snapshot keymap (works across the keyboard and consumer
  interfaces — the knob's volume usages arrive on the consumer interface).
- Tracks the active layer host-side from physical matrix presses and the
  layer-switching keycodes in the keymap, since VIA exposes no command for the
  active layer index.

## Layout

| File | Role |
|---|---|
| `core.py` | VIA raw-HID transport. Command IDs, `open_raw`, `read_all`, scalar/color writes. Returns raw ints/bytes; never imports `catalog`. |
| `model.py` | Neutral dataclasses (`Snapshot`, `LightingState`) and `control_id` constructors. No Qt, no hardware. |
| `catalog.py` | Keycode encode/decode, the Norwegian-Mac dropdown catalog, and `resolve_controls` (matches a HID report to a physical control via the snapshot). Pure logic. |
| `listener.py` | `QObject` worker for the keyboard and consumer HID interfaces. Pure report decode is unit-tested. |
| `worker.py` | `ControlWorker` — owns the VIA handle, runs `core` calls on its own thread, polls `switch_matrix_state` at ~33 Hz. |
| `inferred_layer.py` | Host-side layer model. Interprets `TO/MO/TG/DF` keycodes against physical matrix events. |
| `ui.py` | PySide6 `MainWindow`, `DevicePanel` (device photo + overlays + leader lines), the RGB panel, and the photo-calibrated LED swatch helper. |
| `main.py` | Wires the two workers onto their `QThread`s and shows the window. |
| `probe.py` | Standalone HID + libusb descriptor dump. Run this first against an unknown device. |

Threads:

- **UI thread** — `MainWindow`, painters, slots that receive worker/listener signals.
- **Control thread** — `ControlWorker`. Owns the `0xFF60` handle. UI talks to it
  exclusively via emitted signals (queued cross-thread delivery), so the handle
  is never touched from the UI thread.
- **Listener thread** — `Listener`. Owns the keyboard + consumer handles, decodes
  reports, emits `input_event`.

## Run it

```bash
uv sync
uv run python main.py
```

Requires Python 3.13 (`.python-version`). Dependencies are listed in
`pyproject.toml`: `hidapi`, `libusb-package`, `pyusb`, `PySide6`.

On first run macOS will prompt for **Input Monitoring** permission for the
keyboard HID interface. Without it, key highlights still work because the VIA
`switch_matrix_state` poll on the vendor `0xFF60` channel isn't gated by macOS,
and the consumer interface (volume knob, media keys) opens without IM either.
What you lose with IM denied is left/right modifier disambiguation and rotation
feedback for encoders bound to non-media keycodes. If the prompt never appears,
grant permission manually under System Settings → Privacy & Security → Input
Monitoring.

### Probing an unknown device

```bash
uv run python probe.py                      # defaults to 0xD010/0x0301
uv run python probe.py --vid 0xFEED --pid 0x6060
```

Prints the HID interface table, the libusb descriptor tree, and a verdict on
whether the device looks like QMK+VIA.

### Dumping the keymap and matrix shape

```bash
uv run python scripts/keymap_dump.py                # 8x8 probe rectangle, 4 encoders
uv run python scripts/keymap_dump.py --rows 4 --cols 6
```

Read-only sweep of `id_dynamic_keymap_get_keycode` over a generous rectangle
and `id_dynamic_keymap_get_encoder` for a few indices. The bounding box of
non-empty cells gives you the matrix shape on a device whose layout isn't
hardcoded into `core.py`. **Close the GUI before running it** — same
single-owner caveat as the LED probe.

### Verifying lighting effects

`scripts/probe_led_effects.py` walks effect indices 0..31, asks you what each
one looks like, and writes the result to
`docs/KB03_led_effect_probe_results.md`. **Close the GUI before running it** —
the VIA raw-HID interface is strictly single-owner (see Caveats).

```bash
uv run python scripts/probe_led_effects.py --max-index 31
```

## Custom firmware

The host app reaches everything VIA exposes at runtime. Things baked at compile
time — `MOUSEKEY_WHEEL_*` constants, encoder maps when `ENCODER_MAP_ENABLE` is
on, anything below the VIA layer — live in `firmware/`:

- `firmware/keymaps/vegar/` — the custom keymap source (4-layer mouse / media /
  lights layout with tuned mousekey wheel constants).
- `firmware/dumps/` — the `.bin`/`.hex` images actually flashed onto this unit,
  plus a stock-default rescue image to roll back to.
- `firmware/build.sh` — wraps `make doio/kb03:<keymap>`. Symlinks
  `firmware/keymaps/*/` into a sibling QMK checkout on first build.

See `firmware/README.md` for the one-time QMK setup and the flash flow. The
QMK tree itself is gitignored — clone it per machine.

## Build a macOS `.app`

```bash
./scripts/build_app_bundle.sh           # writes dist/DOIO KB03-01.app
./scripts/build_app_bundle.sh --install # also copies to /Applications
```

The bundle is a thin native launcher (`scripts/macos_launcher.c`) that records
the project path at build time, `chdir`s back to it, and execs
`uv run python main.py`. Output goes to `/tmp/doio-kb03-app.log`. The icon is
generated from `pictures/icon.png` via `scripts/png_to_icns.py`. Ad-hoc signed
with `codesign -`.

## Tests

```bash
uv run pytest
```

All tests are pure-logic (no hardware). They cover keycode decode, the
Norwegian-Mac catalog table, report decoding for both interfaces,
`resolve_controls` (including the QMK 5-bit right-mod fold edge case), the
inferred layer state machine, VIA frame shapes, and the photo-calibrated LED
swatch.

## Caveats

- **VIA raw-HID is single-owner.** Two processes opening `0xFF60` at the same
  time desync the request/response stream and the device appears to stop
  responding — symptom looks like a disconnection but it's a host-side handle
  clash. Replug won't fix it; close the other owner. Don't run any `scripts/`
  device probe while `main.py` is open, or vice versa.
- **No real active-layer query.** VIA has no command that returns the current
  active layer index; `inferred_layer.py` reconstructs it from physical matrix
  events and the `TO/MO/TG/DF` keycodes in the snapshot. The app boots assuming
  hardware-layer 0, and the small layer-LED dot in the inspector mirrors the
  *host-side* inferred layer. If hardware and host start misaligned, click the
  GUI's layer radio buttons until the on-screen dot color matches the physical
  Layers-key LED — from then on, pressing the hardware Layers key (col 3)
  advances both together via the matrix poll. Doing better would mean a custom
  QMK build that pushes layer state via `raw_hid_send`; see
  `docs/KB03_layer_state_handoff.md`.
- **Norwegian-Mac symbol catalog uses Option combos** (`⌥+KC_8` for `[`, etc.).
  A window manager that swallows global `⌥` hotkeys (e.g. AeroSpace) will
  intercept them before any text field — verify with the WM disabled if a
  symbol "doesn't type."
- **The LED color swatch is host-rendered**, not a readback from the device. It
  uses a 16-point photo-calibrated hue table (`LED_HUE_SAMPLES` in `ui.py`)
  modelling this specific KB03's diffusion, not an ideal HSV wheel.
- **Effect set is firmware-fixed.** Indices 0..31 are whatever was compiled into
  the QMK image. Adding a new pattern means recompiling and flashing the
  firmware, not changing this app. See `docs/KB03_led_findings.md`.
- **macOS only.** The `.app` packaging is Mac-specific, and the Input
  Monitoring handling and banner text assume the macOS HID permission model
  (the listener observes a denied open; the OS prompt itself comes from
  macOS, not from the app). The transport (`core.py` + `hidapi`) is
  platform-neutral — Linux likely runs with appropriate udev rules but is
  untested.

## More docs

- `docs/HID_debug_lessons.md` — the VIA `switch_matrix_state` offset-byte
  gotcha. Read this if you're adding new VIA commands.
- `docs/KB03_layer_state_handoff.md` — the long investigation into reading
  active layer state over HID and why the answer is "you can't without custom
  firmware."
- `docs/KB03_led_findings.md` — verified RGB matrix behavior and the live-vs-
  saved contract.
- `docs/KB03_led_effect_probe_results.md` — visual descriptions of each effect
  index on this specific unit.
- `docs/KB03_live_highlight_debug_handoff.md` — the matrix-poll / live-highlight
  pipeline, including the interface separation the listener relies on.
