#pragma once
#include <stdbool.h>
#include <stdint.h>

#define PROGMEM
#define MATRIX_ROWS 1
#define MATRIX_COLS 5
#define NUM_ENCODERS 2
#define NUM_DIRECTIONS 2
#define DYNAMIC_KEYMAP_LAYER_COUNT 4
#define SAFE_RANGE 0x7E40
#define TO(layer) (0x5200 | (layer))
#define LAYOUT(layer, k1, k2, k3, knob) {{k1, k2, k3, layer, knob}}
#define ENCODER_CCW_CW(ccw, cw) {ccw, cw}

enum {
    KC_1 = 0x1E, KC_2, KC_3, KC_ENT, MS_BTN1, MS_BTN3, MS_BTN2,
    KC_LCTL, KC_MRWD, KC_MPLY, KC_MFFD, KC_MUTE, RM_VALD, QK_BOOT,
    RM_VALU, RM_TOGG, MS_WHLU, MS_WHLD, MS_LEFT, MS_RGHT, KC_VOLD,
    KC_VOLU, RM_SATD, RM_SATU
};
typedef struct { int8_t v; } report_mouse_t;
typedef struct { struct { bool pressed; } event; } keyrecord_t;
void host_mouse_send(report_mouse_t *report);
void dynamic_keymap_reset(void);
