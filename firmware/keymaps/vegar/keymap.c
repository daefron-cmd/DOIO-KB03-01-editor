// Copyright 2025 DOIO
// Copyright 2025 ClownFish (@clownfish-og)
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Outer-ring (encoder index 1) MX-Master scroll emulation. The outer
// ring fires custom keycodes OUTER_SCROLL_CCW/CW. process_record_user
// routes them either to a raw_hid SCROLL_PING when the host is ready,
// or falls back to MS_WHLU/MS_WHLD via tap_code.
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
    // Inner knob (index 0): per-layer bindings as before.
    // Outer ring (index 1): custom keycodes on every layer.
    [_BASE]   = { ENCODER_CCW_CW(MS_WHLU, MS_WHLD),
                  ENCODER_CCW_CW(OUTER_SCROLL_CCW, OUTER_SCROLL_CW) },
    [_MOUSE]  = { ENCODER_CCW_CW(MS_UP,   MS_DOWN),
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
                    tap_code(cw ? MS_WHLD : MS_WHLU);
                }
            }
            return false;
    }
    return true;
}

bool via_command_kb(uint8_t *data, uint8_t length) {
    if (length > 0 && data[0] == 0xA0) {  // HOST_SCROLL_READY
        inertia_host_ready();
        return true;
    }
    return false;
}

void housekeeping_task_user(void) {
    inertia_tick();
}
