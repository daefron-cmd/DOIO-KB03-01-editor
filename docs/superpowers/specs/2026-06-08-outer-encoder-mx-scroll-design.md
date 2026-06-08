# Outer-encoder MX-Master scroll emulation — design

Status: draft, awaiting review
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
2. **MagSpeed gain.** Output magnitude is `velocity × gain(|velocity|)`,
   where `gain()` is piecewise linear:
   - `|v| ≤ slow_threshold` → gain = 1.0 (precision: 1 detent ≈ N pixels)
   - `|v| ≥ fast_threshold` → gain = `max_gain` (free-spin throughput)
   - between → linear interpolation
3. **Coast.** When no detent arrives for `active_window_ms` (default 80 ms),
   the engine transitions to a momentum phase. Velocity decays
   exponentially with time constant `τ` (default 350 ms). Once `|v|` drops
   below `cutoff_v`, momentum ends.
4. **Direction-flip kill.** A detent whose sign opposes current velocity
   zeroes velocity (and accumulator) instantly before applying its own
   impulse, so reversing immediately cancels coast.
5. **Pixel-precise output (host-online mode).** Output is posted as
   `CGEventCreateScrollWheelEvent2` with `kCGScrollEventUnitPixel`,
   `IsContinuous=1`, and explicit `ScrollPhase` and `MomentumPhase` flags
   following the trackpad gesture sequence:
   `Began → Changed → Ended → MomentumBegan → MomentumChanged → MomentumEnded`.
6. **Standalone fallback (host-offline mode).** When the host app isn't
   running, the outer ring emits plain `MS_WHLU`/`MS_WHLD` HID reports
   exactly as today. The encoder still works on any machine, just without
   the MX feel.
7. **Inner knob untouched.** All existing per-layer bindings on encoder 0
   remain.
8. **Cross-layer.** Outer-ring behaviour is identical on `_BASE`, `_MOUSE`,
   `_MEDIA`, and `_LIGHTS`. Previous outer-ring bindings on the non-`_BASE`
   layers (`MS_LEFT/RGHT`, `KC_MPRV/MNXT`, `RM_HUED/U`) are removed.

## Architecture

### Topology

```
┌─────────────────────────────────────────────────────────────────┐
│ Firmware  (firmware/keymaps/vegar/)                             │
│                                                                 │
│  encoder_update_user(idx, cw)                                   │
│   ├─ idx 0 (inner knob) ─► return true (default keymap path)    │
│   └─ idx 1 (outer ring) ─► if host_online: raw_hid_send(0xA1…)  │
│                            else:           tap MS_WHLU/MS_WHLD  │
│                            return false                         │
│                                                                 │
│  inertia.c/h:                                                   │
│   - host_online watchdog (last_ping_ms; 500 ms window)          │
│   - raw_hid_receive(): sentinel 0xA0 ↦ heartbeat refresh        │
│   - send sentinel 0xA1 frame on each outer-ring detent          │
└─────────────────────────────────────────────────────────────────┘
                            ▲                    │
                            │ heartbeat 0xA0     │ scroll ping 0xA1
                            │ every 200 ms       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Host  (Python / PySide6)                                        │
│                                                                 │
│  core.py        - add SCROLL_PING=0xA1, HOST_ALIVE=0xA0         │
│  reader.py NEW  - dedicated 0xFF60 read loop; demux replies vs  │
│                   unsolicited frames; emits scroll_tick signal  │
│  worker.py      - writes only; 200 ms heartbeat; request/       │
│                   response now via reader's Future queue        │
│  scroll.py NEW  - ScrollEngine on its own QThread: inertia      │
│                   state, ~120 Hz tick, posts CGEvent            │
│  ui.py          - "Scroll feel" panel (sliders + persistence)   │
│  main.py        - wires Reader, Worker, ScrollEngine threads    │
└─────────────────────────────────────────────────────────────────┘
                            ▲
                            │  CGEventPost (HID tap, pixel units,
                            │   ScrollPhase + MomentumPhase set)
                            ▼
                       macOS event system → apps
```

### The reader-thread refactor

Today `core.cmd()` is strict write-then-read on the same thread, so
`ControlWorker` doubles as its own reader. Unsolicited device→host frames
(the `0xA1` scroll pings) break that pattern.

We introduce a **single dedicated reader thread** on the `0xFF60` handle
that:

- demuxes replies (matched to outstanding write requests by command-ID,
  returned via a `concurrent.futures.Future`),
- routes sentinel frames to subscribers (`scroll_tick` Qt signal for `0xA1`).

The existing **single-owner caveat** still holds at the OS-handle level;
only the *internal* dispatch within `main.py` changes. Writers (worker,
heartbeat timer) call into the reader's request API; the reader is the
only caller of `hid_read`.

### Threads, final state

