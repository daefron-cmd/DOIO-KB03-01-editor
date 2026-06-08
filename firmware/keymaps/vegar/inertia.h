// SPDX-License-Identifier: GPL-2.0-or-later
//
// inertia.h — host-takeover state machine and SCROLL_PING transport
// for the MX-Master-style outer-encoder scroll feature.
//
// See docs/superpowers/specs/2026-06-08-outer-encoder-mx-scroll-design.md
// for the full protocol and behaviour contract.

#pragma once

#include <stdbool.h>
#include <stdint.h>

// Called from via_command_kb() when a HOST_SCROLL_READY (0xA0) heartbeat
// arrives. Refreshes the watchdog timestamp.
void inertia_host_ready(void);

// Called from housekeeping_task_user(); drops host_scroll_ready after
// 500 ms without a heartbeat.
void inertia_tick(void);

// True iff a fresh heartbeat has arrived within the last ~500 ms.
bool inertia_is_host_ready(void);

// Emit a SCROLL_PING (0xA1) frame upstream to the host.
// `cw = true` -> direction = 1 = down/CW.
void inertia_send_scroll_ping(bool cw);
