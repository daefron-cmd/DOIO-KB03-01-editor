# Outer-encoder MX-Master scroll emulation — design

Status: revised after review (`synthesized_review_checklist.md`)
Date: 2026-06-08

## Goal

Turn the DOIO KB03-01's **outer ring** (encoder index 1) into a vertical
scroll wheel that emulates a Logitech MX Master 3S as closely as a detented
encoder + the macOS event system allow: coast after release, speed-adaptive
gain ("MagSpeed"), direction-flip kill, and pixel-precise output with native
momentum phases so Safari/Chrome/Finder honour it like a trackpad fling.

The inner knob (encoder index 0) keeps its existing per-layer bindings and
is out of scope.

## Behaviour contract

1. **Detent → impulse.** Each detent of the outer ring adds an impulse to a
   signed velocity scalar (units: pixels/sec). Direction sets the sign.
2. **Damped impulse model.** Velocity decays exponentially with time
   constant `τ` in both ACTIVE (user is turning) and MOMENTUM (released)
   phases. This is the chosen model — *not* rate-estimation — so steady
   spinning produces a stable steady-state velocity rather than ramping
   indefinitely with time.
3. **MagSpeed gain.** Output magnitude is `velocity × gain(|velocity|)`,
   where `gain()` is piecewise linear:
   - `|v| ≤ slow_threshold` → gain = 1.0 (precision)
   - `|v| ≥ fast_threshold` → gain = `max_gain` (free-spin throughput)
   - between → linear interpolation
   - Gain is applied in **both ACTIVE and MOMENTUM** so output is
     continuous across release (no audible/visible jump). The cost is
     bounded by `v_max × max_gain × τ`; defaults are chosen so the max
     fling is ~2–3 screens.
4. **Precision is real.** A single isolated detent at rest must produce a
   small predictable nudge (target ≤ 15 px), not a fling. Verified by unit
   test.
5. **Coast.** When no detent arrives for `active_window_ms` (default 80 ms)
   **and** velocity at that moment exceeds `coast_threshold`, the engine
   transitions to MOMENTUM. Velocity continues to decay; once `|v|` drops
   below `cutoff_v`, MOMENTUM ends. If `v` at the transition is below
   `coast_threshold`, we go directly ACTIVE → IDLE (post `ScrollPhase.Ended`
   only; no momentum phase events at all).
6. **Direction-flip kill.** A detent whose sign opposes current velocity
   zeroes velocity (and accumulator) instantly before applying its own
   impulse. If the flip happens during MOMENTUM, exactly one
   `MomentumPhase.Ended` is posted, the engine returns to IDLE, and the
   new detent then opens a fresh ACTIVE gesture with `ScrollPhase.Began`.
7. **Pixel-precise output (host-online mode).** Output is posted as
   `CGEventCreateScrollWheelEvent2` with `kCGScrollEventUnitPixel`,
   `IsContinuous=1`, and explicit `ScrollPhase` and `MomentumPhase` flags
   following the trackpad sequence
   `Began → Changed → Ended → MomentumBegan → MomentumChanged → MomentumEnded`.
   App behaviour with this event shape will be **empirically verified
   per-app**; the spec does not claim Safari/Chrome/etc. respond
   identically.
8. **Standalone fallback (host-offline mode).** When the host app isn't
   running, or it's running but cannot safely take over (no Accessibility,
   no Quartz, no scroll engine), the outer ring emits plain
   `MS_WHLU`/`MS_WHLD` HID reports exactly as today.
9. **Inner knob untouched.** All existing per-layer bindings on encoder 0
   remain.
10. **Cross-layer.** Outer-ring behaviour is identical on `_BASE`, `_MOUSE`,
    `_MEDIA`, and `_LIGHTS`. Previous outer-ring bindings on the
    non-`_BASE` layers (`MS_LEFT/RGHT`, `KC_MPRV/MNXT`, `RM_HUED/U`) are
    removed.
11. **Direction calibration is required.** The host config exposes an
    `invert` flag (default `false`). CW vs CCW physical direction → page
    scroll direction is **not** assumed; the user verifies after first
    flash, and the convention "CW scrolls page down" is documented but
    only authoritative once tested.

## Architecture

### Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│ Firmware  (firmware/keymaps/vegar/)                                 │
│                                                                     │
│  enum custom_keycodes { OUTER_SCROLL_CCW=SAFE_RANGE, OUTER_SCROLL_CW};│
│                                                                     │
│  encoder_map[*][1]  = ENCODER_CCW_CW(OUTER_SCROLL_CCW, OUTER_SCROLL_CW)│
│  encoder_map[*][0]  = unchanged                                     │
│                                                                     │
│  process_record_user(kc, record):                                   │
│   if kc in {OUTER_SCROLL_*} and record->event.pressed:              │
│     if inertia_is_host_ready(): inertia_send_scroll_ping(cw)        │
│     else:                       tap_code(cw ? MS_WHLD : MS_WHLU)    │
│     return false                                                    │
│                                                                     │
│  via_command_kb(data, length):                                      │
│   if data[0] == 0xA0:           inertia_host_ready(); return true   │
│   return false                                                      │
│                                                                     │
│  inertia.c/h:                                                       │
│   - host_scroll_ready watchdog (last_host_ready_ms; 500 ms window)  │
│   - housekeeping_task_user() drops readiness on timeout             │
│   - inertia_send_scroll_ping(cw): raw_hid_send(frame, RAW_EPSIZE)   │
└─────────────────────────────────────────────────────────────────────┘
                            ▲                    │
                            │ HOST_SCROLL_READY  │ SCROLL_PING 0xA1
                            │ via via_command_kb │ via raw_hid_send
                            │ every 200 ms       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Host  (Python / PySide6 / pyobjc)                                   │
│                                                                     │
│  hid_io.py NEW     HidIoWorker — sole owner of 0xFF60.              │
│                    Owns read loop, write queue, futures, demux,     │
│                    close/reopen with backoff. Emits scroll_tick     │
│                    on 0xA1. send_request / send_untracked API.      │
│                                                                     │
│  core.py           Frame builders/parsers only. No I/O. cmd()       │
│                    becomes a thin convenience that calls            │
│                    HidIoWorker.send_request().                      │
│                                                                     │
│  worker.py         ControlWorker uses HidIoWorker for transport.    │
│                    Owns the heartbeat-gating logic: only enables    │
│                    heartbeat when all four readiness conditions     │
│                    are true (see "HOST_SCROLL_READY semantics").    │
│                                                                     │
│  scroll.py NEW     ScrollEngine QObject on its own QThread,         │
│                    driven by a QTimer at 120 Hz. Subscribes to      │
│                    HidIoWorker.scroll_tick. Inertia state           │
│                    machine; posts CGEvent.                          │
│                                                                     │
│  ui.py             "Scroll feel" panel (sliders + invert toggle +   │
│                    Accessibility-permission banner).                │
│                                                                     │
│  main.py           Wires HidIoWorker, ControlWorker, Listener,      │
│                    ScrollEngine threads. Calls                      │
│                    AXIsProcessTrustedWithOptions on startup.        │
└─────────────────────────────────────────────────────────────────────┘
                            ▲
                            │  CGEventPost (HID tap, pixel units,
                            │   ScrollPhase + MomentumPhase set)
                            ▼
                       macOS event system → apps