| Thread | Owns | Notes |
|---|---|---|
| UI | `MainWindow`, painters, slots | Same as today |
| Reader | `hid_read` on `0xFF60` | NEW. Demuxes; dispatches to worker futures + scroll signal |
| Control | `ControlWorker`, writes on `0xFF60` | Submits via reader's request API; drives 200 ms heartbeat |
| Listener | Keyboard + consumer HID handles | Unchanged |
| Scroll | `ScrollEngine` | NEW. 120 Hz tick, posts CGEvent |

### File-level change list

| File | Change | Approx size |
|---|---|---|
| `firmware/keymaps/vegar/inertia.{c,h}` (new) | host_online watchdog, raw_hid send/receive helpers | ~80 lines |
| `firmware/keymaps/vegar/keymap.c` | add `encoder_update_user` override; null out `encoder_map[*][1]` to `KC_NO` (cosmetic — override suppresses dispatch anyway, but `KC_NO` documents intent and stops VIA from showing stale bindings on the outer ring) | ~25 lines |
| `firmware/keymaps/vegar/rules.mk` | add `SRCS += inertia.c` | 1 line |
| `firmware/keymaps/vegar/config.h` | unchanged. Existing `MOUSEKEY_WHEEL_*` constants still govern the standalone fallback (which goes through `tap_code` → QMK mousekey machinery). Add a header comment pointing at this design doc. | trivial |
| `core.py` | add `SCROLL_PING`, `HOST_ALIVE`; `cmd` becomes a thin wrapper that uses the reader's request API | ~30 lines net |
| `reader.py` (new) | dedicated reader thread, demux, subscriber registry | ~120 lines |
| `worker.py` | reader-backed request/response; 200 ms heartbeat timer | ~30 lines changed |
| `scroll.py` (new) | `ScrollEngine` — inertia state machine + macOS event posting | ~200 lines |
| `ui.py` | "Scroll feel" panel (sliders), Accessibility-permission banner | ~80 lines |
| `main.py` | thread wiring | ~10 lines |
| `tests/test_scroll_model.py` (new) | inertia model unit tests (no hardware, no Quartz) | ~120 lines |
| `tests/test_reader.py` (new) | demux logic against a fake hid handle | ~80 lines |

## Inertia model

### State

```python
@dataclass
class ScrollState:
    velocity: float = 0.0        # signed, pixels/sec
    accumulator: float = 0.0     # sub-pixel carry
    last_tick_ms: int = 0        # monotonic, ms
    last_emit_ms: int = 0
    phase: Phase = Phase.IDLE    # IDLE | ACTIVE | MOMENTUM
```

### Tick loop (120 Hz)

```
now = monotonic_ms()
dt  = (now - last_emit_ms) / 1000

# 1. Active → Momentum
if phase == ACTIVE and (now - last_tick_ms) > active_window_ms:
    if abs(velocity) > coast_threshold:
        post_scroll(0, ScrollPhase.ENDED, MomentumPhase.NONE)
        post_scroll(0, ScrollPhase.NONE,  MomentumPhase.BEGAN)
        phase = MOMENTUM
    else:
        post_scroll(0, ScrollPhase.ENDED, MomentumPhase.NONE)
        phase = IDLE
        velocity = 0.0

# 2. Decay (momentum only)
if phase == MOMENTUM:
    velocity *= exp(-dt / tau)
    if abs(velocity) < cutoff_v:
        post_scroll(0, ScrollPhase.NONE, MomentumPhase.ENDED)
        phase = IDLE
        velocity = 0.0
        return

# 3. Emit
gain     = magspeed_gain(abs(velocity))
pixels_f = velocity * gain * dt + accumulator
pixels   = int(pixels_f)             # truncate toward zero
accumulator = pixels_f - pixels       # carry fraction
if pixels != 0:
    if phase == MOMENTUM:
        post_scroll(pixels, ScrollPhase.NONE,    MomentumPhase.CHANGED)
    else:
        post_scroll(pixels, ScrollPhase.CHANGED, MomentumPhase.NONE)
last_emit_ms = now
```

### Detent arrival (queued cross-thread call from reader)

```python
def on_tick(direction: int, device_t_ms: int):
    now = monotonic_ms()
    impulse = impulse_per_detent  # tunable

    # Direction-flip kill
    if velocity != 0 and sign(velocity) != sign(direction):
        velocity = 0.0
        accumulator = 0.0
        if phase == MOMENTUM:
            post_scroll(0, ScrollPhase.NONE, MomentumPhase.ENDED)

    if phase in (IDLE, MOMENTUM):
        if phase == MOMENTUM:
            post_scroll(0, ScrollPhase.NONE, MomentumPhase.ENDED)
        post_scroll(0, ScrollPhase.BEGAN, MomentumPhase.NONE)
        phase = ACTIVE

    velocity = clamp(velocity + direction * impulse, -v_max, v_max)
    last_tick_ms = now
```

