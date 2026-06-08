# firmware

QMK firmware sources, build helper, and flashable dumps for the DOIO KB03-01.

The host-side GUI in this repo can remap keys, encoders, and lighting over VIA
without ever rebuilding firmware. This directory is for the cases VIA can't
reach: things baked at compile time (mousekey wheel constants, encoder maps
when `ENCODER_MAP_ENABLE` is on), recovery to a known-good image, and storing
the binaries we actually flashed onto this unit.

## Layout

| Path | What it is |
|---|---|
| `keymaps/vegar/` | Custom keymap source — `config.h` (mousekey wheel tuning), `keymap.c` (4-layer layout with mouse / media / lights layers), `rules.mk` (encoder map + VIA on). |
| `dumps/candidate_doio_kb03_vegar.{bin,hex}` | Last image built from `keymaps/vegar/` and flashed onto the unit. |
| `dumps/rescue_doio_kb03_default.{bin,hex}` | Stock `doio/kb03:default` build. Flash this to roll back. |
| `dumps/keymap_dump_initial.txt` | Pre-customization output of `scripts/keymap_dump.py` — matrix shape + per-layer keycodes as the unit shipped. Reference snapshot. |
| `build.sh` | Convenience wrapper around `make doio/kb03:<keymap>`. |
| `qmk_firmware/` | Full QMK checkout. Gitignored. See setup below. |

## Setup (one-time)

Install the QMK toolchain via Homebrew, then clone QMK into this directory:

```bash
brew install qmk/qmk/qmk
git clone --depth=1 --recurse-submodules https://github.com/qmk/qmk_firmware.git firmware/qmk_firmware
qmk setup -H firmware/qmk_firmware    # answers "yes" to the prompts
```

## Build

```bash
cd firmware
./build.sh default       # stock keymap
./build.sh vegar         # custom keymap from ./keymaps/vegar/
```

`build.sh` symlinks each subdirectory of `firmware/keymaps/` into
`qmk_firmware/keyboards/doio/kb03/keymaps/` on first run, so edits in
`firmware/keymaps/vegar/` are picked up by the next `make` without a copy step.
The `default` keymap is left alone — it ships with QMK.

Output binaries land in `qmk_firmware/.build/` and the top-level
`qmk_firmware/`. Copy the keepers into `dumps/` with a descriptive name before
overwriting them on the next build.

## Flash

The KB03-01 enters DFU via the `QK_BOOT` keycode (the `vegar` keymap puts it on
the middle key of layer 3 — three layer-cycles deep so it can only be hit
deliberately) or by shorting the on-PCB reset pads.

```bash
# With the device in DFU:
qmk flash -kb doio/kb03 -km vegar
# or, equivalently, point dfu-util at one of the .bin files in dumps/.
```

## Caveats

- Only flash images built for the current STM32/APM32 KB03-01 revision
  (`0xD010/0x0301`). The 2023 ATmega32U4 revision (`0xFEED/0x6060`) needs a
  different QMK target and is not covered here.
- VIA raw-HID is single-owner — close the GUI before running `qmk flash` or any
  device probe. See the top-level README for the full caveat.
- `ENCODER_MAP_ENABLE = yes` (in `keymaps/vegar/rules.mk`) means encoder
  bindings are compile-time, not VIA-runtime-configurable. That is the price of
  being able to override `MOUSEKEY_WHEEL_*` in `config.h`. The GUI can still
  display the encoder bindings, but the "set encoder" path will be a no-op for
  this firmware.
