// Copyright 2025 DOIO
// Copyright 2025 ClownFish (@clownfish-og)
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Outer-ring (encoder index 1) MX-Master scroll emulation. The outer
// ring fires custom keycodes OUTER_SCROLL_CCW/CW. process_record_user
// emits a SCROLL_PING (0xA1) on the raw_hid endpoint when the host daemon
// (main.py + ScrollEngine) has sent a fresh HOST_SCROLL_READY heartbeat.
// Otherwise it falls back to plain vertical QMK mouse-wheel events so the
// outer ring remains usable with the GUI closed or Accessibility denied.
//
// See docs/superpowers/specs/2026-06-08-outer-encoder-mx-scroll-design.md

#include QMK_KEYBOARD_H

#include "inertia.h"

enum my_layers {
    _BASE,
    _MOUSE,
    _MEDIA,
    _LIGHTS
};

enum custom_keycodes {
    OUTER_SCROLL_CCW = SAFE_RANGE,
    OUTER_SCROLL_CW,
};

static void send_wheel_report(bool cw) {
    report_mouse_t report = {0};
    report.v = cw ? -1 : 1;
    host_mouse_send(&report);
}

const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
    [_BASE] = LAYOUT(
        TO(_MOUSE),
        KC_1,    KC_2,    KC_3,
                 KC_ENT
    ),
    [_MOUSE] = LAYOUT(
        TO(_MEDIA),
        MS_BTN1, MS_BTN3, MS_BTN2,
                 KC_LCTL
    ),
    [_MEDIA] = LAYOUT(
        TO(_LIGHTS),
        KC_MRWD, KC_MPLY, KC_MFFD,
                 KC_MUTE
    ),
    [_LIGHTS] = LAYOUT(
        TO(_BASE),
        RM_VALD, QK_BOOT, RM_VALU,
                 RM_TOGG
    )
};

#ifdef ENCODER_MAP_ENABLE
const uint16_t PROGMEM encoder_map[][NUM_ENCODERS][NUM_DIRECTIONS] = {
    // Inner knob (index 0): per-layer bindings, untouched by this project.
    // Outer ring (index 1): always OUTER_SCROLL_CCW/CW — host daemon owns it.
    [_BASE]   = { ENCODER_CCW_CW(MS_WHLU, MS_WHLD),
                  ENCODER_CCW_CW(OUTER_SCROLL_CCW, OUTER_SCROLL_CW) },
    [_MOUSE]  = { ENCODER_CCW_CW(MS_LEFT, MS_RGHT),
                  ENCODER_CCW_CW(OUTER_SCROLL_CCW, OUTER_SCROLL_CW) },
    [_MEDIA]  = { ENCODER_CCW_CW(KC_VOLD, KC_VOLU),
                  ENCODER_CCW_CW(OUTER_SCROLL_CCW, OUTER_SCROLL_CW) },
    [_LIGHTS] = { ENCODER_CCW_CW(RM_SATD, RM_SATU),
                  ENCODER_CCW_CW(OUTER_SCROLL_CCW, OUTER_SCROLL_CW) }
};
#endif

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    switch (keycode) {
        case OUTER_SCROLL_CW:
        case OUTER_SCROLL_CCW:
            if (record->event.pressed) {
                bool cw = (keycode == OUTER_SCROLL_CW);
                if (inertia_is_host_ready()) {
                    inertia_send_scroll_ping(cw);
                } else {
                    send_wheel_report(cw);
                }
            }
            return false;
    }
    return true;
}

bool via_command_kb(uint8_t *data, uint8_t length) {
    if (length > 0 && data[0] == 0xA0) {  // HOST_SCROLL_READY heartbeat
        inertia_host_ready();
        return true;
    }
    return false;
}

void housekeeping_task_user(void) {
    inertia_tick();
}

void keyboard_post_init_user(void) {
#ifdef ENCODER_MAP_ENABLE
    // Force EEPROM dynamic-keymap to match the compile-time keymaps[]
    // and encoder_map[] on every boot. Required because VIA_ENABLE +
    // ENCODER_MAP_ENABLE persists encoder bindings in EEPROM and
    // continues using stale values across reflashes — without this,
    // edits to encoder_map[] in this file never take effect at runtime.
    // Side-effect (consistent with the "outer ring is reserved" policy):
    // any VIA remap is silently reverted on next boot.
    dynamic_keymap_reset();
#endif
}