### MagSpeed gain curve

```python
def magspeed_gain(abs_v):
    if abs_v <= slow_threshold: return 1.0
    if abs_v >= fast_threshold: return max_gain
    t = (abs_v - slow_threshold) / (fast_threshold - slow_threshold)
    return 1.0 + t * (max_gain - 1.0)
```

### Defaults (all GUI-tunable except `v_max`)

| Param | Default | Slider range |
|---|---|---|
| `impulse_per_detent` | 1500 px/s | 200–6000 |
| `slow_threshold` | 1500 px/s | 200–4000 |
| `fast_threshold` | 6000 px/s | 2000–20000 |
| `max_gain` | 5.0× | 1.0–12.0 |
| `tau` (decay) | 350 ms | 50–2000 |
| `active_window_ms` | 80 ms | 30–250 |
| `cutoff_v` | 40 px/s | 5–200 |
| `coast_threshold` | = `cutoff_v` | (not a separate slider) |
| `v_max` | 25000 px/s | hard clamp |

`coast_threshold` is set equal to `cutoff_v`: if velocity at release is
already below the end-of-momentum cutoff, there's no momentum to coast,
so we skip directly IDLE→IDLE (post `ScrollPhase.ENDED` only). One
fewer slider, no expressivity loss.

Persisted to `~/.config/doio-kb03/scroll.json` (or
`$XDG_CONFIG_HOME/...`). Malformed file → defaults applied, file ignored.
Out-of-range values are clamped at load.

## macOS event posting

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

The combination of continuous + pixel units + explicit phase + momentum
phase is what Safari/Chrome/Finder treat as a real trackpad gesture,
including any *additional* native momentum smoothing the app layers on
top of ours.

### Permission

First `CGEventPost` to `kCGHIDEventTap` prompts for **Accessibility**
(System Settings → Privacy & Security → Accessibility). Until granted,
`CGEventPost` silently no-ops to other apps.

The GUI detects the state via
`AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})` and
shows a banner above the "Scroll feel" panel until it's granted.

## Heartbeat & takeover

### Firmware side

```
host_online :: bool       // false at boot
last_ping_ms :: uint32_t  // 0 at boot

void raw_hid_receive(uint8_t *data, uint8_t length):
    if (data[0] == 0xA0) {            // HOST_ALIVE
        last_ping_ms = timer_read32();
        host_online  = true;
    }

void housekeeping_task_user(void):
    if (host_online && timer_elapsed32(last_ping_ms) > 500)
        host_online = false;

bool encoder_update_user(uint8_t idx, bool cw):
    if (idx != 1) return true;        // inner knob → default path
    if (host_online) {
        uint8_t f[32] = {0};
        f[0] = 0xA1;                  // SCROLL_PING
        f[1] = cw ? 1 : 0;
        // f[2..5] = little-endian timer_read32() — reserved, host ignores for now
        raw_hid_send(f);
    } else {
        tap_code(cw ? KC_MS_WHEEL_DOWN : KC_MS_WHEEL_UP);
    }
    return false;                     // suppress default keymap dispatch
```

Watchdog window 500 ms ≈ 2.5 missed heartbeats at 200 ms cadence. On
host crash or app quit, the encoder is back to fallback within half a
second.

### Host side

```
main.py start:
    reader thread starts, opens 0xFF60
    worker starts heartbeat timer (200 ms): writes {0xA0, 0, …}
    scroll engine subscribes to reader's scroll_tick signal

main.py exit:
    heartbeat timer stops
    reader thread closes handle
    firmware watchdog times out → fallback within 500 ms
```

### Reader demux

```
on hid_read(buf):
    cmd_id = buf[0]
    if cmd_id == 0xA1:                          # SCROLL_PING
        dir = 1 if buf[1] else -1
        device_t_ms = int.from_bytes(buf[2:6], 'little')
        emit scroll_tick(dir, device_t_ms)
    elif cmd_id in pending_requests:
        fut = pending_requests.pop(cmd_id)
        fut.set_result(buf)
    else:
        log unexpected; drop
```

VIA's current command-ID space (`0x01..0x15`) doesn't collide with
`0xA0/0xA1`, and VIA replies always echo the request's `cmd_id` in
`buf[0]` — demux is unambiguous.

## Error handling