```

### Why this shape

- **Custom keycodes via `encoder_map` + `process_record_user`** is the
  documented QMK path under `ENCODER_MAP_ENABLE=yes`. The earlier draft
  used `encoder_update_user`, which is bypassed by the encoder-map
  dispatch and would silently do nothing.
- **VIA stays the top-level raw-HID dispatcher.** We do *not* define a
  keymap-level `raw_hid_receive()`; that would override VIA's handler and
  break the existing GUI. Heartbeat goes through `via_command_kb()`,
  which is VIA's official kb-private command hook.
- **One `HidIoWorker` owns the `0xFF60` handle.** Reads, writes, futures,
  reopen/backoff — all in one place. ControlWorker and ScrollEngine talk
  to it; neither touches the handle. This collapses the previous draft's
  contradictory "reader thread + worker writes directly" model.
- **`send_untracked` for heartbeats**, separate from `send_request` for
  command/reply traffic. Heartbeat noise can't collide with VIA replies.

### Threads, final state

| Thread | Owns | Notes |
|---|---|---|
| UI | `MainWindow`, painters, slots | Unchanged |
| HID I/O | `HidIoWorker` — `0xFF60` handle, read loop, write queue, future table | NEW; sole HID owner |
| Control | `ControlWorker` | Submits requests via HidIoWorker; drives heartbeat |
| Listener | Keyboard + consumer HID handles (separate interfaces) | Unchanged |
| Scroll | `ScrollEngine` with QTimer | NEW; 120 Hz tick, posts CGEvent |

### File-level change list

| File | Change | Approx size |
|---|---|---|
| `firmware/keymaps/vegar/inertia.{c,h}` (new) | `host_scroll_ready` watchdog, `via_command_kb`, scroll-ping send helper | ~80 lines |
| `firmware/keymaps/vegar/keymap.c` | custom keycodes `OUTER_SCROLL_CCW/CW`, encoder_map entries on all 4 layers, `process_record_user` handler | ~30 lines |
| `firmware/keymaps/vegar/rules.mk` | `SRC += inertia.c` (note: `SRC`, not `SRCS`) | 1 line |
| `firmware/keymaps/vegar/config.h` | unchanged. Existing `MOUSEKEY_WHEEL_*` constants still govern the standalone fallback (through `tap_code` → QMK mousekey). Add header comment pointing at this design doc. | trivial |
| `pyproject.toml` | add `pyobjc-framework-Quartz` and `pyobjc-framework-ApplicationServices` (NOT transitively from PySide6) | 2 lines |
| `hid_io.py` (new) | `HidIoWorker` — single owner of `0xFF60`, read loop, write queue, demux, futures, reopen/backoff | ~250 lines |
| `core.py` | refactor to pure frame builders/parsers (`build_get_key`, `parse_get_key`, …). `cmd()` becomes a convenience wrapper around `HidIoWorker.send_request`. | ~80 lines net |
| `worker.py` | `ControlWorker` uses `HidIoWorker`; adds heartbeat gating logic with the four readiness conditions | ~60 lines changed |
| `scroll.py` (new) | `ScrollEngine` — inertia state machine, QTimer tick, CGEvent posting | ~250 lines |
| `ui.py` | "Scroll feel" panel: sliders, invert toggle, Accessibility-permission banner | ~100 lines |
| `main.py` | thread wiring, Accessibility prompt on startup, dependency-import gating | ~20 lines |
| `scripts/scroll_probe.py` (new) | local CFMachPort event-tap probe that logs `NSEvent.phase`, `momentumPhase`, `hasPreciseScrollingDeltas`, `scrollingDeltaX/Y` so we can empirically verify the event shape per-app | ~100 lines |
| `tests/test_scroll_model.py` (new) | inertia model unit tests (virtual clock; no hardware, no Quartz) | ~250 lines |
| `tests/test_hid_io.py` (new) | demux + future logic against a fake hid handle; FIFO per command-ID; `id_unhandled=0xFF` handling | ~150 lines |

## Private protocol

One table, authoritative for both firmware and host.

| ID | Name | Direction | Length | Purpose |
|---|---|---|---|---|
| `0xA0` | `HOST_SCROLL_READY` | host → device, via `via_command_kb()` | 32 B | Fire-and-forget heartbeat. Refreshes `last_host_ready_ms`. |
| `0xA1` | `SCROLL_PING` | device → host, via `raw_hid_send()` | `RAW_EPSIZE` | One per outer-ring detent in host-online mode. |

### `0xA1` SCROLL_PING frame

```
byte 0     : 0xA1                              (command ID)
byte 1     : 0x01                              (protocol version)
byte 2     : direction — 0 = up/CCW, 1 = down/CW
byte 3     : flags (reserved, must be 0)
bytes 4..7 : device timestamp ms, little-endian (timer_read32())
bytes 8..31: reserved, zero
```

### `0xA0` HOST_SCROLL_READY frame

```
byte 0     : 0xA0                              (command ID)
byte 1     : 0x01                              (protocol version)
bytes 2..31: reserved, zero
```

The host-side write to HIDAPI prepends the standard report-ID byte
`0x00`, producing a 33-byte write; the device sees the 32-byte payload.
This matches the existing `core.cmd()` write shape and is reaffirmed
here because it's protocol-level.

The firmware sends exactly `RAW_EPSIZE` bytes (zero-padded) — never a
short frame.

## HOST_SCROLL_READY semantics

Heartbeats are sent **only when all four conditions hold**. Drop any one
and heartbeats stop; firmware watchdog times out within 500 ms and the
encoder reverts to fallback.

1. `HidIoWorker` has the `0xFF60` handle open.
2. `pyobjc-framework-Quartz` and `pyobjc-framework-ApplicationServices`
   imports succeeded.
3. `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})`
   has returned `True` since startup (host re-checks after any
   permission-grant action).
4. `ScrollEngine`'s `QTimer` is started and its thread's event loop is
   running.

Implementation: `ControlWorker.update_readiness()` is called from each
of these state changes (handle opened/closed, trust gained, scroll
engine started/stopped). When the result transitions to `True`, the
heartbeat `QTimer` (200 ms) starts; when it transitions to `False`, it
stops. No heartbeat is sent "speculatively".

## Inertia model

### Phases

```
IDLE          : no detents recent, no momentum. v = 0, accumulator = 0.
ACTIVE        : user is currently turning. Posting ScrollPhase.Changed.
MOMENTUM      : user released; coasting. Posting MomentumPhase.Changed.
```

### State

```python
@dataclass
class ScrollState:
    velocity: float = 0.0        # signed, pixels/sec
    accumulator: float = 0.0     # sub-pixel carry
    last_tick_ms: int = 0        # monotonic clock, ms; last detent
    last_emit_ms: int = 0        # monotonic clock, ms; last tick-loop frame
    phase: Phase = Phase.IDLE
