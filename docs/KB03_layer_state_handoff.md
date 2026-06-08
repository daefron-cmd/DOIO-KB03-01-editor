# DOIO KB03-01 — Reading Layer State over HID: Handoff

**Goal:** expose the macropad's *currently active layer* to the host over HID so a
companion app can react to layer changes.

**Bottom line up front:** the stock VIA protocol has **no command that returns the
active layer index**. `switch_matrix_state` reports physical switch closures only,
not `layer_state`. The reliable path is a custom QMK build (the device is
DFU-flashable) that pushes layer state via `raw_hid_send`, or answers a custom
`via_command_kb` sub-command. Everything below supports that conclusion and gives
the concrete next steps.

---

## 1. Device identity (confirmed from this unit)

From `system_profiler` + `probe.py` on the actual hardware:

| Field | Value | Meaning |
|---|---|---|
| USB Vendor ID | `0xD010` | DOIO's real assigned VID (not the QMK default `0xFEED`) |
| USB Product ID | `0x0301` | matches mainline `keyboards/doio/kb03` |
| bcdDevice (Product Version) | `0x0001` | firmware `DEVICE_VER` = v0.0.1 |
| Link speed | 12 Mb/s | USB Full Speed — true of both AVR and STM32F103, **not** decisive |
| Power | 500 mA requested | standard, not decisive |

**Interpretation:** this is the **current revision**, the one `core.py` is already
written against — *not* the original ATmega32U4 unit (which enumerated with the
QMK-default `0xFEED/0x6060` and used `qmk_rgblight`). The running USB descriptor
**cannot** tell us whether the silicon is a genuine ST STM32F103 or a Geehy
**APM32F103CBT6** clone; DOIO ships both interchangeably and they enumerate
identically while running.

### Hardware revisions seen in the wild

| Revision | MCU | Matrix | Lighting | VIA IDs | QMK source |
|---|---|---|---|---|---|
| Original (2023) | ATmega32U4 | 4×8 declared | `qmk_rgblight` | `0xFEED/0x6060` | never upstreamed; keebmonkey `kb03-01.json` |
| **Current (this unit)** | STM32F103 **or** APM32F103CBT6 | 1×5 | ws2812 **RGB matrix**, 10 LEDs | `0xD010/0x0301` | mainline `keyboards/doio/kb03` |