| Failure | Detected by | Response |
|---|---|---|
| Accessibility denied | `AXIsProcessTrustedWithOptions()` returns false | GUI banner on the "Scroll feel" panel; CGEvent calls are no-op anyway |
| Firmware doesn't recognise `0xA0` (not yet flashed) | No `0xA1` frames ever arrive | ScrollEngine silently idle; firmware stays in pre-change behaviour |
| Host crashes mid-scroll | Firmware watchdog (500 ms) | Fallback engages; user gets a plain detented wheel |
| Reader can't open `0xFF60` | Open returns `None` | Match existing UI behaviour for "device not connected" |
| `hid_read` timeout / error | Read loop catches | Drop and continue; on 5 consecutive errors, close + retry open with backoff |
| Direction flip mid-momentum | Sign mismatch in `on_tick` | Velocity zeroed, MomentumPhase.ENDED posted, new gesture starts |
| Slider values out of safe range | Clamp at load | Persistence file ignored if malformed; defaults applied |
| Two outer-ring detents in same tick window | Coalesce in `on_tick` | Each adds an impulse; phase transitions still single-fire |

## Testing

### Pure-logic unit tests (no hardware, no Quartz)

`tests/test_scroll_model.py`:

- Single detent in IDLE → ACTIVE, velocity = `impulse_per_detent`, accumulator carries fractional pixels.
- Sustained turns → MagSpeed gain ramps from 1.0 toward `max_gain`.
- Stop turning → ACTIVE → MOMENTUM transition after `active_window_ms`.
- Decay reaches `cutoff_v` in expected wall-time (within tolerance of
  `τ · ln(impulse / cutoff)`).
- Direction-flip zeroes velocity and posts MomentumPhase.ENDED.
- Accumulator sums to integer pixels over a long run (no rounding drift).
- Tunable params load and clamp from a malformed JSON file.

`tests/test_reader.py`:

- Demux routes `0xA1` to the scroll subscriber.
- Demux routes a `0x04` reply to the correct pending future.
- Unknown command IDs are dropped, logged, not propagated.
- Short reads are tolerated and don't desync.
- 5-in-a-row read errors trigger close + reopen.

### Manual hardware verification

Run after flashing new firmware and launching the GUI.

1. **Fallback works.** With GUI closed: outer encoder scrolls vertically
   (plain detented wheel, same as today).
2. **Takeover engages.** Launch GUI. Outer encoder turns → page scroll is
   pixel-smooth (verify by visual smoothness; cross-check by running
   `probe.py` in parallel to observe wheel-report stream is now empty
   while host is up).
3. **Coast.** Spin fast then release → page coasts and decays smoothly,
   ending without a visible jolt.
4. **Direction-flip kill.** Spin fast, immediately reverse → coast
   instantly cancels, page reverses with no fight.
5. **Precision mode.** Slow careful turns → 1 detent = a small, precise
   amount of scroll.
6. **Crash recovery.** Force-quit GUI mid-coast → scroll continues from
   firmware fallback within ~500 ms (verify by watching pages scroll
   without GUI process running).
7. **App matrix.** Test in Safari, Chrome, Finder, VS Code, Preview
   (PDFs), Terminal — each scrollview reacts differently to
   MomentumPhase; we want to confirm all major ones look right.

## Out of scope (notes, not TODOs)

- **Horizontal scroll on the outer ring**, e.g. modifier-held. The
  firmware path supports it (different sentinel byte), but no current
  ask.
- **Per-app gain profiles** (different inertia in Finder vs Safari).
  Possible later via `CGEventGetIntegerValueField(kCGEventSourceUserData)`
  plus front-app detection.
- **Push-to-toggle MagSpeed** like MX's physical button under the wheel.
  Knob push is currently `KC_LCTL` on `_MOUSE` and could double as the
  toggle, but adds firmware complexity.
- **Linux / Windows event posting.** The transport (firmware + reader +
  worker + inertia math) is portable; only `scroll.py:post_scroll` is
  macOS-specific. A Linux port would replace it with `uinput`.
- **Tactile fake-detent feedback** via the LED matrix (e.g. a brief flash
  on each "virtual detent" in free-spin mode). Cute, ignorable.

## Open verifications (do during implementation, not now)

- Confirm `pyobjc-framework-Quartz` is already on the dependency graph
  (PySide6's transitive deps include `pyobjc-framework-Cocoa` on macOS,
  but `Quartz` is separate). If not, add to `pyproject.toml`.
- Confirm `Quartz.CGEventCreateScrollWheelEvent2` is the right ABI for
  the continuous + phase + momentum-phase combination (vs the older
  non-`2` variant) on current macOS.
- Confirm QMK's `raw_hid_send` is available with `VIA_ENABLE=yes` and no
  separate `RAW_ENABLE` toggle is needed (VIA enables raw HID under the
  hood; verify in `qmk_firmware/quantum/via.c`).
- Confirm `AXIsProcessTrustedWithOptions` works under the ad-hoc-signed
  `.app` bundle (`scripts/build_app_bundle.sh`) — Accessibility tends to
  bind to the code signature, so a rebuild may re-prompt.
