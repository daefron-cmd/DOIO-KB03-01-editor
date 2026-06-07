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

The dropdown names below are still best-guess cosmetic labels. The device
accepts effect indices, but the per-index visual names need a dedicated hardware
walk with `scratch_effects_walk.py` or an equivalent single-owner script while
the GUI is closed.

| Index | Current label |
|---:|---|
| 0 | `SOLID_COLOR_OFF/NONE` |
| 1 | `SOLID_COLOR` |
| 2 | `GRADIENT_UP_DOWN` |
| 3 | `GRADIENT_LEFT_RIGHT` |
| 4 | `BREATHING` |
| 5 | `BAND_SAT` |
| 6 | `BAND_VAL` |

## Remaining hardware pass

1. Close the GUI so there is only one owner of the VIA raw-HID handle.
2. Run the effect walk script.
3. Record every visible index, repeated index, and no-op index.
4. Update `EFFECTS` in `ui.py` to the verified names.
5. Re-run the GUI golden path: preview without save, reconnect to confirm it
   reverts, save, reconnect to confirm it persists.