```

### Helpers — phase entries always reset timing baselines

```python
def enter_active(self, now_ms: int) -> None:
    self.phase = Phase.ACTIVE
    self.last_tick_ms = now_ms
    self.last_emit_ms = now_ms
    self.accumulator = 0.0
    post_scroll(0, ScrollPhase.BEGAN, MomentumPhase.NONE)

def enter_momentum(self, now_ms: int) -> None:
    self.phase = Phase.MOMENTUM
    self.last_tick_ms = now_ms
    self.last_emit_ms = now_ms
    post_scroll(0, ScrollPhase.ENDED, MomentumPhase.NONE)
    post_scroll(0, ScrollPhase.NONE, MomentumPhase.BEGAN)

def enter_idle(self, post_ended: ScrollPhase | None = None) -> None:
    if post_ended is ScrollPhase.ENDED:
        post_scroll(0, ScrollPhase.ENDED, MomentumPhase.NONE)
    self.velocity = 0.0
    self.accumulator = 0.0
    self.phase = Phase.IDLE

def enter_idle_from_momentum(self) -> None:
    post_scroll(0, ScrollPhase.NONE, MomentumPhase.ENDED)
    self.velocity = 0.0
    self.accumulator = 0.0
    self.phase = Phase.IDLE
```

### Tick loop (120 Hz, QTimer-driven)

```python
def tick(self) -> None:
    if self.phase == Phase.IDLE:
        return

    now = monotonic_ms()
    dt_s = max(0.0, min((now - self.last_emit_ms) / 1000.0, 0.050))
    tau_s = self.tau_ms / 1000.0

    # 1. ACTIVE → MOMENTUM or IDLE
    if self.phase == Phase.ACTIVE and (now - self.last_tick_ms) > self.active_window_ms:
        if abs(self.velocity) > self.coast_threshold:
            self.enter_momentum(now)
        else:
            self.enter_idle(post_ended=ScrollPhase.ENDED)
            return

    # 2. Damped velocity (applied in BOTH active and momentum)
    self.velocity *= math.exp(-dt_s / tau_s)

    # 3. End of momentum
    if self.phase == Phase.MOMENTUM and abs(self.velocity) < self.cutoff_v:
        self.enter_idle_from_momentum()
        return

    # 4. Emit
    gain = self.magspeed_gain(abs(self.velocity))
    pixels_f = self.velocity * gain * dt_s + self.accumulator
    pixels = int(pixels_f)                  # truncate toward zero
    self.accumulator = pixels_f - pixels
    if pixels != 0:
        if self.phase == Phase.MOMENTUM:
            post_scroll(pixels, ScrollPhase.NONE,    MomentumPhase.CHANGED)
        else:
            post_scroll(pixels, ScrollPhase.CHANGED, MomentumPhase.NONE)
    self.last_emit_ms = now
```

Notes:
- `dt_s` is clamped to 50 ms to prevent huge first-frame deltas after
  wake-from-sleep or event-loop stalls.
- Damping (`v *= exp(-dt/τ)`) is applied in *both* ACTIVE and MOMENTUM
  so a steady spin reaches a stable steady-state velocity rather than
  ramping indefinitely with each tick.
- The `coast_threshold == cutoff_v` skip branch from the prior draft is
  gone. `coast_threshold` is now its own slider with `coast_threshold ≥
  cutoff_v` enforced.

**On the `active_window_ms` cliff.** Output *velocity* is continuous
across the ACTIVE → MOMENTUM transition: same `v`, same `gain(v)`, same
emitted pixels. What changes is only the macOS phase flag on the
CGEvent. The visible cliff therefore comes from how apps interpret
phase — Safari/Chrome may add their own momentum animation on
`MomentumPhase.Began`, producing a noticeable jump if 79 ms vs 81 ms
puts a detent on opposite sides of the boundary. Two mitigations are
available without a model rewrite: (1) widen `active_window_ms` so
late-but-rhythmic detents stay in ACTIVE, or (2) on a detent arriving
shortly after MOMENTUM begins, retroactively cancel the momentum
events and treat the gesture as never having released. We pick
mitigation (1) by default (slider goes up to 250 ms) and leave (2) as
a future iteration if testing shows app jumpiness on the boundary.

### Detent arrival (queued cross-thread from `HidIoWorker.scroll_tick`)

```python
def on_tick(self, direction: int, device_t_ms: int) -> None:
    now = monotonic_ms()
    impulse = self.impulse_per_detent * direction
    if self.invert:
        impulse = -impulse

    # Direction-flip kill
    if self.velocity != 0 and sign(self.velocity) != sign(direction):
        if self.phase == Phase.MOMENTUM:
            self.enter_idle_from_momentum()   # posts ONE MomentumPhase.ENDED
        else:
            self.velocity = 0.0
            self.accumulator = 0.0

    if self.phase in (Phase.IDLE,):
        self.enter_active(now)
    elif self.phase == Phase.MOMENTUM:
        # Same-direction detent during momentum: re-open ACTIVE gesture.
        post_scroll(0, ScrollPhase.NONE, MomentumPhase.ENDED)
        self.enter_active(now)

    self.velocity = clamp(self.velocity + impulse, -self.v_max, self.v_max)
    self.last_tick_ms = now
