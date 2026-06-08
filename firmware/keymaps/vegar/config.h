// SPDX-License-Identifier: GPL-2.0-or-later
//
// Mousekey wheel tuning for the DOIO KB03-01.
//
// Background: an encoder detent in QMK fires a synthetic press/release
// of the mapped keycode. When the keycode is a mousekey wheel
// (MS_WHLU / MS_WHLD / MS_WHLL / MS_WHLR), the mousekey state machine
// uses these four constants to decide how many wheel reports to send
// and how fast to ramp up under sustained scrolling.
//
// All four are quantum/mousekey.c defaults that we override here.
// Stock QMK defaults shown in comments for reference.

#pragma once

// Time (ms) between a wheel-key press and the FIRST wheel report.
// On an encoder we want the first tick to fire immediately, so 0.
// Stock default: 10.
#define MOUSEKEY_WHEEL_DELAY 0

// Time (ms) between successive wheel reports while the key is held.
// Encoders only hold the synthesised press for a short window
// (MOUSEKEY_INTERVAL ms by default), so this mostly controls the
// minimum gap between distinct detents at high turn rates.
// Stock default: 80.
#define MOUSEKEY_WHEEL_INTERVAL 50

// Maximum acceleration multiplier. Each wheel report scales linearly
// from 1 up to this value over MOUSEKEY_WHEEL_TIME_TO_MAX. Higher
// = faster fast-scrolls under sustained turn.
// Stock default: 8.
#define MOUSEKEY_WHEEL_MAX_SPEED 8

// Time, in units of 10 ms, to reach MAX_SPEED. 40 = 400 ms.
// Lower = ramps up faster.
// Stock default: 40.
#define MOUSEKEY_WHEEL_TIME_TO_MAX 40

// QMK encoder maps travel through the normal keycode pipeline as a
// key-down then key-up. The default delay between that pair caps
// detent dispatch rate during fast spins, even though our handler
// short-circuits with raw_hid_send. Set it to 0 so fast MagSpeed
// spins don't get throttled.
#define ENCODER_MAP_KEY_DELAY 0

// Time (ms) between register_code and unregister_code in tap_code, and
// between encoder_map key-down and key-up for non-custom keycodes.
// Default 0 collides on the host's HID poll window: a wheel report with
// v=±1 and a follow-up report with v=0 land in the same poll, netting
// to a zero-delta scroll event in macOS. 10 ms is enough to keep the
// two reports in distinct poll windows so the wheel impulse survives.
// Affects every tap_code() call AND every encoder_map wheel binding
// (MS_WHLU/D on _BASE inner, etc.), not just our outer-ring handler.
#define TAP_CODE_DELAY 10
