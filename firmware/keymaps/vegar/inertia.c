// SPDX-License-Identifier: GPL-2.0-or-later
//
// inertia.c — see inertia.h.

#include "inertia.h"

#include "raw_hid.h"
#include "timer.h"
#include "quantum.h"

#define HOST_READY_WINDOW_MS 500
#define RAW_HID_REPORT_SIZE 32

static bool     s_host_ready          = false;
static uint32_t s_last_host_ready_ms  = 0;

void inertia_host_ready(void) {
    s_last_host_ready_ms = timer_read32();
    s_host_ready = true;
}

void inertia_tick(void) {
    if (s_host_ready
        && timer_elapsed32(s_last_host_ready_ms) > HOST_READY_WINDOW_MS) {
        s_host_ready = false;
    }
}

bool inertia_is_host_ready(void) {
    return s_host_ready;
}

void inertia_send_scroll_ping(bool cw) {
    uint8_t f[RAW_HID_REPORT_SIZE] = {0};
    uint32_t t = timer_read32();

    f[0] = 0xA1;            // SCROLL_PING
    f[1] = 0x01;            // protocol version
    f[2] = cw ? 1 : 0;
    f[3] = 0x00;            // flags reserved
    f[4] = (uint8_t)(t      );
    f[5] = (uint8_t)(t >>  8);
    f[6] = (uint8_t)(t >> 16);
    f[7] = (uint8_t)(t >> 24);

    raw_hid_send(f, RAW_HID_REPORT_SIZE);
}