The mainline "add support" issue (#21041) was closed as *not planned*, but a
`keyboards/doio/kb03` board now exists in-tree (the kb16/kb30 siblings were the
templates). DOIO moved the kb16 from 32U4 (rev1) to APM32F103CBT6 (rev2) during the
32U4 shortage — same playbook likely applied to the kb03.

### Vendor download files

The vendor-provided `/Users/vegar/Downloads/kb03-01.json` is a VIA definition for
the older public identity:

- name: `DOIO`
- VID/PID: `0xFEED/0x6060`
- lighting metadata: `qmk_rgblight`
- matrix: `4` rows × `8` cols
- layout entries include `0,0`, `0,1`, `0,2`, `0,3`, `0,4`, `0,5`, `0,6`,
  `1,5`, and `1,6`

That file explains the old public VIA layout, but it does not match this unit's
live USB identity or observed RGB-matrix channel behavior.

The vendor-provided `/Users/vegar/Downloads/kb09-01.bin` is an ARM firmware image
despite the `kb09` filename. Embedded strings identify it as QMK-builder firmware
with `VID: 0xFEED(qmkbuilder) PID: 0x6060(DOIO)`, build date `Sep 24 2022`, and
QMK RGB Matrix strings including `rgb_matrix_config.mode`,
`rgb_matrix_config.hsv.h`, `rgb_matrix_config.hsv.s`, `rgb_matrix_config.hsv.v`,
and `rgb_matrix_config.speed`.

Treat both files as evidence for the older vendor/QMK-builder firmware family,
not as source of truth for the current `0xD010/0x0301` hardware. Do not flash
`kb09-01.bin` to this KB03 unless the target model, MCU, and bootloader match are
confirmed separately.

---

## 2. Definitive MCU disambiguation (do this if the exact die matters)

The decisive signal is the **bootloader** VID/PID, not the running firmware. Put the
device into flashing mode and re-run `probe.py` (or `lsusb` / `system_profiler`)
against the device that appears:

| Bootloader VID:PID | Identity | Implies |
|---|---|---|
| `1EAF:0003` ("LeafLabs Maple") | STM32duino bootloader | STM32F103 **or** APM32F103CBT6 — **most likely** |
| `03EB:2FF4` ("Atmel Corp. ATmega32U4") | Atmel-DFU | old AVR revision |
| `0483:DF11` ("STM Device in DFU Mode") | ST/APM factory DFU | unlikely (F103 ships no USB DFU) |

Bootloader entry:
- **AVR rev:** hold the upper-left key while plugging in (Caterina/Atmel-DFU).
- **STM32F103/APM32 rev:** bridge BOOT0→VCC + tap RESET (or a boot button if DOIO
  exposed one), then flash with `dfu-util`.

### Zero-reboot confirmation (no bootloader needed)

Run `main.py` (or `core.read_all` from a REPL). The transport reads lighting on
the **custom RGB-matrix channel `0x03`**, which only the current ws2812-RGB-matrix
firmware answers. If the GUI populates with **4 layers**, the keymap, both
encoders, and valid brightness/effect/speed/color from channel `0x03`, you're
confirmed on the STM32/APM32 build. If channel `0x03` returns `0xFF` while LEDs
are clearly lit, it's the older `qmk_rgblight` build.

---

## 3. Why `switch_matrix_state` can't read the layer

`switch_matrix_state` is `id_switch_matrix_state = 0x03`, a **sub-ID** under
`id_get_keyboard_value = 0x02` (confirmed in `quantum/via.h`). Its handler returns
the debounced **physical** matrix scan (`matrix_get_row()` per row), which runs
*before* any layer/keymap logic.

- `layer_state` is a separate `uint32_t` bitmask; it is never projected back into
  the matrix.
- On this firmware the back button is matrix **column 3** ("Layers" in
  `core.KEY_LABELS`), mapped to a layer keycode. Polling `switch_matrix_state` shows
  column 3 *transiently* high while it's physically pressed — it does **not** hold a
  value representing "layer 2 is active."
- The handler is also **optional**; a minimal VIA build can return `id_unhandled`
  (`0xFF`). Probe it: send `02 03` and check whether you get a row-bitmask byte
  (one byte per row, cols packed as bits — for this 1×5 matrix that's a single
  byte at offset 3 with bits 0..4 representing cols 0..4) or `0xFF`.
  `core.pressed_cols` is the in-tree implementation.

**Prior-art search result:** nobody uses `switch_matrix_state` for layer detection.
Every published approach uses one of the methods in §4.

---

## 4. Recommended implementation (custom QMK build)

The device is DFU-flashable, so this is the clean path. Base the build on the
in-tree `keyboards/doio/kb03` (fall back to the kb30 lineage if needed). Pick **one**
of the two readout mechanisms — push is simpler and lower-latency.

### Option A — Push on change (preferred)

Fires a report from the keyboard whenever the layer changes. This is the
`qmk-hid-host` pattern; the `0xCC` magic first byte keeps it from colliding with
VIA's own raw-HID replies, so the host can filter unsolicited layer reports from
command responses.

```c
#include "raw_hid.h"   // RAW_ENABLE is implied by VIA_ENABLE

#define HID_LAYER_REPORT 0xCC  // magic byte: outside VIA's command range

layer_state_t layer_state_set_user(layer_state_t state) {
    uint8_t report[RAW_EPSIZE] = {0};
    report[0] = HID_LAYER_REPORT;
    report[1] = get_highest_layer(state);          // top active layer
    report[2] = (state >> 24) & 0xFF;              // full 32-bit mask, MSB..LSB
    report[3] = (state >> 16) & 0xFF;
    report[4] = (state >> 8)  & 0xFF;
    report[5] =  state        & 0xFF;
    raw_hid_send(report, RAW_EPSIZE);
    return state;
}
```

Host side: open the `0xFF60`/`0x61` interface (same one `core.open_raw` uses),
read reports, and act on any whose `data[0] == 0xCC`; ignore the rest (they're
VIA command replies). `listener.py` is a starting point but currently decodes
the keyboard/consumer interfaces — add a third handle on the raw interface and
filter on `0xCC`, keeping the existing single-owner discipline (the
`ControlWorker` already owns the raw handle for VIA traffic, so the push reader
should share that handle rather than open a second one).

### Option B — Pull on demand (`via_command_kb` override)

Add a custom sub-ID under `id_get_keyboard_value`. Host sends `02 80`, reads back the
layer. Stays inside the VIA protocol; no unsolicited traffic.

```c
#include "via.h"

enum kb_keyboard_value_id {
    id_get_active_layer = 0x80,   // custom; above the stock 0x01..0x05 range
};

// QMK's raw_hid_receive() (in quantum/via.c) calls via_command_kb() first;
// returning true short-circuits the default VIA handler.
// VERIFY this signature/semantics against your pinned QMK revision.
bool via_command_kb(uint8_t *data, uint8_t length) {
    if (data[0] == id_get_keyboard_value && data[1] == id_get_active_layer) {
        data[2] = get_highest_layer(layer_state);
        data[3] = (layer_state >> 24) & 0xFF;
        data[4] = (layer_state >> 16) & 0xFF;
        data[5] = (layer_state >> 8)  & 0xFF;
        data[6] =  layer_state        & 0xFF;
        return true;   // handled
    }
    return false;      // fall through to stock VIA
}
```

### Build & flash notes

- Use the upstream bootloader declaration: `keyboards/doio/kb03/keyboard.json`
  ships `"bootloader": "stm32duino"`, and DOIO factory-installs the STM32duino
  bootloader on both genuine STM32F103 and APM32F103CBT6 units (kb16 rev2 with
  confirmed APM32 silicon also uses `stm32duino` upstream). There is no
  `apm32-dfu` variant to choose between — build the in-tree target as-is.
- Flash with `dfu-util` after BOOT0+RESET entry.
- The original AVR rev would instead use Caterina/Atmel-DFU and `qmk flash`.

---

## 5. Concrete next steps for Claude Code

1. **Confirm firmware family (non-invasive):** launch `main.py`; expect VIA proto
   version, 4 layers, keymap, 2 encoders, RGB-matrix lighting on channel `0x03`.
2. **Confirm silicon (if it matters for flashing):** enter bootloader, re-run
   `probe.py`, match the VID:PID against the §2 table.
3. **Probe `switch_matrix_state`:** already in-tree as `core.pressed_cols`; the
   `ControlWorker` polls it at ~33 Hz and the GUI surfaces presses. (Confirms the
   §3 reasoning empirically; the answer does not unblock layer readout either way.)
4. **Read the layer-switch scheme:** `core.read_all` dumps all layers into a
   `Snapshot`; inspect column 3 ("Layers") per layer — `TO(n)` varying by layer =
   hard cycle (this unit's stock keymap); `TT`/`MO` = momentary/tap-toggle.
   Documents how the firmware moves between layers.
5. **Implement readout:** Option A (push) unless there's a reason to prefer pull.
6. **Build & flash** per §4, using the bootloader confirmed in step 2.
7. **Host integration:** extend `listener.py`/`core.py` to consume the layer
   signal (filter `0xCC` reports for Option A, or send `02 80` for Option B), and
   replace `inferred_layer.py`'s host-side reconstruction with the firmware
   signal.

---

## 6. Existing tooling in this repo

| File | Purpose | Notes |
|---|---|---|
| `probe.py` | HID + libusb descriptor dump; QMK/VIA fingerprint verdict | defaults to `0xD010/0x0301`; flags `0xFF60` (VIA) and `0xFF31` (console) |
| `core.py` | VIA raw-HID transport (`0xFF60`) | command IDs, `open_raw`, scalar/color reads and writes, `RGB_MATRIX_CHANNEL = 0x03`; single-owner handle |
| `worker.py` | `ControlWorker` thread owning the VIA handle | polls `switch_matrix_state` at ~33 Hz; UI talks to it via signals only |
| `listener.py` | live HID input reports while pressing keys/turning knobs | decodes keyboard + consumer interfaces; for `0xCC` push add a third raw-HID handle and filter on `data[0]` |
| `inferred_layer.py` | host-side active-layer model | interprets `TO/MO/TG/DF` against physical matrix events; the workaround until firmware can push layer state |
| `ui.py` / `main.py` | PySide6 GUI and thread wiring | not relevant to the layer-state work |

---

## 7. Key references

- VIA protocol enums: `qmk_firmware/quantum/via.h` (`id_get_keyboard_value = 0x02`,
  `id_switch_matrix_state = 0x03`, channel IDs).
- VIA handler / `via_command_kb`: `qmk_firmware/quantum/via.c`.
- Raw HID: https://docs.qmk.fm/features/rawhid
- Push-from-device prior art: https://github.com/zzeneg/qmk-hid-host
  (`layer_state_set_user` + `raw_hid_send`, `0xCC` magic byte).
- Pull-from-host prior art: https://cassaundra.org/blog/layerizer/
- DOIO kb16 readme (bootloader fingerprints, AVR→APM32 revision history):
  `qmk_firmware/keyboards/doio/kb16/readme.md`
- mainline board: `qmk_firmware/keyboards/doio/kb03`
- QMK flashing (STM32duino / apm32-dfu / dfu-util): https://docs.qmk.fm/flashing

---

## 8. Open questions / assumptions to verify

- Exact silicon (ST vs APM32) — resolve via §2 bootloader fingerprint.
- Whether stock firmware implements `switch_matrix_state` (`02 03`) — §5 step 3.
- `via_command_kb` exact signature/short-circuit semantics on the pinned QMK
  revision used for the build — verify before relying on Option B.
- `EFFECTS` ordering in `ui.py` — verified against this firmware by
  `scripts/probe_led_effects.py` (indices 0..31 confirmed; see
  `docs/KB03_led_findings.md`).