```

Direction-flip during MOMENTUM posts exactly one `MomentumPhase.ENDED`
(inside `enter_idle_from_momentum`), then immediately enters ACTIVE with
a fresh `ScrollPhase.BEGAN`. Same-direction detent during MOMENTUM also
ends momentum (one `MomentumPhase.ENDED`) and restarts ACTIVE, so the
user sees their continued turning as a new push rather than amplified
coast.

### MagSpeed gain curve

```python
def magspeed_gain(self, abs_v: float) -> float:
    if abs_v <= self.slow_threshold: return 1.0
    if abs_v >= self.fast_threshold: return self.max_gain
    t = (abs_v - self.slow_threshold) / (self.fast_threshold - self.slow_threshold)
    return 1.0 + t * (self.max_gain - 1.0)
```

### Defaults (all GUI-tunable except `v_max` hard clamp)

| Param | Default | Slider range | Reasoning |
|---|---|---|---|
| `impulse_per_detent` | 100 px/s | 20–500 | One isolated detent at IDLE: v=100 → over 80 ms active window with damping → output ≈ 7 px. Precision passes. |
| `tau_ms` | 400 ms | 50–2000 | Used in both phases. Decay from 1000 px/s to cutoff 40 ≈ 1.3 s of perceptible coast. |
| `slow_threshold` | 200 px/s | 50–1000 | Below this, gain = 1.0 — single isolated detents are unmodified. |
| `fast_threshold` | 1500 px/s | 500–5000 | Above this, gain = max_gain — sustained fast spin gives free-spin throughput. |
| `max_gain` | 6.0× | 1.0–12.0 | At `v_max × max_gain × τ ≈ 6000 px ≈ 6 screens` worst-case fling. |
| `active_window_ms` | 80 ms | 30–250 | Time without a detent before ACTIVE → MOMENTUM transition. |
| `coast_threshold` | 300 px/s | 50–2000 | Below this at the ACTIVE → MOMENTUM check, skip momentum (ACTIVE → IDLE). Must be `≥ cutoff_v`. |
| `cutoff_v` | 40 px/s | 5–200 | Below this during MOMENTUM, momentum ends. |
| `invert` | `false` | toggle | CW vs CCW direction calibration. |
| `v_max` | 2500 px/s | hard clamp | Caps worst-case fling. Not user-tunable. |

Persisted to `~/.config/doio-kb03/scroll.json` (or
`$XDG_CONFIG_HOME/...`). Malformed file → defaults applied, file
ignored. Out-of-range values are clamped at load. The variable name
suffix `_ms` is preserved through the codebase to keep units visible.

### Worked sanity examples

```
Single isolated detent (precision):
  v0 = 100 px/s, gain at 100 = 1.0
  Active phase, 80 ms with damping τ=400 ms:
    integral ≈ v0 * τ * (1 - exp(-T/τ))
            = 100 * 0.4 * 0.181  ≈ 7.2 px
  v at transition = 100 * exp(-0.08/0.4) ≈ 82 px/s
  82 < coast_threshold (300) → ACTIVE → IDLE, no momentum.
  Net output: ~7 px. PRECISE.

Steady slow (1 detent every 200 ms):
  Steady-state v ≈ I * exp(-dt/τ) / (1 - exp(-dt/τ))
                = 100 * 0.607 / 0.393 ≈ 155 px/s
  Below slow_threshold → gain 1.0.
  Output ≈ 155 px/s × 0.2 s/detent ≈ 31 px/detent.

Steady fast (1 detent every 30 ms):
  v ≈ 100 * exp(-0.075) / (1 - exp(-0.075)) ≈ 1290 px/s
  gain ≈ 1 + (1290-200)/1300 × 5 ≈ 5.2
  Output ≈ 1290 × 5.2 × 0.03 ≈ 200 px/detent. Free-spin feel.

Release after fast burst at v ≈ 1290:
  Approx fling ≈ v0 × gain(v0) × τ ≈ 1290 × 5.2 × 0.4 ≈ 2680 px.
  ≈ 2–3 screens. Bounded by tuning.

