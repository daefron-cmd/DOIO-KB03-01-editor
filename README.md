# DOIO KB03-01 Control Center

A macOS companion app and optional custom QMK firmware for the wonderfully
over-specific **DOIO KB03-01** macropad: three keys, a layer button, a push-knob,
and two rotary encoders.

The app turns the pad's VIA raw-HID interface into a visual control center. It
can inspect and remap the four-layer keymap, configure RGB matrix lighting,
identify controls as you use them, and give the outer ring MX Master-style
accelerated scrolling when paired with the included firmware.

> [!IMPORTANT]
> This is an independent enthusiast project, not an official DOIO utility. It
> targets one specific hardware revision; confirm the VID/PID below before
> using the app or flashing firmware.

## Download

Tagged releases attach a self-contained Apple-silicon macOS app and its SHA-256
checksum on the [GitHub Releases](https://github.com/daefron-cmd/DOIO-KB03-01-editor/releases)
page. Download the `arm64.zip`, extract it, and move `DOIO KB03-01.app` to
Applications. No Python installation or source checkout is required.

The automated beta build is ad-hoc signed, not Apple-notarized. Gatekeeper may
therefore require you to approve the app explicitly in System Settings →
Privacy & Security after the first launch attempt. A Developer ID-signed and
notarized release can replace it later without changing the bundle format.

Verify a download from the directory containing both release files:

```bash
shasum -a 256 -c DOIO-KB03-01-v0.1.0-macOS-arm64.zip.sha256
```

## Run from source

You need macOS 13 or newer, Python 3.13, [`uv`](https://docs.astral.sh/uv/), and
a current-revision KB03-01 connected over USB.

```bash
uv sync --frozen
uv run python main.py
```

If `uv` is not installed yet, follow its
[official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
The required Python version is recorded in `.python-version`; `uv` can install
it automatically. Runtime dependencies are locked in `uv.lock`.

The GUI works with the device's regular VIA firmware. Flashing the custom
firmware is optional and is only needed for the host-assisted outer-ring scroll
behavior. On first launch, macOS may ask for Input Monitoring and Accessibility
permissions; the app explains what remains available if either is denied.

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
- Opens a non-modal infinite-text Scroll Lab from the Scroll Feel panel, with
  numbered virtual rows and a fixed calibration marker for comparing precision,
  acceleration, coast, and reverse braking while tuning the outer ring.

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
| `scroll_lab.py` | Virtual infinite-text calibration window for tuning the outer-ring scroll model. |
| `main.py` | Wires the two workers onto their `QThread`s and shows the window. |
| `probe.py` | Standalone HID + libusb descriptor dump. Run this first against an unknown device. |

Threads:

- **UI thread** — `MainWindow`, painters, slots that receive worker/listener signals.
- **Control thread** — `ControlWorker`. Owns the `0xFF60` handle. UI talks to it
  exclusively via emitted signals (queued cross-thread delivery), so the handle
  is never touched from the UI thread.
- **Listener thread** — `Listener`. Owns the keyboard + consumer handles, decodes
  reports, emits `input_event`.

## macOS permissions

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

### Watching physical matrix presses

```bash
uv run python scripts/matrix_state.py
```

Prints the currently pressed matrix columns whenever they change. This is the
smallest diagnostic for live-highlight or layer-button problems. Close the GUI
first because this probe also owns the VIA raw-HID interface.

### Verifying lighting effects

`scripts/probe_led_effects.py` walks effect indices 0..31, asks you what each
one looks like, and writes the result to
`docs/KB03_led_effect_probe_results.md`. **Close the GUI before running it** —
the VIA raw-HID interface is strictly single-owner (see Caveats).

```bash
uv run python scripts/probe_led_effects.py --max-index 31
```

## Custom firmware (optional)

The host app reaches everything VIA exposes at runtime. Things baked at compile
time — `MOUSEKEY_WHEEL_*` constants, encoder maps when `ENCODER_MAP_ENABLE` is
on, anything below the VIA layer — live in `firmware/`:

- `firmware/keymaps/vegar/` — the custom keymap source (4-layer mouse / media /
  lights layout with tuned mousekey wheel constants).
- `firmware/dumps/` — the `.bin`/`.hex` images actually flashed onto this unit,
  plus a stock-default rescue image to roll back to.
- `firmware/build.sh` — wraps `make doio/kb03:<keymap>`. Symlinks
  `firmware/keymaps/*/` into a sibling QMK checkout on first build.

See [`firmware/README.md`](firmware/README.md) for the one-time QMK setup,
firmware checksums, and flash flow. The QMK tree itself is gitignored — clone it
per machine. Flashing the wrong image can leave the macropad temporarily
unusable, so verify the USB identity and keep the rescue image available.

## Build a local macOS `.app`

```bash
./scripts/build_app_bundle.sh           # writes dist/DOIO KB03-01.app
./scripts/build_app_bundle.sh --install # also copies to /Applications
```

This is a local convenience bundle, not a redistributable release build: the
native launcher (`scripts/macos_launcher.c`) records the checkout path and uses
that checkout's virtual environment. Keeping the bundle executable alive is
required for macOS Accessibility permission to bind to `DOIO KB03-01.app`.
Output goes to `/tmp/doio-kb03-app.log`; the bundle is ad-hoc signed with
`codesign -`.

## Build a distributable macOS app

```bash
uv sync --frozen --group package
./scripts/build_release.sh
```

This creates a self-contained, relocatable app plus a ZIP and SHA-256 file in
`dist/releases/`. The archive name includes the version from `version.py` and
the build machine's architecture. The builder verifies the embedded version,
property list, code signature, archive integrity, and bundled dependency
notices before returning success.

Pushing a matching semantic-version tag such as `v0.1.0` runs the release
workflow and creates a GitHub prerelease with the ZIP and checksum attached.
The tag must match both `version.py` and `pyproject.toml`.

For a Gatekeeper-friendly public release, set `MACOS_CODESIGN_IDENTITY` to a
Developer ID Application identity while building. Submit the ZIP with Apple's
`notarytool`; after acceptance, staple the ticket to the `.app`, then recreate
the ZIP and checksum before publishing. Apple Developer Program credentials are
not stored in this repository, so the automated workflow currently produces an
ad-hoc-signed beta.

## Tests

```bash
uv run --frozen ruff check .
uv run --frozen pytest
bash -n scripts/build_app_bundle.sh firmware/build.sh
```

The automated suite is hardware-free. It covers keycode decode, the
Norwegian-Mac catalog table, report decoding for both interfaces,
`resolve_controls` (including the QMK 5-bit right-mod fold edge case), the
inferred layer state machine, VIA frame shapes, and the photo-calibrated LED
swatch. Pull requests run these checks on macOS in GitHub Actions.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the small-project contribution
workflow and the details that make hardware reports actionable.

## Versioning and license

The first public release is `0.1.0`: functional and useful on the confirmed
hardware, with compatibility and packaging still allowed to evolve. Releases
use semantic version tags such as `v0.1.0`.

This project is licensed under
[GNU GPL version 2 or later](LICENSE). Third-party components included in the
prebuilt app retain their own licenses; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

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
