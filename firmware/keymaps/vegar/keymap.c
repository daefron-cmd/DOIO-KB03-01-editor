// Copyright 2025 DOIO
// Copyright 2025 ClownFish (@clownfish-og)
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Derived from keyboards/doio/kb03/keymaps/default/keymap.c.
// Layout is unchanged; this keymap exists to host tuned mousekey
// wheel constants from config.h. See ./config.h for the deltas.

#include QMK_KEYBOARD_H

enum my_layers {
    _BASE,
    _MOUSE,
    _MEDIA,
    _LIGHTS
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
        // Middle key is QK_BOOT — buried under 3 layer cycles to reach,
        // so it can only be hit deliberately. Cheap alternative to the
        // physical reset button / bootmagic-on-plug.
        RM_VALD, QK_BOOT, RM_VALU,
                 RM_TOGG
    )
};

#ifdef ENCODER_MAP_ENABLE
const uint16_t PROGMEM encoder_map[][NUM_ENCODERS][NUM_DIRECTIONS] = {
    // Both encoders scroll on BASE — this is what the wheel tuning
    // constants in config.h actually affect, so it's the layer to
    // feel the difference on.
    [_BASE]   = { ENCODER_CCW_CW(MS_WHLU, MS_WHLD), ENCODER_CCW_CW(MS_WHLL, MS_WHLR) },
    [_MOUSE]  = { ENCODER_CCW_CW(MS_LEFT, MS_RGHT), ENCODER_CCW_CW(MS_UP,   MS_DOWN) },
    [_MEDIA]  = { ENCODER_CCW_CW(KC_VOLD, KC_VOLU), ENCODER_CCW_CW(KC_MPRV, KC_MNXT) },
    [_LIGHTS] = { ENCODER_CCW_CW(RM_SATD, RM_SATU), ENCODER_CCW_CW(RM_HUED, RM_HUEU) }
};
#endif