Worst-case fling (v_max × max_gain × τ):
  2500 × 6.0 × 0.4 = 6000 px ≈ 6 screens. Hard ceiling.
```

A unit test on the model asserts: a single isolated detent emits ≤ 15 px
total. This is the precision guarantee.

## macOS event posting

### Permission gating

On startup, before opening the HID handle, `main.py` calls:

```python
trusted = AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
```

This prompts the user once if not already trusted. Until it returns
trusted, `ControlWorker.update_readiness()` reports false on the
trust gate and no heartbeat is sent — the encoder operates in fallback.
The GUI shows a banner above the "Scroll feel" panel; clicking it opens
System Settings → Privacy & Security → Accessibility. After the user
grants permission, the GUI re-checks trust (on focus or via a "Re-check"
button) and re-evaluates readiness.

### CGEvent post

```python
def post_scroll(pixels: int, scroll_phase: int, momentum_phase: int):
    ev = Quartz.CGEventCreateScrollWheelEvent2(
        None, Quartz.kCGScrollEventUnitPixel,
        1,                  # wheelCount
        pixels, 0, 0)       # axis1 (vert), axis2, axis3
    Quartz.CGEventSetIntegerValueField(
        ev, Quartz.kCGScrollWheelEventScrollPhase,   scroll_phase)
    Quartz.CGEventSetIntegerValueField(
        ev, Quartz.kCGScrollWheelEventMomentumPhase, momentum_phase)
    Quartz.CGEventSetIntegerValueField(
        ev, Quartz.kCGScrollWheelEventIsContinuous, 1)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
