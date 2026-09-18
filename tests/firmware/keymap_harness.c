// Execute the actual keymap's boot hook against simulated persistent mappings.
#include <stdio.h>
#include <string.h>
#include "keymap.c"

static uint16_t stored_keys[4][1][5];
static uint16_t stored_encoders[4][2][2];
static int writes;
static int resets;

void host_mouse_send(report_mouse_t *report) { (void)report; }
void inertia_host_ready(void) {}
void inertia_tick(void) {}
bool inertia_is_host_ready(void) { return false; }
void inertia_send_scroll_ping(bool cw) { (void)cw; }
uint8_t dynamic_keymap_get_layer_count(void) { return 4; }
uint16_t dynamic_keymap_get_encoder(uint8_t layer, uint8_t encoder, bool cw) {
    return stored_encoders[layer][encoder][cw];
}
void dynamic_keymap_set_encoder(uint8_t layer, uint8_t encoder, bool cw, uint16_t code) {
    stored_encoders[layer][encoder][cw] = code;
    writes++;
}
void dynamic_keymap_reset(void) {
    memcpy(stored_keys, keymaps, sizeof(stored_keys));
    memcpy(stored_encoders, encoder_map, sizeof(stored_encoders));
    resets++;
}

#define CHECK(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "%s\n", message); return 1; } \
} while (0)

int main(void) {
    for (int layer = 0; layer < 4; layer++) {
        for (int col = 0; col < 5; col++) {
            stored_keys[layer][0][col] = 0x100 + layer * 5 + col;
        }
        stored_encoders[layer][0][0] = 0x200 + layer;
        stored_encoders[layer][0][1] = 0x300 + layer;
        stored_encoders[layer][1][0] = 0;
        stored_encoders[layer][1][1] = 0;
    }
    for (int boot = 0; boot < 2; boot++) {
        keyboard_post_init_user();
        CHECK(resets == 0, "boot erased the full dynamic keymap");
        for (int layer = 0; layer < 4; layer++) {
            for (int col = 0; col < 5; col++) {
                CHECK(stored_keys[layer][0][col] == 0x100 + layer * 5 + col,
                      "user key remap lost");
            }
            CHECK(stored_encoders[layer][0][0] == 0x200 + layer, "inner CCW lost");
            CHECK(stored_encoders[layer][0][1] == 0x300 + layer, "inner CW lost");
            CHECK(stored_encoders[layer][1][0] == OUTER_SCROLL_CCW, "outer CCW not reserved");
            CHECK(stored_encoders[layer][1][1] == OUTER_SCROLL_CW, "outer CW not reserved");
        }
        CHECK(writes == 8, "unchanged outer mappings must not be rewritten on reboot");
    }
    return 0;
}
