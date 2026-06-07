# KB03 LED Findings

## Verified behavior

- Lighting uses the VIA custom RGB-matrix channel `0x03`.
- The app reads and writes:
  - brightness: value id `0x01`
  - effect: value id `0x02`
  - speed: value id `0x03`
  - color: value id `0x04`, sent as hue and saturation together
- Hue and saturation must be written as one `LIGHT_COLOR` command. Sending only
  one channel risks clobbering the other channel.
- Slider updates are live preview only until `CUSTOM_SAVE` is sent.
- `CUSTOM_SAVE` persists the live lighting state to keyboard storage.
- The UI caps brightness at `200` for practical rendering on this unit.

## Current UI contract

- Changing effect, brightness, speed, hue, or saturation immediately previews on
  the device.
- The panel shows `Live preview active; not saved yet` while previewed settings
  differ from the last loaded/saved state.
- `Revert` restores the last loaded/saved lighting state and previews it.
- `Save lighting` sends `CUSTOM_SAVE`; on acknowledgement, the current preview
  becomes the saved baseline.
- The color swatch is a UI preview derived from hue and saturation. It is not a
  readback from the LEDs.

## Effect index table

The dropdown uses QMK RGB Matrix enum names. `scripts/probe_led_effects.py`
verified that this KB03 firmware accepts and reads back indices `0..31`
directly, so these are the firmware-style names for the modes available through
VIA raw HID on this unit.

The GUI can select only effects compiled into the keyboard firmware. New
patterns cannot be added through VIA raw-HID alone; adding a genuinely new
animation means changing and flashing the QMK firmware, then exposing/selecting
that mode from the GUI.

| Index | QMK RGB Matrix name |
|---:|---|
| 0 | `RGB_MATRIX_NONE` |
| 1 | `RGB_MATRIX_SOLID_COLOR` |
| 2 | `RGB_MATRIX_ALPHAS_MODS` |
| 3 | `RGB_MATRIX_GRADIENT_UP_DOWN` |
| 4 | `RGB_MATRIX_GRADIENT_LEFT_RIGHT` |
| 5 | `RGB_MATRIX_BREATHING` |
| 6 | `RGB_MATRIX_BAND_SAT` |
| 7 | `RGB_MATRIX_BAND_VAL` |
| 8 | `RGB_MATRIX_BAND_PINWHEEL_SAT` |
| 9 | `RGB_MATRIX_BAND_PINWHEEL_VAL` |
| 10 | `RGB_MATRIX_BAND_SPIRAL_SAT` |
| 11 | `RGB_MATRIX_BAND_SPIRAL_VAL` |
| 12 | `RGB_MATRIX_CYCLE_ALL` |
| 13 | `RGB_MATRIX_CYCLE_LEFT_RIGHT` |
| 14 | `RGB_MATRIX_CYCLE_UP_DOWN` |
| 15 | `RGB_MATRIX_CYCLE_OUT_IN` |
| 16 | `RGB_MATRIX_CYCLE_OUT_IN_DUAL` |
| 17 | `RGB_MATRIX_RAINBOW_MOVING_CHEVRON` |
| 18 | `RGB_MATRIX_CYCLE_PINWHEEL` |
| 19 | `RGB_MATRIX_CYCLE_SPIRAL` |
| 20 | `RGB_MATRIX_DUAL_BEACON` |
| 21 | `RGB_MATRIX_RAINBOW_BEACON` |
| 22 | `RGB_MATRIX_RAINBOW_PINWHEELS` |
| 23 | `RGB_MATRIX_FLOWER_BLOOMING` |
| 24 | `RGB_MATRIX_RAINDROPS` |
| 25 | `RGB_MATRIX_JELLYBEAN_RAINDROPS` |
| 26 | `RGB_MATRIX_HUE_BREATHING` |
| 27 | `RGB_MATRIX_HUE_PENDULUM` |
| 28 | `RGB_MATRIX_HUE_WAVE` |
| 29 | `RGB_MATRIX_PIXEL_FRACTAL` |
| 30 | `RGB_MATRIX_PIXEL_FLOW` |
| 31 | `RGB_MATRIX_PIXEL_RAIN` |

QMK's RGB Matrix documentation is the reference for these enum names. The raw
probe notes remain in `docs/KB03_led_effect_probe_results.md` as a visual
description of what this specific device showed for each index.

## Remaining hardware pass

1. Close the GUI so there is only one owner of the VIA raw-HID handle.
2. Run `uv run python scripts/probe_led_effects.py --max-index 31` after future
   firmware changes.
3. Record every visible index, repeated index, and no-op index.
4. Update `EFFECTS` in `ui.py` if the compiled firmware effect set changes.
5. Re-run the GUI golden path: preview without save, reconnect to confirm it
   reverts, save, reconnect to confirm it persists.

The probe writes `docs/KB03_led_effect_probe_results.md` by default. Use that
table as the source of truth when renaming the dropdown entries.