```

### Event-shape verification

App-behaviour claims are **targets to verify**, not assumptions.
`scripts/scroll_probe.py` creates an event tap on
`kCGSessionEventTap`/`kCGHeadInsertEventTap` and logs every scroll
event's `NSEvent.phase`, `momentumPhase`, `hasPreciseScrollingDeltas`,
and `scrollingDeltaX/Y` so we can confirm the event shape matches what
a real trackpad emits before declaring a target app "works". This probe
is part of the spec; running it across the app matrix is part of
acceptance.

## Error handling

| Failure | Detected by | Response |
|---|---|---|
| Accessibility denied | `AXIsProcessTrustedWithOptions` returns false | Readiness gate fails; no heartbeats sent; firmware fallback stays active. Banner in GUI. |
| Quartz/ApplicationServices import fails (missing pyobjc) | ImportError at startup | Readiness gate fails; banner offers "Install pyobjc-framework-Quartz". |
| Firmware doesn't recognise `0xA0` (not yet flashed) | No `0xA1` frames ever arrive; via_command_kb on device falls through to default `id_unhandled=0xFF` reply | Host treats `0xFF` reply as a non-completion (not a future-fulfilment). ScrollEngine silently idle; firmware stays in pre-change behaviour. |
| Host crashes mid-coast | Firmware watchdog (500 ms) drops `host_scroll_ready` | Synthetic momentum stops on the host (process is gone). Within ~500 ms, new physical detents on the outer ring produce plain firmware wheel events. (Existing momentum does *not* keep going — the engine was the host.) |
| `HidIoWorker` can't open `0xFF60` | `open_raw()` returns None at startup; or `OSError` during read loop | UI shows existing "device not connected" state. Backoff: try reopen at 1 s, 2 s, 5 s. |
| `hid_read` timeout / short read | Read loop catches | Drop and continue; on 5 consecutive errors, close + reopen with backoff. |
| `hid_read` returns frame with command ID matching a pending future, but in wrong order | Future table uses FIFO queue **per command-ID** | Reply is delivered to the oldest waiting future for that ID. If no pending future for the ID and it's not `0xA1`/`0xA0`, log and drop. |
| Reply with `0xFF` (`id_unhandled`) | Always treated as an explicit error | Fulfils the oldest pending future for the *original* request command ID (HidIoWorker tracks (request_id → outgoing_command_id) when the host sends), but with an `IdUnhandledError`. Never silently completes an unrelated request. |
| Direction flip mid-momentum | `on_tick` detects sign mismatch | Exactly one `MomentumPhase.ENDED` posted via `enter_idle_from_momentum`; new gesture starts with `ScrollPhase.BEGAN`. |
| Slider values out of safe range or `coast_threshold < cutoff_v` | Validation at load | Clamp; emit warning to log. |
| Wake-from-sleep / event-loop stall | `dt_s` clamp in tick loop | Frame `dt` ≤ 50 ms regardless of wall time. |
| USB disconnect | `hid_read` errors | `HidIoWorker` enters reopen backoff; on success, restores readiness; firmware reset clears `host_scroll_ready`, fallback engaged until next heartbeat. |

## Testing

### Pure-logic unit tests (no hardware, no Quartz)

`tests/test_scroll_model.py` — `ScrollEngine` driven by virtual clock,
`post_scroll` captured to a list. Coverage:

- Single isolated detent in IDLE → total emitted output ≤ 15 px.
  (Precision guarantee.)
- Sustained slow detents (one per 200 ms) → emitted output per detent
  ≈ `slow_steady_expected_px` within tolerance.
- Sustained fast detents → MagSpeed gain ramps to `max_gain` within
  expected number of detents; output per detent ≈ free-spin range.
- Steady spin rate produces a **stable** velocity, not indefinite ramp.
  (Damping invariant.)
- Release after burst → MOMENTUM begins, decay reaches `cutoff_v` at
  expected wall-time (within tolerance of `τ × ln(v0/cutoff_v)`).
- Direction-flip during MOMENTUM → exactly one `MomentumPhase.ENDED`
  emitted, then new gesture with `ScrollPhase.BEGAN`.
- Direction-flip during ACTIVE → velocity zeroed, accumulator zeroed,
  no extra phase events.
- `enter_idle` clears both `velocity` and `accumulator`.
- `enter_idle_from_momentum` clears both `velocity` and `accumulator`.
- Accumulator sums to integer pixels over a long run (no rounding drift
  > 1 px after 10,000 ticks).
- `tau_ms` is correctly converted to seconds in the decay formula.
- First tick after long idle: `dt` clamp prevents huge first-frame
  delta (`>=` 50 ms wall doesn't translate to runaway output).
- Malformed `scroll.json` ignored; defaults applied; values clamped.
- `coast_threshold < cutoff_v` rejected at load with warning.
- `invert=True` reverses output sign.

`tests/test_hid_io.py` — `HidIoWorker` against a fake hid handle:

- `send_request` returns a Future fulfilled by a reply with matching
  command ID.
- FIFO ordering: two concurrent `send_request(GET_KEY)` calls receive
  replies in the order they were sent.
- `send_untracked` does *not* enter the future table; replies to
  unrelated commands aren't mis-attributed.
- `0xA1` frame routes to `scroll_tick` signal (no future side-effect).
- `0xFF` reply fulfils the appropriate future with `IdUnhandledError`.
- Unknown command ID + no pending future → dropped, logged, no panic.
- Short reads tolerated.
- 5 consecutive read errors → close + reopen with backoff schedule.

### Firmware build-time check

- `firmware/build.sh` is expected to compile cleanly; a manual diff
  check confirms `inertia.c` ends up linked (look for it in the build
  log). Failing case is `SRCS += inertia.c` (typo), so we verify the
  Makefile output references `inertia.c`.

### Manual hardware verification

After flashing new firmware **and ensuring EEPROM state is consistent**
(see "VIA EEPROM migration" below):

1. **Fallback (GUI closed).** Outer encoder scrolls vertically as
   plain detented wheel.
2. **Fallback (GUI open, Accessibility denied).** Outer encoder still
   produces firmware wheel events. (Critical: the encoder must not go
   dead just because the GUI is running without permission.)
3. **Takeover.** Launch GUI with Accessibility granted. Outer encoder
   turns → pixel-smooth scroll. Confirm via `scripts/scroll_probe.py`
   that emitted events have `IsContinuous=1`, correct phase sequence.
4. **Coast.** Spin fast, release → page coasts and decays smoothly,
   ending without a visible jolt.
5. **Direction-flip kill.** Spin fast, immediately reverse → coast
   instantly cancels, page reverses.
6. **Precision.** Slow careful turns → small predictable scroll per
   detent (visually consistent with the 7–30 px range from the worked
   examples).
7. **Crash recovery (corrected wording).** Force-quit GUI mid-coast →
   *host-synthesized momentum stops immediately* (the process is gone).
   Within ~500 ms, new outer-ring detents produce plain firmware wheel
   events again. (The previous spec wording that said "scroll continues
   from firmware fallback" was misleading.)
8. **USB unplug / replug.** Unplug during use → GUI reflects
   disconnect; replug → `HidIoWorker` reopens; readiness restored;
   takeover resumes.
9. **Layer change.** Confirm outer-encoder behaviour identical across
   `_BASE`, `_MOUSE`, `_MEDIA`, `_LIGHTS`. Inner-knob bindings on each
   layer unchanged.
10. **Direction calibration.** With macOS "natural scrolling" both ON
    and OFF, verify CW (or whichever convention is chosen) scrolls
    pages in the direction the user expects, with and without
    `invert=True`.
11. **App matrix** — Safari, Chrome, Finder, VS Code, Preview (PDFs),
    Terminal. For each, log emitted event shape via
    `scripts/scroll_probe.py`; document how each app responds (some may
    not fully honour momentum phase; that's data, not a defect).

## VIA EEPROM migration

With `ENCODER_MAP_ENABLE=yes`, encoder bindings are stored in EEPROM at
first boot (copied from `encoder_map` in flash). Subsequent VIA reads
go to EEPROM, not the compile-time `encoder_map`. Flashing new firmware
**does not** automatically refresh stored encoder bindings; without
migration, old bindings survive on the user's device.

Three options, ordered by preference:

1. **Bump the VIA layout version** in `keymap.c`/`config.h` (the
   product-version macro VIA reads). On boot, VIA detects the bump and
   re-copies `encoder_map` from flash to EEPROM. Zero user friction.
2. **One-time firmware migration** in `keyboard_post_init_user()`:
   explicitly overwrite encoder bindings for index 1 across all layers
   to `OUTER_SCROLL_CCW/CW`. Idempotent.
3. **Manual EEPROM reset** via QMK bootmagic on first plug. Cheapest in
   firmware code; requires the user to know the bootmagic gesture.

Spec choice: **Option 1 (layout version bump)**. The implementation
plan specifies which macro to bump and how to verify VIA re-syncs.
Option 2 is the fallback if the bump turns out to be a no-op on this
QMK version.

The keymap matrix (per-layer keycodes, not encoder bindings) is
untouched by this change, so no migration is needed there.

## Out of scope (notes, not TODOs)

- **Horizontal scroll on the outer ring**, e.g. modifier-held. Frame
  format reserves bytes for it; no current ask.
- **Per-app gain profiles.** Possible later via
  `CGEventGetIntegerValueField(kCGEventSourceUserData)` plus front-app
  detection.
- **Push-to-toggle MagSpeed** like MX's physical button under the wheel.
- **Linux / Windows event posting.** Transport (firmware + HidIoWorker +
  inertia math) is portable; only `scroll.py:post_scroll` is
  macOS-specific. Linux would replace it with `uinput`.
- **Tactile fake-detent feedback** via the LED matrix on each "virtual
  detent" in free-spin mode.
- **Rate-estimation inertia model** (alternative to damped impulse).
  Picked damped-impulse for simplicity; if feel is wrong, this is the
  primary alternative to try.

## Open verifications

These are deferred to implementation time, with the named fallback if
the assumption fails:

- `pyobjc-framework-Quartz` and `pyobjc-framework-ApplicationServices`
  install cleanly under uv + Python 3.13. Fallback: pin a known-good
  version (`>=12`).
- `Quartz.CGEventCreateScrollWheelEvent2` is the correct binding name
  in the pyobjc version used. Fallback: try `CGEventCreateScrollWheelEvent`
  (non-`2`); difference is the wheelCount arg position.
- `via_command_kb()` signature is `bool via_command_kb(uint8_t *data,
  uint8_t length)` in the target QMK version. Fallback: check
  `qmk_firmware/quantum/via.c` at the SHA the build script pins and
  adapt.
- `RAW_ENABLE = yes` is needed alongside `VIA_ENABLE = yes` for
  `raw_hid_send` to be linked. Fallback: add `RAW_ENABLE = yes` to
  `rules.mk` if compilation fails.
- `MS_WHLU` / `MS_WHLD` are valid keycodes accepted by `tap_code()`
  under the target QMK. Fallback: use `tap_code16()` if compilation
  complains.
- VIA layout-version bump triggers EEPROM re-sync of encoder bindings.
  Fallback: option 2 (post-init explicit overwrite).
- `AXIsProcessTrustedWithOptions` works under the ad-hoc-signed `.app`
  bundle. Accessibility binds to the code signature, so a rebuild may
  re-prompt; documented in the manual-test checklist.

## Readiness gate (acceptance for implementation plan)

All of these must be true before the design is considered ready:

- Encoder integration works with `ENCODER_MAP_ENABLE=yes` via custom
  keycodes + `process_record_user`.
- VIA still works after adding the heartbeat custom command; existing
  GUI features (keymap, lighting, layer inspection) unaffected.
- Firmware fallback works when GUI is closed.
- Firmware fallback works when Accessibility is denied.
- Host-side takeover engages only when all four readiness conditions
  hold.
- One slow detent emits ≤ 15 px (precision unit test passes).
- Fast spinning produces bounded fling (worked-example numbers hold).
- Direction matches between fallback and host modes (with the same
  `invert` setting in each, where applicable).
- Threading model has exactly one `HidIoWorker` owning the `0xFF60`
  handle.
- Unit tests cover every state-machine edge case listed under
  "Testing" → "Pure-logic unit tests".
- Manual tests pass across the app matrix.
