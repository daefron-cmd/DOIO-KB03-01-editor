#pragma once
#include "qmk_stub.h"

uint8_t dynamic_keymap_get_layer_count(void);
uint16_t dynamic_keymap_get_encoder(uint8_t layer, uint8_t encoder, bool clockwise);
void dynamic_keymap_set_encoder(uint8_t layer, uint8_t encoder, bool clockwise, uint16_t code);
