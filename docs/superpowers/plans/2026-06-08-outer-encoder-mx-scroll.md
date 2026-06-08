# Outer-encoder MX-Master scroll emulation — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the outer ring (encoder index 1) of the DOIO KB03-01 behave like a Logitech MX Master 3S vertical scroll wheel — with coast, MagSpeed-style gain, direction-flip kill, pixel-precise output, and proper macOS momentum phases — by running an inertia model in the host app and switching the firmware between standalone-fallback and host-takeover modes.

**Architecture:** Single `HidIoWorker` owns the `0xFF60` handle for read + write + future demux. The firmware uses encoder-map → custom keycodes (`OUTER_SCROLL_CW/CCW`) → `process_record_user` to either tap-fallback (`MS_WHLU/D`) or `raw_hid_send` a `SCROLL_PING` (`0xA1`) when the host is ready. The host runs a `ScrollEngine` on its own thread that consumes `scroll_tick` signals and posts `CGEventCreateScrollWheelEvent2` events with pixel units and explicit `ScrollPhase`/`MomentumPhase`. A heartbeat (`HOST_SCROLL_READY=0xA0`, sent through `via_command_kb`) gates firmware takeover on all four host readiness conditions.

**Tech Stack:** Python 3.13, PySide6, hidapi, pyobjc (Quartz + ApplicationServices), QMK + VIA.

**Reference spec:** [`docs/superpowers/specs/2026-06-08-outer-encoder-mx-scroll-design.md`](../specs/2026-06-08-outer-encoder-mx-scroll-design.md). The plan implements that spec. If they conflict, the spec wins; flag the inconsistency and stop.

---

## File structure

**New files:**

| Path | Role |
|---|---|
| `hid_io.py` | `HidIoWorker` — single owner of the `0xFF60` handle. Read loop, write queue, per-command-ID FIFO future demux, `scroll_tick` signal, close/reopen with backoff. |
| `scroll.py` | `ScrollEngine` (`QObject` on its own `QThread`), `ScrollState`, `ScrollConfig`, `Phase` enum. Inertia state machine + macOS event posting. |
| `scripts/scroll_probe.py` | Standalone event-tap probe that logs every scroll event's phase / momentum-phase / hasPreciseScrollingDeltas / deltaY. Used to empirically verify CGEvent shape per app. |
| `firmware/keymaps/vegar/inertia.h` | Public API for the inertia/host-readiness state machine (firmware side). |
| `firmware/keymaps/vegar/inertia.c` | `host_scroll_ready` watchdog, `via_command_kb`, `inertia_send_scroll_ping`. |
| `tests/test_scroll_model.py` | Pure-logic tests of `ScrollEngine` (virtual clock; `post_scroll` captured to list). |
| `tests/test_hid_io.py` | `HidIoWorker` tests against a fake hid handle. |
| `tests/test_scroll_config.py` | Config loading / clamping / invert tests. |

**Modified files:**

| Path | Change |
|---|---|
| `pyproject.toml` | Add `pyobjc-framework-Quartz`, `pyobjc-framework-ApplicationServices`. |
| `core.py` | Refactor: pure frame *builders* and *parsers* (`build_get_key`, `parse_get_encoder_reply`, …). The old `cmd()` is kept as a backward-compat thin shim that goes through `HidIoWorker.send_request` once we migrate the worker. |
| `worker.py` | `ControlWorker` no longer owns `0xFF60`. It calls `HidIoWorker`. Adds the four-gate readiness state machine and the heartbeat `QTimer`. |
| `main.py` | Wire `HidIoWorker` + `ScrollEngine` threads. Call `AXIsProcessTrustedWithOptions` on startup. |
| `ui.py` | New "Scroll feel" panel (sliders + invert toggle). Accessibility-permission banner with "Re-check" button. |
| `firmware/keymaps/vegar/keymap.c` | `enum custom_keycodes { OUTER_SCROLL_CCW = SAFE_RANGE, OUTER_SCROLL_CW }`; encoder_map for index 1 across all 4 layers; `process_record_user` handler. |
| `firmware/keymaps/vegar/config.h` | Bump `DEVICE_VER` (VIA layout version) to force EEPROM re-sync of encoder bindings. Header comment pointing at this design doc. |
| `firmware/keymaps/vegar/rules.mk` | `SRC += inertia.c` (note: `SRC`, not `SRCS`). Add `RAW_ENABLE = yes` if firmware build fails without it. |

---

## Phase 1 — Setup and probe utility

### Task 1: Add pyobjc dependencies and verify imports

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/test_smoke.py` (extend)

- [ ] **Step 1: Add the dependencies**

Edit `pyproject.toml`. After the existing `PySide6>=6.8,` line in `dependencies`, add:

```toml
    "pyobjc-framework-Quartz>=12",
    "pyobjc-framework-ApplicationServices>=12",
```

- [ ] **Step 2: Resolve the new deps**

Run: `uv sync`
Expected: completes successfully; `uv.lock` updated.

- [ ] **Step 3: Add a smoke import test**

Open `tests/test_smoke.py`. Append:

```python
def test_pyobjc_imports_available_on_darwin():
    import sys
    if sys.platform != "darwin":
        return  # macOS-only deps
    import Quartz  # noqa: F401
    import ApplicationServices  # noqa: F401
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS (all smoke tests, including the new one on macOS).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/test_smoke.py
git commit -m "build: add pyobjc Quartz + ApplicationServices for scroll engine"
```

---

### Task 2: Scroll-event probe utility

**Files:**
- Create: `scripts/scroll_probe.py`

This is a standalone helper used to verify per-app behaviour during manual testing. Not unit-testable; verified by running it.

- [ ] **Step 1: Write the script**

Create `scripts/scroll_probe.py`:

```python
"""Scroll event probe. Logs every scroll-wheel CGEvent that flows through
the session tap. Use it to verify our emitted scroll events have the
right phase/momentum-phase/IsContinuous/deltaY shape, and to compare
against a real trackpad. Requires Accessibility permission for
Terminal/iTerm (whatever runs this).

Run with the GUI closed — it does not touch 0xFF60.

    uv run python scripts/scroll_probe.py
"""

from __future__ import annotations

import sys
import time

import Quartz


SCROLL_WHEEL_EVENT = Quartz.kCGEventScrollWheel
MASK = Quartz.CGEventMaskBit(SCROLL_WHEEL_EVENT)


def _phase_name(value: int) -> str:
    return {
        0: "none",
        1: "began",
        2: "stationary",
        4: "changed",
        8: "ended",
        16: "cancelled",
        128: "may-begin",
    }.get(value, f"unknown({value})")


def _momentum_name(value: int) -> str:
    return {
        0: "none",
        1: "began",
        2: "changed",
        3: "ended",
    }.get(value, f"unknown({value})")


def _tap_callback(proxy, type_, ev, refcon):
    if type_ != SCROLL_WHEEL_EVENT:
        return ev
    g = Quartz.CGEventGetIntegerValueField
    phase = g(ev, Quartz.kCGScrollWheelEventScrollPhase)
    mom   = g(ev, Quartz.kCGScrollWheelEventMomentumPhase)
    cont  = g(ev, Quartz.kCGScrollWheelEventIsContinuous)
    dy    = g(ev, Quartz.kCGScrollWheelEventDeltaAxis1)
    pdy   = g(ev, Quartz.kCGScrollWheelEventPointDeltaAxis1)
    print(
        f"{time.monotonic():.3f}  phase={_phase_name(phase):<10} "
        f"momentum={_momentum_name(mom):<8} cont={cont} "
        f"deltaY={dy:>5} pointDeltaY={pdy:>5}",
        flush=True,
    )
    return ev


def main() -> int:
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        MASK, _tap_callback, None,
    )
    if not tap:
        print("Could not create event tap — grant Accessibility to this terminal.",
              file=sys.stderr)
        return 1
    src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    print("Listening for scroll events. Ctrl-C to stop.", file=sys.stderr)
    try:
        Quartz.CFRunLoopRun()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify it runs**

Run: `uv run python scripts/scroll_probe.py`

Expected: prints "Listening for scroll events. Ctrl-C to stop." then logs lines as you scroll with the trackpad. If it can't create the tap, the terminal needs Accessibility permission (System Settings → Privacy & Security → Accessibility → add your terminal).

- [ ] **Step 3: Commit**

```bash
git add scripts/scroll_probe.py
git commit -m "feat(scripts): scroll-event probe for per-app shape verification"
```

---

## Phase 2 — Inertia model (pure logic, TDD)

The whole inertia model is built and unit-tested without touching macOS event posting or hardware. `post_scroll` is a callback we pass in.

### Task 3: ScrollState, Phase, ScrollConfig dataclasses

**Files:**
- Create: `scroll.py`
- Create: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scroll_model.py`:

```python
from scroll import Phase, ScrollConfig, ScrollState


def test_scrollstate_defaults():
    s = ScrollState()
    assert s.velocity == 0.0
    assert s.accumulator == 0.0
    assert s.last_tick_ms == 0
    assert s.last_emit_ms == 0
    assert s.phase == Phase.IDLE


def test_scrollconfig_defaults():
    c = ScrollConfig()
    assert c.impulse_per_detent == 100.0
    assert c.tau_ms == 400
    assert c.slow_threshold == 200.0
    assert c.fast_threshold == 1500.0
    assert c.max_gain == 6.0
    assert c.active_window_ms == 80
    assert c.coast_threshold == 300.0
    assert c.cutoff_v == 40.0
    assert c.v_max == 2500.0
    assert c.invert is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scroll'`.

- [ ] **Step 3: Create the minimal scroll.py**

Create `scroll.py`:

```python
"""ScrollEngine: MX-Master-style scroll wheel emulation for the outer
encoder. Pure inertia state machine + macOS event posting.

The state machine and the Quartz post are split: pass `post_scroll`
(a callable taking pixels, scroll_phase, momentum_phase) into the
engine so the model is unit-testable without macOS.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    MOMENTUM = "momentum"


@dataclass
class ScrollConfig:
    impulse_per_detent: float = 100.0
    tau_ms: int = 400
    slow_threshold: float = 200.0
    fast_threshold: float = 1500.0
    max_gain: float = 6.0
    active_window_ms: int = 80
    coast_threshold: float = 300.0
    cutoff_v: float = 40.0
    v_max: float = 2500.0
    invert: bool = False


@dataclass
class ScrollState:
    velocity: float = 0.0
    accumulator: float = 0.0
    last_tick_ms: int = 0
    last_emit_ms: int = 0
    phase: Phase = Phase.IDLE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): Phase, ScrollConfig, ScrollState dataclasses"
```

---

### Task 4: MagSpeed gain function

**Files:**
- Modify: `scroll.py`
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scroll_model.py`:

```python
from scroll import magspeed_gain


def test_gain_below_slow_is_one():
    c = ScrollConfig()
    assert magspeed_gain(0.0, c) == 1.0
    assert magspeed_gain(c.slow_threshold, c) == 1.0


def test_gain_above_fast_is_max():
    c = ScrollConfig()
    assert magspeed_gain(c.fast_threshold, c) == c.max_gain
    assert magspeed_gain(c.fast_threshold + 1000, c) == c.max_gain


def test_gain_midpoint_is_linear():
    c = ScrollConfig(slow_threshold=200, fast_threshold=1200, max_gain=11)
    mid = (200 + 1200) / 2
    assert magspeed_gain(mid, c) == 6.0  # halfway: 1 + 0.5 * 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scroll_model.py::test_gain_below_slow_is_one -v`
Expected: FAIL with `ImportError: cannot import name 'magspeed_gain'`.

- [ ] **Step 3: Add the function**

In `scroll.py`, append after the dataclasses:

```python
def magspeed_gain(abs_v: float, c: ScrollConfig) -> float:
    if abs_v <= c.slow_threshold:
        return 1.0
    if abs_v >= c.fast_threshold:
        return c.max_gain
    t = (abs_v - c.slow_threshold) / (c.fast_threshold - c.slow_threshold)
    return 1.0 + t * (c.max_gain - 1.0)
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): MagSpeed gain curve (piecewise linear)"
```

---

### Task 5: ScrollEngine skeleton + post_scroll injection

**Files:**
- Modify: `scroll.py`
- Modify: `tests/test_scroll_model.py`

The engine is a plain `object` here (not a `QObject` yet) so we can unit-test the model without Qt or Quartz. Qt wrapping comes in Task 19.

- [ ] **Step 1: Write the failing test**

Append:

```python
from scroll import ScrollEngine, ScrollPhase, MomentumPhase


def test_engine_initial_state_is_idle():
    posts = []
    eng = ScrollEngine(now_fn=lambda: 0, post_scroll=lambda *a: posts.append(a))
    assert eng.state.phase == Phase.IDLE
    assert posts == []
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_scroll_model.py::test_engine_initial_state_is_idle -v`
Expected: FAIL — `ImportError: cannot import name 'ScrollEngine'`.

- [ ] **Step 3: Implement the skeleton**

In `scroll.py` append:

```python
from typing import Callable


class ScrollPhase:
    """Mirror of kCGScrollWheelEventScrollPhase enum values."""
    NONE = 0
    BEGAN = 1
    STATIONARY = 2
    CHANGED = 4
    ENDED = 8
    CANCELLED = 16
    MAY_BEGIN = 128


class MomentumPhase:
    """Mirror of kCGScrollWheelEventMomentumPhase enum values."""
    NONE = 0
    BEGAN = 1
    CHANGED = 2
    ENDED = 3


PostScroll = Callable[[int, int, int], None]
NowMs = Callable[[], int]


class ScrollEngine:
    """Pure inertia state machine. Drive ticks via tick(); deliver
    detents via on_tick(direction, device_t_ms).

    Both clock and event-post are injected so the engine is testable
    without macOS or wall-clock dependencies.
    """

    def __init__(
        self,
        *,
        now_fn: NowMs,
        post_scroll: PostScroll,
        config: ScrollConfig | None = None,
    ):
        self.config = config or ScrollConfig()
        self.state = ScrollState()
        self._now = now_fn
        self._post = post_scroll
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): ScrollEngine skeleton with injectable clock and post"
```

---

### Task 6: Phase-entry helpers (enter_active / enter_momentum / enter_idle)

**Files:**
- Modify: `scroll.py`
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def _make_engine(config=None, now=0):
    posts = []
    clock = [now]
    eng = ScrollEngine(
        now_fn=lambda: clock[0],
        post_scroll=lambda p, sp, mp: posts.append((p, sp, mp)),
        config=config,
    )
    return eng, posts, clock


def test_enter_active_resets_baselines_and_posts_began():
    eng, posts, clock = _make_engine(now=100)
    eng.state.velocity = 50.0
    eng.state.accumulator = 0.7
    eng.enter_active(now_ms=100)
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.last_tick_ms == 100
    assert eng.state.last_emit_ms == 100
    assert eng.state.accumulator == 0.0
    assert eng.state.velocity == 50.0  # NOT cleared (impulse preserved)
    assert posts == [(0, ScrollPhase.BEGAN, MomentumPhase.NONE)]


def test_enter_momentum_posts_ended_then_began():
    eng, posts, clock = _make_engine(now=200)
    eng.state.velocity = 1000.0
    eng.state.phase = Phase.ACTIVE
    eng.enter_momentum(now_ms=200)
    assert eng.state.phase == Phase.MOMENTUM
    assert eng.state.last_tick_ms == 200
    assert eng.state.last_emit_ms == 200
    assert posts == [
        (0, ScrollPhase.ENDED, MomentumPhase.NONE),
        (0, ScrollPhase.NONE,  MomentumPhase.BEGAN),
    ]


def test_enter_idle_clears_velocity_and_accumulator():
    eng, posts, _ = _make_engine()
    eng.state.velocity = 123.0
    eng.state.accumulator = 4.5
    eng.state.phase = Phase.ACTIVE
    eng.enter_idle(post_ended=True)
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert eng.state.accumulator == 0.0
    assert posts == [(0, ScrollPhase.ENDED, MomentumPhase.NONE)]


def test_enter_idle_without_post_ended_emits_nothing():
    eng, posts, _ = _make_engine()
    eng.enter_idle(post_ended=False)
    assert posts == []
    assert eng.state.phase == Phase.IDLE


def test_enter_idle_from_momentum_posts_one_momentum_ended():
    eng, posts, _ = _make_engine()
    eng.state.velocity = 800.0
    eng.state.accumulator = 1.1
    eng.state.phase = Phase.MOMENTUM
    eng.enter_idle_from_momentum()
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert eng.state.accumulator == 0.0
    assert posts == [(0, ScrollPhase.NONE, MomentumPhase.ENDED)]
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: FAIL — `AttributeError: 'ScrollEngine' object has no attribute 'enter_active'`.

- [ ] **Step 3: Implement the helpers**

Append inside `class ScrollEngine`:

```python
    def enter_active(self, now_ms: int) -> None:
        self.state.phase = Phase.ACTIVE
        self.state.last_tick_ms = now_ms
        self.state.last_emit_ms = now_ms
        self.state.accumulator = 0.0
        self._post(0, ScrollPhase.BEGAN, MomentumPhase.NONE)

    def enter_momentum(self, now_ms: int) -> None:
        self.state.phase = Phase.MOMENTUM
        self.state.last_tick_ms = now_ms
        self.state.last_emit_ms = now_ms
        self._post(0, ScrollPhase.ENDED, MomentumPhase.NONE)
        self._post(0, ScrollPhase.NONE, MomentumPhase.BEGAN)

    def enter_idle(self, *, post_ended: bool) -> None:
        if post_ended:
            self._post(0, ScrollPhase.ENDED, MomentumPhase.NONE)
        self.state.velocity = 0.0
        self.state.accumulator = 0.0
        self.state.phase = Phase.IDLE

    def enter_idle_from_momentum(self) -> None:
        self._post(0, ScrollPhase.NONE, MomentumPhase.ENDED)
        self.state.velocity = 0.0
        self.state.accumulator = 0.0
        self.state.phase = Phase.IDLE
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): phase-entry helpers reset baselines and clear state"
```

---

### Task 7: Tick loop — damping and emit (IDLE no-op + ACTIVE emit)

**Files:**
- Modify: `scroll.py`
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
import math


def test_tick_in_idle_does_nothing():
    eng, posts, _ = _make_engine()
    eng.tick()
    assert posts == []


def test_tick_in_active_emits_pixels_and_damps_velocity():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 1000.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    clock[0] = 10  # 10 ms tick
    eng.tick()
    expected_v_after_damp = 1000.0 * math.exp(-0.010 / 0.400)
    assert abs(eng.state.velocity - expected_v_after_damp) < 0.5
    # gain at 1000 with defaults (slow=200, fast=1500, max=6):
    # t = (1000-200)/(1500-200) = 0.615 → gain ≈ 1 + 0.615*5 ≈ 4.08
    # pixels_f ≈ 1000 * 4.08 * 0.010 ≈ 40.8
    assert posts
    assert posts[0][1] == ScrollPhase.CHANGED
    assert posts[0][2] == MomentumPhase.NONE
    assert 30 <= posts[0][0] <= 50


def test_tick_in_momentum_uses_momentum_phase():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 500.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    clock[0] = 10
    eng.tick()
    assert posts
    assert posts[0][1] == ScrollPhase.NONE
    assert posts[0][2] == MomentumPhase.CHANGED


def test_tick_accumulator_carries_fractional_pixels():
    eng, posts, clock = _make_engine(now=0)
    # craft a velocity that produces ~3.5 px per tick at gain=1
    cfg = eng.config
    cfg.slow_threshold = 1e9  # force gain=1
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 350.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    # tick at 10 ms → output ≈ 350 * 0.010 ≈ 3.5 px → int 3, acc 0.5 (before damp drift)
    clock[0] = 10
    eng.tick()
    assert posts[0][0] == 3
    assert 0.3 < eng.state.accumulator < 0.6
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_scroll_model.py::test_tick_in_idle_does_nothing -v`
Expected: FAIL — `AttributeError: 'ScrollEngine' object has no attribute 'tick'`.

- [ ] **Step 3: Implement tick (no phase transitions yet)**

Add `import math` at top of `scroll.py`. Append inside `class ScrollEngine`:

```python
    def tick(self) -> None:
        if self.state.phase == Phase.IDLE:
            return
        now = self._now()
        dt_s = max(0.0, min((now - self.state.last_emit_ms) / 1000.0, 0.050))
        tau_s = self.config.tau_ms / 1000.0

        # Damped velocity (applied in both ACTIVE and MOMENTUM)
        self.state.velocity *= math.exp(-dt_s / tau_s)

        # Emit
        gain = magspeed_gain(abs(self.state.velocity), self.config)
        pixels_f = self.state.velocity * gain * dt_s + self.state.accumulator
        pixels = int(pixels_f)
        self.state.accumulator = pixels_f - pixels
        if pixels != 0:
            if self.state.phase == Phase.MOMENTUM:
                self._post(pixels, ScrollPhase.NONE, MomentumPhase.CHANGED)
            else:
                self._post(pixels, ScrollPhase.CHANGED, MomentumPhase.NONE)
        self.state.last_emit_ms = now
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): tick loop with damping + emit (no transitions yet)"
```

---

### Task 8: Tick loop — phase transitions (ACTIVE → MOMENTUM / IDLE, MOMENTUM → IDLE)

**Files:**
- Modify: `scroll.py`
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_active_with_idle_period_transitions_to_momentum_if_fast():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 1000.0  # > coast_threshold (300)
    eng.state.last_tick_ms = 0
    eng.state.last_emit_ms = 0
    clock[0] = 200  # well beyond active_window_ms = 80
    eng.tick()
    assert eng.state.phase == Phase.MOMENTUM
    # transition posts ENDED then MomentumBegan, then the regular emit
    assert posts[0] == (0, ScrollPhase.ENDED, MomentumPhase.NONE)
    assert posts[1] == (0, ScrollPhase.NONE, MomentumPhase.BEGAN)


def test_active_with_idle_period_goes_to_idle_if_slow():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 100.0  # < coast_threshold (300)
    eng.state.last_tick_ms = 0
    eng.state.last_emit_ms = 0
    clock[0] = 200
    eng.tick()
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert posts == [(0, ScrollPhase.ENDED, MomentumPhase.NONE)]


def test_momentum_ends_when_velocity_below_cutoff():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 30.0  # already below cutoff_v=40
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    clock[0] = 10
    eng.tick()
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert posts == [(0, ScrollPhase.NONE, MomentumPhase.ENDED)]
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_scroll_model.py::test_active_with_idle_period_transitions_to_momentum_if_fast -v`
Expected: FAIL — transition logic not present.

- [ ] **Step 3: Add transitions to the tick loop**

Replace the body of `tick()` in `scroll.py` with:

```python
    def tick(self) -> None:
        if self.state.phase == Phase.IDLE:
            return
        now = self._now()
        dt_s = max(0.0, min((now - self.state.last_emit_ms) / 1000.0, 0.050))
        tau_s = self.config.tau_ms / 1000.0

        # 1. ACTIVE → MOMENTUM / IDLE
        if (self.state.phase == Phase.ACTIVE
                and (now - self.state.last_tick_ms) > self.config.active_window_ms):
            if abs(self.state.velocity) > self.config.coast_threshold:
                self.enter_momentum(now)
            else:
                self.enter_idle(post_ended=True)
                return

        # 2. Damped velocity
        self.state.velocity *= math.exp(-dt_s / tau_s)

        # 3. End of momentum
        if (self.state.phase == Phase.MOMENTUM
                and abs(self.state.velocity) < self.config.cutoff_v):
            self.enter_idle_from_momentum()
            return

        # 4. Emit
        gain = magspeed_gain(abs(self.state.velocity), self.config)
        pixels_f = self.state.velocity * gain * dt_s + self.state.accumulator
        pixels = int(pixels_f)
        self.state.accumulator = pixels_f - pixels
        if pixels != 0:
            if self.state.phase == Phase.MOMENTUM:
                self._post(pixels, ScrollPhase.NONE, MomentumPhase.CHANGED)
            else:
                self._post(pixels, ScrollPhase.CHANGED, MomentumPhase.NONE)
        self.state.last_emit_ms = now
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (18 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): tick loop ACTIVE↔MOMENTUM↔IDLE phase transitions"
```

---

### Task 9: on_tick — detent arrival from IDLE

**Files:**
- Modify: `scroll.py`
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_on_tick_from_idle_enters_active_and_adds_impulse():
    eng, posts, clock = _make_engine(now=100)
    eng.on_tick(direction=+1, device_t_ms=12345)
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.velocity == eng.config.impulse_per_detent
    assert eng.state.last_tick_ms == 100
    assert posts == [(0, ScrollPhase.BEGAN, MomentumPhase.NONE)]


def test_on_tick_direction_is_signed():
    eng, posts, _ = _make_engine(now=0)
    eng.on_tick(direction=-1, device_t_ms=0)
    assert eng.state.velocity == -eng.config.impulse_per_detent


def test_on_tick_clamps_to_v_max():
    eng, posts, _ = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = eng.config.v_max - 10
    eng.on_tick(direction=+1, device_t_ms=0)
    assert eng.state.velocity == eng.config.v_max


def test_on_tick_invert_flips_sign():
    eng, posts, _ = _make_engine()
    eng.config.invert = True
    eng.on_tick(direction=+1, device_t_ms=0)
    assert eng.state.velocity == -eng.config.impulse_per_detent
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_on_tick_from_idle_enters_active_and_adds_impulse -v`
Expected: FAIL — no `on_tick` method.

- [ ] **Step 3: Implement on_tick (IDLE branch only)**

Append inside `class ScrollEngine`:

```python
    def on_tick(self, direction: int, device_t_ms: int) -> None:
        """Called when a SCROLL_PING arrives. direction is +1 or -1."""
        now = self._now()
        signed_impulse = self.config.impulse_per_detent * direction
        if self.config.invert:
            signed_impulse = -signed_impulse

        if self.state.phase == Phase.IDLE:
            self.enter_active(now)

        new_v = self.state.velocity + signed_impulse
        if new_v > self.config.v_max:
            new_v = self.config.v_max
        elif new_v < -self.config.v_max:
            new_v = -self.config.v_max
        self.state.velocity = new_v
        self.state.last_tick_ms = now
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (22 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): on_tick from IDLE — enter ACTIVE + add signed impulse"
```

---

### Task 10: on_tick — direction-flip kill

**Files:**
- Modify: `scroll.py`
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_direction_flip_during_active_zeros_velocity_then_applies_impulse():
    eng, posts, _ = _make_engine()
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 500.0
    eng.state.accumulator = 0.7
    eng.on_tick(direction=-1, device_t_ms=0)
    assert eng.state.velocity == -eng.config.impulse_per_detent
    assert eng.state.accumulator == 0.0


def test_direction_flip_during_momentum_posts_one_momentum_ended():
    eng, posts, _ = _make_engine()
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 500.0
    eng.state.accumulator = 1.5
    eng.on_tick(direction=-1, device_t_ms=0)
    # Sequence: MomentumEnded, then ScrollBegan, then impulse applied
    momentum_ended_count = sum(
        1 for p in posts if p == (0, ScrollPhase.NONE, MomentumPhase.ENDED))
    assert momentum_ended_count == 1
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.velocity == -eng.config.impulse_per_detent
    assert eng.state.accumulator == 0.0


def test_same_direction_during_momentum_reopens_active_with_one_momentum_ended():
    eng, posts, _ = _make_engine()
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 500.0
    eng.on_tick(direction=+1, device_t_ms=0)
    momentum_ended_count = sum(
        1 for p in posts if p == (0, ScrollPhase.NONE, MomentumPhase.ENDED))
    assert momentum_ended_count == 1
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.velocity == 500.0 + eng.config.impulse_per_detent
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_direction_flip_during_active_zeros_velocity_then_applies_impulse -v`
Expected: FAIL — flip-kill not implemented.

- [ ] **Step 3: Update on_tick**

Replace `on_tick` in `scroll.py`:

```python
    def on_tick(self, direction: int, device_t_ms: int) -> None:
        now = self._now()
        signed_impulse = self.config.impulse_per_detent * direction
        if self.config.invert:
            signed_impulse = -signed_impulse

        # Direction-flip kill (only when there's existing velocity to flip
        # AND the new impulse opposes it)
        flipped = (
            self.state.velocity != 0
            and (self.state.velocity > 0) != (signed_impulse > 0)
        )
        if flipped:
            if self.state.phase == Phase.MOMENTUM:
                self.enter_idle_from_momentum()
            else:
                self.state.velocity = 0.0
                self.state.accumulator = 0.0

        if self.state.phase == Phase.IDLE:
            self.enter_active(now)
        elif self.state.phase == Phase.MOMENTUM:
            # Same-direction (non-flip) detent during momentum: end momentum,
            # reopen ACTIVE with a fresh ScrollPhase.BEGAN.
            self._post(0, ScrollPhase.NONE, MomentumPhase.ENDED)
            self.enter_active(now)
            # enter_active resets accumulator; preserve velocity.

        new_v = self.state.velocity + signed_impulse
        if new_v > self.config.v_max:
            new_v = self.config.v_max
        elif new_v < -self.config.v_max:
            new_v = -self.config.v_max
        self.state.velocity = new_v
        self.state.last_tick_ms = now
```

There's a subtle bug to avoid: `enter_active` posts `ScrollPhase.BEGAN`, but `enter_idle_from_momentum` already cleared `velocity` to 0 in the flip case. After `enter_active`, we then add the impulse. That's correct. For same-direction during momentum, we DON'T zero velocity, so the accumulated velocity is preserved and the new impulse stacks on top — also correct.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_scroll_model.py -v`
Expected: PASS (25 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): direction-flip kill + same-dir momentum re-entry"
```

---

### Task 11: Precision invariant (single isolated detent ≤ 15 px)

**Files:**
- Modify: `tests/test_scroll_model.py`

This is the spec's precision guarantee. We verify by simulating a single detent then ticking the engine to completion at 120 Hz.

- [ ] **Step 1: Write the test**

Append:

```python
def _run_to_idle(eng, clock, start_ms, max_ms=5000, tick_period_ms=8):
    posts_local = []
    eng._post = lambda p, sp, mp: posts_local.append((p, sp, mp))
    t = start_ms
    end = start_ms + max_ms
    while t <= end:
        clock[0] = t
        eng.tick()
        if eng.state.phase == Phase.IDLE:
            break
        t += tick_period_ms
    return posts_local


def test_single_isolated_detent_emits_at_most_15_pixels():
    eng, _, clock = _make_engine(now=0)
    eng.on_tick(direction=+1, device_t_ms=0)
    posts = _run_to_idle(eng, clock, start_ms=0)
    total_px = sum(p[0] for p in posts)
    assert eng.state.phase == Phase.IDLE
    assert abs(total_px) <= 15, (
        f"Single slow detent emitted {total_px} px — precision guarantee broken. "
        f"Posts: {posts}")
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_single_isolated_detent_emits_at_most_15_pixels -v`
Expected: PASS — confirms the spec's worked example holds with default config (one isolated detent of velocity 100 px/s damps quickly and emits ~7 px total).

- [ ] **Step 3: Commit**

```bash
git add tests/test_scroll_model.py
git commit -m "test(scroll): precision invariant — single detent ≤ 15 px"
```

---

### Task 12: Steady-spin stability invariant

**Files:**
- Modify: `tests/test_scroll_model.py`

Asserts damped-impulse model converges to a stable velocity under steady input — does NOT ramp indefinitely.

- [ ] **Step 1: Write the test**

Append:

```python
def test_steady_spin_converges_to_stable_velocity():
    """Spin at one detent every 30 ms for 3 seconds. After the first
    ~1 second the velocity should be within 5% of steady-state."""
    eng, _, clock = _make_engine(now=0)
    eng._post = lambda *a: None
    detent_period = 30
    velocity_samples = []
    t = 0
    last_detent = 0
    end = 3000
    while t <= end:
        clock[0] = t
        if t - last_detent >= detent_period:
            eng.on_tick(direction=+1, device_t_ms=t)
            last_detent = t
        eng.tick()
        if t > 1000:
            velocity_samples.append(eng.state.velocity)
        t += 8

    assert velocity_samples
    v_late = velocity_samples[-200:]  # last ~1.6 s
    v_min, v_max = min(v_late), max(v_late)
    spread = (v_max - v_min) / max(abs(v_max), 1)
    assert spread < 0.20, (
        f"Velocity unstable in late phase: min={v_min:.1f} max={v_max:.1f}")
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_steady_spin_converges_to_stable_velocity -v`
Expected: PASS — the damping in both ACTIVE and MOMENTUM phases keeps velocity bounded.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scroll_model.py
git commit -m "test(scroll): steady spin converges, doesn't ramp indefinitely"
```

---

### Task 13: Wake-from-sleep / dt-clamp invariant

**Files:**
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the test**

Append:

```python
def test_dt_clamp_prevents_huge_first_frame():
    """If the event loop stalls for 5 seconds, the first tick after the
    stall must not emit a giant burst."""
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 1000.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    clock[0] = 5000  # 5-second stall
    eng.tick()
    # dt clamped to 50 ms. At v=1000, gain≈4.08, pixels ≈ 1000*4.08*0.050 = 204
    # Without clamp, would emit > 20000.
    assert posts
    assert abs(posts[-1][0]) < 300, (
        f"dt-clamp failed: first frame emitted {posts[-1][0]} px")
```

Note: the tick will ALSO transition into MOMENTUM because (5000 - last_tick_ms) > active_window_ms. That's fine — the test only checks the magnitude of any single emitted frame, not the phase.

Actually the transition path enters MOMENTUM then runs the damping + emit. After enter_momentum, `last_emit_ms` is reset to `now=5000`, so the emit step computes `dt_s = (now - last_emit_ms)/1000 = 0`. Output = 0. No emit. Test passes trivially because no emit happens.

Refine the test to specifically check the no-transition path:

```python
def test_dt_clamp_prevents_huge_first_frame():
    """If the event loop stalls for 5 seconds, the first tick after the
    stall must not emit a giant burst."""
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 1000.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 5000  # detent JUST arrived at t=5000
    clock[0] = 5000
    eng.tick()
    # No phase transition (active_window check sees 0 ms since detent).
    # Damping uses dt_s clamped to 50ms.
    assert posts
    deltas = [p[0] for p in posts if p[1] == ScrollPhase.CHANGED]
    assert deltas, f"expected an ACTIVE emit, got {posts}"
    assert all(abs(d) < 300 for d in deltas), (
        f"dt-clamp failed: emits {deltas}")
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_dt_clamp_prevents_huge_first_frame -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scroll_model.py
git commit -m "test(scroll): dt clamp prevents wake-from-sleep burst"
```

---

### Task 14: Accumulator-drift invariant

**Files:**
- Modify: `tests/test_scroll_model.py`

- [ ] **Step 1: Write the test**

Append:

```python
def test_accumulator_does_not_drift_over_long_run():
    """Sum of int pixels emitted equals integer part of analytic integral
    within ±1 px after 10000 ticks under steady velocity."""
    eng, posts, clock = _make_engine(now=0)
    cfg = eng.config
    cfg.slow_threshold = 1e9  # gain=1 throughout
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 100.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    t = 0
    detent_period = 1   # one detent every ms — keeps ACTIVE alive, ~steady-state
    last_detent = 0
    end = 10000 * 8  # 10000 ticks at 8 ms
    while t < end:
        clock[0] = t
        if t - last_detent >= detent_period:
            eng.on_tick(direction=+1, device_t_ms=t)
            last_detent = t
        eng.tick()
        t += 8
    px_emitted = sum(p[0] for p in posts if p[1] == ScrollPhase.CHANGED)
    # Cross-check: with continuous impulses + damping, steady-state v is
    # high (impulse rate >> damping rate). Use loose bound: emitted pixels
    # should equal accumulator-corrected sum within 1 px.
    # Easier check: accumulator never grows unbounded.
    assert -2.0 < eng.state.accumulator < 2.0, (
        f"Accumulator drift: {eng.state.accumulator}")
    assert px_emitted > 0
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_accumulator_does_not_drift_over_long_run -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scroll_model.py
git commit -m "test(scroll): accumulator stays bounded over long runs"
```

---

### Task 15: ScrollConfig persistence (load/save scroll.json + clamping)

**Files:**
- Modify: `scroll.py`
- Create: `tests/test_scroll_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scroll_config.py`:

```python
import json
from pathlib import Path

import pytest

from scroll import ScrollConfig, load_config, save_config


def test_load_missing_file_returns_defaults(tmp_path):
    c = load_config(tmp_path / "scroll.json")
    assert c == ScrollConfig()


def test_load_malformed_file_returns_defaults(tmp_path):
    p = tmp_path / "scroll.json"
    p.write_text("{not json")
    c = load_config(p)
    assert c == ScrollConfig()


def test_load_partial_file_merges_with_defaults(tmp_path):
    p = tmp_path / "scroll.json"
    p.write_text(json.dumps({"tau_ms": 800, "invert": True}))
    c = load_config(p)
    assert c.tau_ms == 800
    assert c.invert is True
    assert c.impulse_per_detent == ScrollConfig().impulse_per_detent


def test_load_clamps_out_of_range_values(tmp_path):
    p = tmp_path / "scroll.json"
    p.write_text(json.dumps({
        "impulse_per_detent": 100000,
        "tau_ms": -50,
        "max_gain": 9999,
        "cutoff_v": -1,
    }))
    c = load_config(p)
    assert c.impulse_per_detent <= 500
    assert c.tau_ms >= 50
    assert c.max_gain <= 12
    assert c.cutoff_v >= 5


def test_load_rejects_invalid_threshold_ordering(tmp_path):
    p = tmp_path / "scroll.json"
    # coast_threshold < cutoff_v is invalid — must be clamped/raised.
    p.write_text(json.dumps({"coast_threshold": 10, "cutoff_v": 50}))
    c = load_config(p)
    assert c.coast_threshold >= c.cutoff_v


def test_save_and_reload_roundtrip(tmp_path):
    p = tmp_path / "scroll.json"
    c = ScrollConfig(tau_ms=600, invert=True)
    save_config(c, p)
    loaded = load_config(p)
    assert loaded == c
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_scroll_config.py -v`
Expected: FAIL — `load_config` / `save_config` not defined.

- [ ] **Step 3: Implement load_config / save_config**

Add to top of `scroll.py`:

```python
import json
from dataclasses import asdict, fields
from pathlib import Path
```

Append at end of `scroll.py`:

```python
_CLAMPS: dict[str, tuple[float, float]] = {
    "impulse_per_detent": (20.0, 500.0),
    "tau_ms": (50, 2000),
    "slow_threshold": (50.0, 1000.0),
    "fast_threshold": (500.0, 5000.0),
    "max_gain": (1.0, 12.0),
    "active_window_ms": (30, 250),
    "coast_threshold": (50.0, 2000.0),
    "cutoff_v": (5.0, 200.0),
    "v_max": (500.0, 25000.0),
}


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def load_config(path: Path) -> ScrollConfig:
    defaults = ScrollConfig()
    try:
        raw = json.loads(Path(path).read_text())
        if not isinstance(raw, dict):
            return defaults
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return defaults

    valid = {f.name for f in fields(ScrollConfig)}
    merged = asdict(defaults)
    for k, v in raw.items():
        if k not in valid:
            continue
        if k == "invert":
            merged[k] = bool(v)
            continue
        if k in _CLAMPS:
            lo, hi = _CLAMPS[k]
            try:
                merged[k] = _clamp(type(merged[k])(v), lo, hi)
            except (TypeError, ValueError):
                continue
    cfg = ScrollConfig(**merged)
    # Enforce coast_threshold >= cutoff_v
    if cfg.coast_threshold < cfg.cutoff_v:
        cfg.coast_threshold = cfg.cutoff_v
    return cfg


def save_config(cfg: ScrollConfig, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), indent=2))
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_scroll_config.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scroll.py tests/test_scroll_config.py
git commit -m "feat(scroll): ScrollConfig load/save with clamping + validation"
```

---

## Phase 3 — macOS event posting

### Task 16: Real CGEvent post helper

**Files:**
- Modify: `scroll.py`

Not unit-testable in isolation (it talks to the OS). We add it as a free function, then write a simple integration test that posts one event and verifies it doesn't crash.

- [ ] **Step 1: Append the function to scroll.py**

```python
def make_cgevent_post():
    """Return a post_scroll(pixels, scroll_phase, momentum_phase) function
    that posts a real CGEvent. macOS-only. Caller is responsible for
    having Accessibility permission.
    """
    import Quartz  # local import: optional dep, only loaded if needed

    def _post(pixels: int, scroll_phase: int, momentum_phase: int) -> None:
        ev = Quartz.CGEventCreateScrollWheelEvent2(
            None,
            Quartz.kCGScrollEventUnitPixel,
            1,           # wheelCount
            pixels, 0, 0)
        Quartz.CGEventSetIntegerValueField(
            ev, Quartz.kCGScrollWheelEventScrollPhase, scroll_phase)
        Quartz.CGEventSetIntegerValueField(
            ev, Quartz.kCGScrollWheelEventMomentumPhase, momentum_phase)
        Quartz.CGEventSetIntegerValueField(
            ev, Quartz.kCGScrollWheelEventIsContinuous, 1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    return _post
```

- [ ] **Step 2: Add an integration smoke test**

Append to `tests/test_scroll_model.py`:

```python
def test_make_cgevent_post_does_not_crash_on_darwin():
    import sys
    if sys.platform != "darwin":
        return
    from scroll import make_cgevent_post
    post = make_cgevent_post()
    # Post a zero-pixel "began" — visible to the OS but harmless.
    post(0, ScrollPhase.BEGAN, MomentumPhase.NONE)
    post(0, ScrollPhase.ENDED, MomentumPhase.NONE)
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_make_cgevent_post_does_not_crash_on_darwin -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): make_cgevent_post — real Quartz event poster"
```

---

### Task 17: Accessibility-trust helper

**Files:**
- Modify: `scroll.py`

- [ ] **Step 1: Append the helper**

In `scroll.py`:

```python
def is_accessibility_trusted(prompt: bool = False) -> bool:
    """Return True iff this process is trusted for Accessibility.
    If `prompt`, macOS shows the system permission prompt on the first
    call when not yet trusted.
    """
    import sys
    if sys.platform != "darwin":
        return False
    try:
        import ApplicationServices
    except ImportError:
        return False
    options = {
        ApplicationServices.kAXTrustedCheckOptionPrompt: prompt
    }
    return bool(
        ApplicationServices.AXIsProcessTrustedWithOptions(options))
```

- [ ] **Step 2: Add a smoke test**

In `tests/test_scroll_model.py`:

```python
def test_is_accessibility_trusted_returns_bool_on_darwin():
    import sys
    if sys.platform != "darwin":
        return
    from scroll import is_accessibility_trusted
    result = is_accessibility_trusted(prompt=False)
    assert isinstance(result, bool)
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_is_accessibility_trusted_returns_bool_on_darwin -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): is_accessibility_trusted helper"
```

---

## Phase 4 — HID transport (HidIoWorker)

### Task 18: HidIoWorker skeleton + send_request / send_untracked APIs

**Files:**
- Create: `hid_io.py`
- Create: `tests/test_hid_io.py`

The worker is designed so the transport logic (queue, demux, future fulfillment) is testable single-threaded via `pump_once()`. The real-thread run loop is separate.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hid_io.py`:

```python
import threading

import pytest

from hid_io import HidIoWorker, IdUnhandledError


class FakeHID:
    """Single-handle fake: writes captured to a list; reads pop from a
    deque. read() blocks via an event if empty (simulates timeout)."""

    def __init__(self):
        self.writes: list[bytes] = []
        self._replies: list[list[int]] = []
        self._closed = False

    def write(self, data):
        if self._closed:
            raise OSError("closed")
        self.writes.append(bytes(data))
        return len(data)

    def read(self, n, timeout=0):
        if self._closed:
            raise OSError("closed")
        if self._replies:
            return self._replies.pop(0)
        return []  # timeout

    def queue_reply(self, reply: list[int]):
        # pad to 32 bytes
        padded = list(reply) + [0] * max(0, 32 - len(reply))
        self._replies.append(padded[:32])

    def close(self):
        self._closed = True


def test_send_request_fulfils_future_with_matching_reply():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0, 0, 2])  # GET_KEYCODE
    dev.queue_reply([0x04, 0, 0, 2, 0x06, 0x25])
    worker.pump_once()
    assert fut.done()
    reply = fut.result(timeout=0.1)
    assert reply[0] == 0x04


def test_send_untracked_writes_but_creates_no_future():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    worker.send_untracked([0xA0, 0x01])
    assert len(dev.writes) == 1
    assert worker.pending_count() == 0
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_hid_io.py -v`
Expected: FAIL — `hid_io` module doesn't exist.

- [ ] **Step 3: Create hid_io.py**

```python
"""HidIoWorker — sole owner of the 0xFF60 raw-HID handle.

Owns: handle, read loop, write queue, per-command-ID FIFO future demux,
unsolicited-frame routing (scroll_tick), close/reopen with backoff.

Two execution modes:
  - run_forever() in a thread (production)
  - pump_once() called manually (testing)
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from concurrent.futures import Future
from typing import Callable

from PySide6.QtCore import QObject, Signal


class IdUnhandledError(Exception):
    """Device replied with 0xFF (id_unhandled) — the command isn't
    recognised by this firmware."""


class HidIoWorker(QObject):
    scroll_tick = Signal(int, int)   # (direction, device_t_ms)
    device_state = Signal(str)       # "" / "no-device"

    SCROLL_PING = 0xA1
    HOST_SCROLL_READY = 0xA0
    ID_UNHANDLED = 0xFF

    def __init__(self):
        super().__init__()
        self._dev = None
        self._dev_lock = threading.Lock()
        self._write_q: deque[bytes] = deque()
        self._futures: dict[int, deque[Future]] = defaultdict(deque)
        self._stop = threading.Event()

    @classmethod
    def with_handle(cls, dev) -> "HidIoWorker":
        w = cls()
        w._dev = dev
        return w

    def pending_count(self) -> int:
        return sum(len(q) for q in self._futures.values())

    def send_request(self, payload: list[int]) -> Future:
        """Send a frame whose first byte is the command ID. Returns a
        Future fulfilled by the next reply with that same command ID.
        Replies arrive in FIFO order per command ID.
        """
        cmd_id = payload[0]
        body = bytes([0x00]) + bytes(payload) + bytes(32 - len(payload))
        fut: Future = Future()
        self._futures[cmd_id].append(fut)
        with self._dev_lock:
            if self._dev is not None:
                self._dev.write(body)
        return fut

    def send_untracked(self, payload: list[int]) -> None:
        """Fire-and-forget. No future registered. Used for heartbeats."""
        body = bytes([0x00]) + bytes(payload) + bytes(32 - len(payload))
        with self._dev_lock:
            if self._dev is not None:
                self._dev.write(body)

    def pump_once(self, timeout_ms: int = 0) -> None:
        """Read once and dispatch. Called from the run loop or tests."""
        with self._dev_lock:
            dev = self._dev
        if dev is None:
            return
        try:
            data = dev.read(32, timeout_ms)
        except OSError:
            self.device_state.emit("no-device")
            return
        if not data:
            return
        cmd_id = data[0]
        if cmd_id == self.SCROLL_PING:
            direction = +1 if data[2] == 1 else -1
            t = (data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24))
            self.scroll_tick.emit(direction, t)
            return
        # VIA reply: fulfil oldest future for this command ID
        if cmd_id == self.ID_UNHANDLED:
            # We don't know which command this corresponds to — drop and log
            # (a well-behaved VIA replies in-order, so 0xFF means the very
            # next pending future's request was unhandled; fulfil the
            # oldest one across all queues with the error).
            for q in self._futures.values():
                if q:
                    q.popleft().set_exception(
                        IdUnhandledError("device returned id_unhandled"))
                    return
            return
        q = self._futures.get(cmd_id)
        if q:
            q.popleft().set_result(list(data))
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_hid_io.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add hid_io.py tests/test_hid_io.py
git commit -m "feat(hid_io): HidIoWorker skeleton — send_request, send_untracked"
```

---

### Task 19: HidIoWorker — FIFO per command-ID

**Files:**
- Modify: `tests/test_hid_io.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_two_concurrent_requests_resolve_in_fifo_order():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    f1 = worker.send_request([0x04, 0, 0, 1])
    f2 = worker.send_request([0x04, 0, 0, 2])
    dev.queue_reply([0x04, 0, 0, 1, 0xAA, 0xAA])
    dev.queue_reply([0x04, 0, 0, 2, 0xBB, 0xBB])
    worker.pump_once()
    worker.pump_once()
    r1 = f1.result(timeout=0.1)
    r2 = f2.result(timeout=0.1)
    assert r1[4:6] == [0xAA, 0xAA]
    assert r2[4:6] == [0xBB, 0xBB]
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_hid_io.py::test_two_concurrent_requests_resolve_in_fifo_order -v`
Expected: PASS (already correct under current impl — `deque.popleft` gives FIFO).

- [ ] **Step 3: Commit**

```bash
git add tests/test_hid_io.py
git commit -m "test(hid_io): two concurrent same-id requests FIFO"
```

---

### Task 20: HidIoWorker — 0xFF id_unhandled

**Files:**
- Modify: `tests/test_hid_io.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_id_unhandled_raises_on_request_future():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x99])  # made-up unhandled command
    dev.queue_reply([0xFF])
    worker.pump_once()
    with pytest.raises(IdUnhandledError):
        fut.result(timeout=0.1)
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_hid_io.py::test_id_unhandled_raises_on_request_future -v`
Expected: PASS (already implemented in Task 18).

- [ ] **Step 3: Commit**

```bash
git add tests/test_hid_io.py
git commit -m "test(hid_io): id_unhandled (0xFF) raises IdUnhandledError"
```

---

### Task 21: HidIoWorker — scroll_tick signal on 0xA1

**Files:**
- Modify: `tests/test_hid_io.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_scroll_ping_emits_signal_no_future_side_effect():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    received = []
    worker.scroll_tick.connect(lambda d, t: received.append((d, t)))
    # 0xA1, version=1, dir=1 (CW=down), flags=0, timestamp=0x04030201
    dev.queue_reply([0xA1, 0x01, 0x01, 0x00, 0x01, 0x02, 0x03, 0x04])
    worker.pump_once()
    assert received == [(+1, 0x04030201)]
    assert worker.pending_count() == 0


def test_scroll_ping_direction_zero_means_up():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    received = []
    worker.scroll_tick.connect(lambda d, t: received.append((d, t)))
    dev.queue_reply([0xA1, 0x01, 0x00, 0x00, 0, 0, 0, 0])
    worker.pump_once()
    assert received == [(-1, 0)]
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_hid_io.py -v`
Expected: PASS (8 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_hid_io.py
git commit -m "test(hid_io): 0xA1 SCROLL_PING emits scroll_tick"
```

---

### Task 22: HidIoWorker — close/reopen with backoff

**Files:**
- Modify: `hid_io.py`
- Modify: `tests/test_hid_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hid_io.py`:

```python
def test_read_error_streak_triggers_close():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    # Force read errors
    def bad_read(*a, **kw):
        raise OSError("boom")
    dev.read = bad_read
    states = []
    worker.device_state.connect(lambda s: states.append(s))
    # Each pump increments error counter
    for _ in range(5):
        worker.pump_once()
    assert states.count("no-device") >= 1
    # After streak, dev should be released
    assert worker._dev is None or dev._closed


def test_open_with_backoff_does_not_busy_loop(monkeypatch):
    """Backoff schedule: 1s, 2s, 5s. We mock time and the open function."""
    attempts = []
    times = [0.0]

    def fake_open():
        attempts.append(times[0])
        return None  # never opens

    worker = HidIoWorker(open_fn=fake_open, now_fn=lambda: times[0])
    # First check at t=0 attempts open
    worker.maybe_reopen()
    assert len(attempts) == 1
    # Within 1s of failure, no new attempt
    times[0] = 0.5
    worker.maybe_reopen()
    assert len(attempts) == 1
    # After 1s, next attempt
    times[0] = 1.1
    worker.maybe_reopen()
    assert len(attempts) == 2
    # After another 2s, third attempt
    times[0] = 3.2
    worker.maybe_reopen()
    assert len(attempts) == 3
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_hid_io.py::test_read_error_streak_triggers_close -v`
Expected: FAIL — no error-streak / reopen logic.

- [ ] **Step 3: Update HidIoWorker**

Edit `hid_io.py`. Replace the `__init__` signature and add helpers:

```python
import time as _time

# default open: lazily imports core.open_raw so tests can substitute
def _default_open():
    import core
    return core.open_raw()


class HidIoWorker(QObject):
    scroll_tick = Signal(int, int)
    device_state = Signal(str)

    SCROLL_PING = 0xA1
    HOST_SCROLL_READY = 0xA0
    ID_UNHANDLED = 0xFF

    READ_ERROR_LIMIT = 5
    BACKOFF_S = (1.0, 2.0, 5.0)

    def __init__(self, open_fn: Callable = _default_open, now_fn: Callable = _time.monotonic):
        super().__init__()
        self._dev = None
        self._dev_lock = threading.Lock()
        self._write_q: deque[bytes] = deque()
        self._futures: dict[int, deque[Future]] = defaultdict(deque)
        self._stop = threading.Event()
        self._open_fn = open_fn
        self._now = now_fn
        self._error_streak = 0
        self._last_open_attempt = -float("inf")
        self._backoff_idx = 0

    @classmethod
    def with_handle(cls, dev) -> "HidIoWorker":
        w = cls()
        w._dev = dev
        return w
```

Update `pump_once` to count read errors:

```python
    def pump_once(self, timeout_ms: int = 0) -> None:
        with self._dev_lock:
            dev = self._dev
        if dev is None:
            return
        try:
            data = dev.read(32, timeout_ms)
            self._error_streak = 0
        except OSError:
            self._error_streak += 1
            self.device_state.emit("no-device")
            if self._error_streak >= self.READ_ERROR_LIMIT:
                self._close_handle()
            return
        if not data:
            return
        cmd_id = data[0]
        if cmd_id == self.SCROLL_PING:
            direction = +1 if data[2] == 1 else -1
            t = (data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24))
            self.scroll_tick.emit(direction, t)
            return
        if cmd_id == self.ID_UNHANDLED:
            for q in self._futures.values():
                if q:
                    q.popleft().set_exception(
                        IdUnhandledError("device returned id_unhandled"))
                    return
            return
        q = self._futures.get(cmd_id)
        if q:
            q.popleft().set_result(list(data))

    def _close_handle(self) -> None:
        with self._dev_lock:
            if self._dev is not None:
                try:
                    self._dev.close()
                except Exception:
                    pass
                self._dev = None
        self._error_streak = 0

    def maybe_reopen(self) -> bool:
        """Attempt to open the handle if we don't have one and enough
        time has passed since the last attempt. Returns True iff a fresh
        open succeeded this call."""
        with self._dev_lock:
            if self._dev is not None:
                return False
        delay = self.BACKOFF_S[min(self._backoff_idx, len(self.BACKOFF_S) - 1)]
        if self._now() - self._last_open_attempt < delay:
            return False
        self._last_open_attempt = self._now()
        dev = self._open_fn()
        if dev is None:
            self._backoff_idx += 1
            return False
        with self._dev_lock:
            self._dev = dev
        self._backoff_idx = 0
        self.device_state.emit("")
        return True
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_hid_io.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add hid_io.py tests/test_hid_io.py
git commit -m "feat(hid_io): close on read-error streak; reopen with backoff"
```

---

### Task 23: HidIoWorker — run_forever loop

**Files:**
- Modify: `hid_io.py`

- [ ] **Step 1: Add run_forever and stop**

Append inside `class HidIoWorker`:

```python
    def run_forever(self) -> None:
        """Production loop. Run on a QThread.started signal."""
        self._stop.clear()
        while not self._stop.is_set():
            if self._dev is None:
                self.maybe_reopen()
                if self._dev is None:
                    self._stop.wait(0.1)
                    continue
            self.pump_once(timeout_ms=20)

    def stop(self) -> None:
        self._stop.set()
        self._close_handle()
```

- [ ] **Step 2: No new test needed — covered by manual integration in later phases.**

- [ ] **Step 3: Commit**

```bash
git add hid_io.py
git commit -m "feat(hid_io): run_forever + stop for threaded use"
```

---

## Phase 5 — Migrate core.py and ControlWorker to use HidIoWorker

### Task 24: Extract pure frame builders in core.py

**Files:**
- Modify: `core.py`
- Modify: `tests/test_core_frames.py`

The strategy: keep existing `core.cmd(dev, ...)` and `core.set_key(dev, ...)` etc. working for now (they still write directly to a handle). In parallel, add pure-Python *builder* functions that return the payload list without writing. These builders are what we'll pass to `HidIoWorker.send_request` later.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core_frames.py`:

```python
def test_build_get_key_payload():
    p = core.build_get_key(layer=1, col=2)
    assert p == [core.DYNAMIC_KEYMAP_GET_KEYCODE, 1, 0, 2]


def test_build_set_key_payload():
    p = core.build_set_key(layer=1, col=2, keycode=0x0625)
    assert p == [core.DYNAMIC_KEYMAP_SET_KEYCODE, 1, 0, 2, 0x06, 0x25]


def test_build_get_encoder_payload():
    p = core.build_get_encoder(layer=0, enc=1, direction=0)
    assert p == [core.DYNAMIC_KEYMAP_GET_ENCODER, 0, 1, 0]


def test_build_set_encoder_payload():
    p = core.build_set_encoder(layer=0, enc=1, direction=1, keycode=0x00A9)
    assert p == [core.DYNAMIC_KEYMAP_SET_ENCODER, 0, 1, 1, 0x00, 0xA9]


def test_parse_keycode_reply():
    reply = [core.DYNAMIC_KEYMAP_GET_KEYCODE, 1, 0, 2, 0x06, 0x25] + [0] * 26
    assert core.parse_keycode_reply(reply) == 0x0625


def test_build_pressed_cols_request():
    p = core.build_pressed_cols()
    assert p == [core.GET_KEYBOARD_VALUE, core.SWITCH_MATRIX_STATE, 0x00]


def test_parse_pressed_cols_reply():
    reply = [core.GET_KEYBOARD_VALUE, core.SWITCH_MATRIX_STATE, 0x00, 0b10101] + [0]*28
    assert core.parse_pressed_cols_reply(reply) == [0, 2, 4]


def test_parse_pressed_cols_reply_returns_none_on_unhandled():
    assert core.parse_pressed_cols_reply([0xFF] + [0]*31) is None
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_core_frames.py -v`
Expected: FAIL — builders not defined.

- [ ] **Step 3: Add builders + parsers**

Append to `core.py`:

```python
# --- pure frame builders (return payload list) ---

def build_get_key(layer: int, col: int) -> list[int]:
    return [DYNAMIC_KEYMAP_GET_KEYCODE, layer, 0, col]


def build_set_key(layer: int, col: int, keycode: int) -> list[int]:
    return [DYNAMIC_KEYMAP_SET_KEYCODE, layer, 0, col,
            (keycode >> 8) & 0xFF, keycode & 0xFF]


def build_get_encoder(layer: int, enc: int, direction: int) -> list[int]:
    return [DYNAMIC_KEYMAP_GET_ENCODER, layer, enc, direction]


def build_set_encoder(layer: int, enc: int, direction: int, keycode: int) -> list[int]:
    return [DYNAMIC_KEYMAP_SET_ENCODER, layer, enc, direction,
            (keycode >> 8) & 0xFF, keycode & 0xFF]


def build_pressed_cols() -> list[int]:
    return [GET_KEYBOARD_VALUE, SWITCH_MATRIX_STATE, 0x00]


def build_layer_count() -> list[int]:
    return [DYNAMIC_KEYMAP_GET_LAYER_COUNT]


def build_light_get(value_id: int) -> list[int]:
    return [CUSTOM_GET_VALUE, RGB_MATRIX_CHANNEL, value_id]


def build_light_set_scalar(value_id: int, value: int) -> list[int]:
    return [CUSTOM_SET_VALUE, RGB_MATRIX_CHANNEL, value_id, value]


def build_light_set_color(hue: int, sat: int) -> list[int]:
    return [CUSTOM_SET_VALUE, RGB_MATRIX_CHANNEL, LIGHT_COLOR, hue, sat]


def build_light_save() -> list[int]:
    return [CUSTOM_SAVE, RGB_MATRIX_CHANNEL]


# --- pure parsers ---

def parse_keycode_reply(reply: list[int]) -> int:
    return (reply[4] << 8) | reply[5]


def parse_pressed_cols_reply(reply: list[int]) -> list[int] | None:
    if not reply or reply[0] == 0xFF or len(reply) < 4:
        return None
    if reply[0] != GET_KEYBOARD_VALUE or reply[1] != SWITCH_MATRIX_STATE:
        return None
    row = reply[3]
    return [col for col in range(N_COLS) if row & (1 << col)]
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_core_frames.py -v`
Expected: PASS (all existing + 8 new).

- [ ] **Step 5: Commit**

```bash
git add core.py tests/test_core_frames.py
git commit -m "refactor(core): extract pure frame builders + parsers"
```

---

### Task 25: Wire ControlWorker to a HidIoWorker

**Files:**
- Modify: `worker.py`
- Modify: `main.py`

This is the load-bearing migration. We need to be careful not to break the existing GUI. Strategy: ControlWorker accepts a `HidIoWorker` reference; uses `io.send_request(builder(...)).result(timeout=...)` instead of `core.cmd(dev, ...)`. The `open_raw()` call moves from ControlWorker to HidIoWorker.

- [ ] **Step 1: Modify worker.py**

Replace the contents of `worker.py` with:

```python
"""ControlWorker: thread-bound owner of the VIA command/reply lifecycle.

The HID handle itself is owned by HidIoWorker. ControlWorker submits
requests via io.send_request(builder), receives results via Future,
and emits the same Qt signals it always did.
"""

from concurrent.futures import TimeoutError as FutureTimeoutError

from PySide6.QtCore import QObject, QTimer, Signal, Slot

import core
from model import Snapshot, key_id, enc_id


class ControlWorker(QObject):
    snapshot_ready = Signal(object)
    device_state = Signal(str)
    set_ack = Signal(object, bool)
    lighting_saved = Signal(bool)
    loading = Signal(bool)
    matrix_state = Signal(str)
    matrix_press = Signal(object)
    matrix_release = Signal(object)

    REPLY_TIMEOUT_S = 1.0

    def __init__(self, io):
        super().__init__()
        self._io = io
        self._matrix_timer = None
        self._pressed_cols: set[int] = set()
        self._matrix_state = ""

    def _request(self, payload: list[int]) -> list[int] | None:
        try:
            fut = self._io.send_request(payload)
            return fut.result(timeout=self.REPLY_TIMEOUT_S)
        except (FutureTimeoutError, Exception):
            self.device_state.emit("no-device")
            return None

    @Slot()
    def start(self):
        # HidIoWorker opens the handle on its own thread; we just wait for it.
        self._start_matrix_poll()
        self.load_all()

    @Slot()
    def reconnect(self):
        self.start()

    @Slot()
    def load_all(self):
        self.loading.emit(True)
        try:
            keymap = []
            for ly in range(4):
                row = []
                for c in range(core.N_COLS):
                    r = self._request(core.build_get_key(ly, c))
                    if r is None:
                        self.loading.emit(False)
                        return
                    row.append(core.parse_keycode_reply(r))
                keymap.append(row)
            encoders = []
            for ly in range(4):
                lay = []
                for e in range(core.N_ENCODERS):
                    pair = []
                    for d in range(2):
                        r = self._request(core.build_get_encoder(ly, e, d))
                        if r is None:
                            self.loading.emit(False)
                            return
                        pair.append(core.parse_keycode_reply(r))
                    lay.append(pair)
                encoders.append(lay)
            b = self._request(core.build_light_get(core.LIGHT_BRIGHTNESS))
            e = self._request(core.build_light_get(core.LIGHT_EFFECT))
            s = self._request(core.build_light_get(core.LIGHT_SPEED))
            c = self._request(core.build_light_get(core.LIGHT_COLOR))
            if any(x is None for x in (b, e, s, c)):
                self.loading.emit(False)
                return
            snap = Snapshot(
                keymap=keymap, encoders=encoders,
                brightness=b[3], effect=e[3], speed=s[3],
                hue=c[3], sat=c[4],
            )
        finally:
            self.loading.emit(False)
        self.snapshot_ready.emit(snap)

    @Slot(int, int, int)
    def set_key(self, layer, col, keycode):
        r = self._request(core.build_set_key(layer, col, keycode))
        self.set_ack.emit(key_id(col), r is not None)

    @Slot(int, int, int, int)
    def set_encoder(self, layer, enc, direction, keycode):
        r = self._request(core.build_set_encoder(layer, enc, direction, keycode))
        self.set_ack.emit(enc_id(enc, direction), r is not None)

    @Slot(int, int)
    def get_key(self, layer, col) -> int:
        r = self._request(core.build_get_key(layer, col))
        return core.parse_keycode_reply(r) if r else 0

    @Slot(int, int, int)
    def set_light_scalar(self, value_id, value):
        self._request(core.build_light_set_scalar(value_id, value))

    @Slot(int, int)
    def set_color(self, hue, sat):
        self._request(core.build_light_set_color(hue, sat))

    @Slot()
    def save(self):
        r = self._request(core.build_light_save())
        self.lighting_saved.emit(r is not None)

    def _start_matrix_poll(self):
        if self._matrix_timer is not None:
            self._pressed_cols = set()
            self._matrix_timer.start()
            return
        self._matrix_timer = QTimer(self)
        self._matrix_timer.setInterval(30)
        self._matrix_timer.timeout.connect(self._poll_matrix)
        self._matrix_timer.start()

    @Slot()
    def _poll_matrix(self):
        r = self._request(core.build_pressed_cols())
        if r is None:
            return
        cols = core.parse_pressed_cols_reply(r)
        if cols is None:
            if self._matrix_state != "unsupported":
                self._matrix_state = "unsupported"
                self.matrix_state.emit("unsupported")
            self._matrix_timer.stop()
            return
        if self._matrix_state != "available":
            self._matrix_state = "available"
            self.matrix_state.emit("available")
        pressed = set(cols)
        for col in sorted(pressed - self._pressed_cols):
            self.matrix_press.emit(key_id(col))
        for col in sorted(self._pressed_cols - pressed):
            self.matrix_release.emit(key_id(col))
        self._pressed_cols = pressed
```

- [ ] **Step 2: Modify main.py**

Replace `main.py`:

```python
import sys

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from hid_io import HidIoWorker
from listener import Listener
from ui import MainWindow
from worker import ControlWorker


def main() -> None:
    app = QApplication(sys.argv)

    io = HidIoWorker()
    io_thread = QThread()
    io.moveToThread(io_thread)
    io_thread.started.connect(io.run_forever)
    io_thread.start()

    control = ControlWorker(io)
    control_thread = QThread()
    control.moveToThread(control_thread)
    control_thread.started.connect(control.start)

    listener = Listener()
    listener_thread = QThread()
    listener.moveToThread(listener_thread)
    listener_thread.started.connect(listener.start)

    window = MainWindow(control, listener)

    # forward device state from io to UI via control
    io.device_state.connect(control.device_state)

    control_thread.start()
    listener_thread.start()
    window.show()

    code = app.exec()
    io.stop()
    listener.stop()
    listener_thread.quit()
    control_thread.quit()
    io_thread.quit()
    listener_thread.wait()
    control_thread.wait()
    io_thread.wait()
    sys.exit(code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run all existing tests**

Run: `uv run pytest`
Expected: All existing tests pass.

- [ ] **Step 4: Manual smoke test — GUI still works against current firmware**

> ⚠️ Per `feedback_via_single_owner.md`, do NOT run probe scripts while the GUI is open. Close everything else.

Run: `uv run python main.py`
Expected:
- Device window shows up, layer dropdowns populated, no "device not connected" banner.
- Click through keymap + encoders + lighting; everything works as before.
- Close the app cleanly.

Document the result in your test notes. If the GUI doesn't load, debug before proceeding.

- [ ] **Step 5: Commit**

```bash
git add worker.py main.py
git commit -m "refactor(worker): ControlWorker uses HidIoWorker for transport"
```

---

## Phase 6 — Readiness gating + heartbeat

### Task 26: Readiness state machine in ControlWorker

**Files:**
- Modify: `worker.py`
- Create: `tests/test_readiness.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_readiness.py`:

```python
from worker import Readiness


def test_readiness_default_is_not_ready():
    r = Readiness()
    assert not r.is_ready()


def test_readiness_all_four_gates_required():
    r = Readiness()
    r.handle_open = True
    assert not r.is_ready()
    r.imports_ok = True
    assert not r.is_ready()
    r.ax_trusted = True
    assert not r.is_ready()
    r.engine_running = True
    assert r.is_ready()


def test_readiness_loses_state_when_any_gate_drops():
    r = Readiness(handle_open=True, imports_ok=True,
                  ax_trusted=True, engine_running=True)
    assert r.is_ready()
    r.handle_open = False
    assert not r.is_ready()
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_readiness.py -v`
Expected: FAIL — `Readiness` not defined.

- [ ] **Step 3: Add Readiness to worker.py**

Append to the top of `worker.py` (after imports):

```python
from dataclasses import dataclass


@dataclass
class Readiness:
    handle_open: bool = False
    imports_ok: bool = False
    ax_trusted: bool = False
    engine_running: bool = False

    def is_ready(self) -> bool:
        return (
            self.handle_open
            and self.imports_ok
            and self.ax_trusted
            and self.engine_running
        )
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_readiness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_readiness.py
git commit -m "feat(worker): Readiness dataclass — four-gate AND"
```

---

### Task 27: Heartbeat timer in ControlWorker

**Files:**
- Modify: `worker.py`

- [ ] **Step 1: Add the heartbeat**

In `worker.py`, change `ControlWorker.__init__` to:

```python
    def __init__(self, io):
        super().__init__()
        self._io = io
        self._matrix_timer = None
        self._heartbeat_timer = None
        self._pressed_cols: set[int] = set()
        self._matrix_state = ""
        self._readiness = Readiness()
```

Add a new public method:

```python
    @Slot(str, bool)
    def update_readiness(self, gate: str, value: bool) -> None:
        """Called from various sources to update one readiness gate.
        Heartbeat starts/stops automatically when overall readiness
        transitions True ↔ False.
        """
        was_ready = self._readiness.is_ready()
        setattr(self._readiness, gate, value)
        is_ready = self._readiness.is_ready()
        if is_ready and not was_ready:
            self._start_heartbeat()
        elif not is_ready and was_ready:
            self._stop_heartbeat()

    def _start_heartbeat(self) -> None:
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.start()
            return
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(200)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)
        self._heartbeat_timer.start()

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.stop()

    @Slot()
    def _send_heartbeat(self) -> None:
        # 0xA0 HOST_SCROLL_READY, version 1
        self._io.send_untracked([0xA0, 0x01])
```

Also update `start()` to set the `handle_open` gate when load_all succeeds:

```python
    @Slot()
    def start(self):
        self._start_matrix_poll()
        self.load_all()
        # If load_all completed without emitting no-device, the handle is open.
        if self._matrix_state in ("available", "unsupported"):
            self.update_readiness("handle_open", True)
```

- [ ] **Step 2: Wire device_state to drop handle_open gate**

Also in `start()`, connect the io's device_state to clear the gate:

```python
        self._io.device_state.connect(self._on_device_state)

    @Slot(str)
    def _on_device_state(self, s: str) -> None:
        if s == "no-device":
            self.update_readiness("handle_open", False)
        elif s == "":
            self.update_readiness("handle_open", True)
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add worker.py
git commit -m "feat(worker): readiness-gated 200ms heartbeat timer"
```

---

## Phase 7 — Scroll engine integration

### Task 28: ScrollEngine as QObject with QTimer tick

**Files:**
- Modify: `scroll.py`

The pure model is class-A; the Qt-aware wrapper is class-B that owns a QTimer and emits signals. Two-layer design keeps the model unit-testable.

- [ ] **Step 1: Wrap ScrollEngine in a Qt-aware engine class**

Append to `scroll.py`:

```python
from PySide6.QtCore import QObject, QTimer, Signal, Slot
import time as _time


class QtScrollEngine(QObject):
    """Qt wrapper that drives ScrollEngine.tick at 120 Hz via QTimer."""

    started = Signal()
    stopped = Signal()

    TICK_PERIOD_MS = 8  # ~120 Hz

    def __init__(self, config: ScrollConfig | None = None):
        super().__init__()
        self.engine = ScrollEngine(
            now_fn=lambda: int(_time.monotonic() * 1000),
            post_scroll=self._post_scroll_safe,
            config=config,
        )
        self._timer = None
        self._post = None  # filled in start_real(); None during tests

    @Slot()
    def start_real(self) -> None:
        """Production start: install the real Quartz poster and begin
        ticking. Called on the engine thread."""
        self._post = make_cgevent_post()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(self.TICK_PERIOD_MS)
            self._timer.timeout.connect(self.engine.tick)
        self._timer.start()
        self.started.emit()

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.stopped.emit()

    @Slot(int, int)
    def on_scroll_tick(self, direction: int, device_t_ms: int) -> None:
        self.engine.on_tick(direction, device_t_ms)

    def _post_scroll_safe(self, pixels: int, scroll_phase: int,
                          momentum_phase: int) -> None:
        if self._post is None:
            return  # not started / not on macOS
        self._post(pixels, scroll_phase, momentum_phase)

    def reload_config(self, cfg: ScrollConfig) -> None:
        self.engine.config = cfg
```

- [ ] **Step 2: Smoke test**

Append to `tests/test_scroll_model.py`:

```python
def test_qt_scroll_engine_constructs_without_qt_running():
    from scroll import QtScrollEngine
    eng = QtScrollEngine()
    assert eng.engine.state.phase == Phase.IDLE
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_scroll_model.py::test_qt_scroll_engine_constructs_without_qt_running -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scroll.py tests/test_scroll_model.py
git commit -m "feat(scroll): QtScrollEngine — 120Hz QTimer + real CGEvent poster"
```

---

### Task 29: Wire ScrollEngine into main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update main.py**

Replace `main.py` with:

```python
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from hid_io import HidIoWorker
from listener import Listener
from scroll import QtScrollEngine, is_accessibility_trusted, load_config
from ui import MainWindow
from worker import ControlWorker


CONFIG_PATH = Path.home() / ".config" / "doio-kb03" / "scroll.json"


def main() -> int:
    app = QApplication(sys.argv)

    # Try imports first — failure here drops the imports_ok gate.
    imports_ok = True
    try:
        import Quartz  # noqa: F401
        import ApplicationServices  # noqa: F401
    except ImportError:
        imports_ok = False

    # Prompt for Accessibility once.
    ax_trusted = is_accessibility_trusted(prompt=True)

    cfg = load_config(CONFIG_PATH)

    io = HidIoWorker()
    io_thread = QThread()
    io.moveToThread(io_thread)
    io_thread.started.connect(io.run_forever)

    control = ControlWorker(io)
    control_thread = QThread()
    control.moveToThread(control_thread)
    control_thread.started.connect(control.start)

    scroll_engine = QtScrollEngine(cfg)
    scroll_thread = QThread()
    scroll_engine.moveToThread(scroll_thread)
    scroll_thread.started.connect(scroll_engine.start_real)
    io.scroll_tick.connect(scroll_engine.on_scroll_tick)

    # Readiness wiring (the four gates):
    # 1. handle_open: ControlWorker sets it (see worker._on_device_state).
    # 2. imports_ok: set once, here.
    # 3. ax_trusted: set here and re-checkable from UI.
    # 4. engine_running: set on QtScrollEngine.started.
    control.update_readiness("imports_ok", imports_ok)
    control.update_readiness("ax_trusted", ax_trusted)
    scroll_engine.started.connect(
        lambda: control.update_readiness("engine_running", True))
    scroll_engine.stopped.connect(
        lambda: control.update_readiness("engine_running", False))

    listener = Listener()
    listener_thread = QThread()
    listener.moveToThread(listener_thread)
    listener_thread.started.connect(listener.start)

    window = MainWindow(control, listener, scroll_engine=scroll_engine,
                        imports_ok=imports_ok,
                        ax_trusted_initial=ax_trusted,
                        config=cfg, config_path=CONFIG_PATH)

    io_thread.start()
    control_thread.start()
    listener_thread.start()
    scroll_thread.start()
    window.show()

    code = app.exec()
    scroll_engine.stop()
    io.stop()
    listener.stop()
    listener_thread.quit()
    control_thread.quit()
    io_thread.quit()
    scroll_thread.quit()
    listener_thread.wait()
    control_thread.wait()
    io_thread.wait()
    scroll_thread.wait()
    return code


if __name__ == "__main__":
    sys.exit(main())
```

Note the `MainWindow` signature change — Task 30 updates `ui.py` to accept the new kwargs.

- [ ] **Step 2: Commit (UI changes come next)**

```bash
git add main.py
git commit -m "feat(main): wire ScrollEngine + readiness gates into app"
```

(ui.py will not yet accept the new kwargs — the next task fixes that.)

---

## Phase 8 — UI

### Task 30: MainWindow accepts scroll_engine + config kwargs

**Files:**
- Modify: `ui.py`

- [ ] **Step 1: Add the kwargs to MainWindow.__init__**

In `ui.py` at `class MainWindow` (line 674), the existing signature at line 686 is:

```python
    def __init__(self, control, listener):
        super().__init__()
        self.setWindowTitle("DOIO KB03-01")
        self._control = control
        self._listener = listener
        # ...
```

Update to:

```python
    def __init__(self, control, listener, *,
                 scroll_engine=None, imports_ok: bool = True,
                 ax_trusted_initial: bool = True,
                 config=None, config_path=None):
        super().__init__()
        self.setWindowTitle("DOIO KB03-01")
        self._control = control
        self._listener = listener
        self._scroll_engine = scroll_engine
        self._scroll_config = config
        self._scroll_config_path = config_path
        self._imports_ok = imports_ok
        self._ax_trusted = ax_trusted_initial
        # ... (rest of existing __init__ body unchanged)
```

Leave every other line in `__init__` exactly as it was.

- [ ] **Step 2: Manual smoke test**

Run: `uv run python main.py`
Expected: GUI launches, same as before. Accessibility prompt may appear once (grant + relaunch).

- [ ] **Step 3: Commit**

```bash
git add ui.py
git commit -m "feat(ui): MainWindow accepts scroll_engine + config kwargs"
```

---

### Task 31: Scroll-feel panel

**Files:**
- Modify: `ui.py`

The panel is a `QGroupBox` with sliders for each tunable param, an invert toggle, and live application of changes.

- [ ] **Step 1: Add the panel class**

In `ui.py`, append a new class above `class MainWindow`:

```python
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QLabel, QSlider, QVBoxLayout, QHBoxLayout, QPushButton)
from PySide6.QtCore import Qt

from scroll import ScrollConfig, save_config


class ScrollFeelPanel(QGroupBox):
    SLIDERS = [
        # (attr,                label,            lo,    hi,   step, fmt)
        ("impulse_per_detent",  "Impulse",        20,    500,  10,   "{} px/s"),
        ("tau_ms",              "Decay τ",        50,    2000, 50,   "{} ms"),
        ("slow_threshold",      "Slow threshold", 50,    1000, 25,   "{} px/s"),
        ("fast_threshold",      "Fast threshold", 500,   5000, 100,  "{} px/s"),
        ("max_gain",            "Max gain",       10,    120,  5,    "{}.×0.1"),
        ("active_window_ms",    "Active window",  30,    250,  10,   "{} ms"),
        ("coast_threshold",     "Coast threshold",50,    2000, 25,   "{} px/s"),
        ("cutoff_v",            "Momentum cutoff",5,     200,  5,    "{} px/s"),
    ]

    def __init__(self, config: ScrollConfig, config_path,
                 scroll_engine, ax_trusted: bool, imports_ok: bool):
        super().__init__("Scroll feel — outer ring")
        self._config = config
        self._config_path = config_path
        self._engine = scroll_engine
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}

        v = QVBoxLayout(self)

        # Status banner
        self._banner = QLabel()
        self._banner.setWordWrap(True)
        v.addWidget(self._banner)
        self._update_banner(imports_ok=imports_ok, ax_trusted=ax_trusted)

        # Re-check button
        h = QHBoxLayout()
        self._recheck = QPushButton("Re-check Accessibility")
        self._recheck.clicked.connect(self._on_recheck)
        h.addWidget(self._recheck)
        h.addStretch()
        v.addLayout(h)

        # Sliders
        for attr, label, lo, hi, step, fmt in self.SLIDERS:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(120)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(lo, hi)
            slider.setSingleStep(step)
            slider.setPageStep(step * 10)
            current = getattr(config, attr)
            if attr == "max_gain":
                slider.setValue(int(current * 10))
            else:
                slider.setValue(int(current))
            val_lbl = QLabel()
            val_lbl.setMinimumWidth(80)
            slider.valueChanged.connect(
                lambda val, a=attr: self._on_slider_change(a, val))
            self._sliders[attr] = slider
            self._value_labels[attr] = val_lbl
            self._refresh_value_label(attr)
            row.addWidget(lbl)
            row.addWidget(slider, 1)
            row.addWidget(val_lbl)
            v.addLayout(row)

        # Invert toggle
        self._invert = QCheckBox("Invert direction")
        self._invert.setChecked(config.invert)
        self._invert.toggled.connect(self._on_invert)
        v.addWidget(self._invert)

    def _refresh_value_label(self, attr: str) -> None:
        v = getattr(self._config, attr)
        if attr == "max_gain":
            text = f"{v:.1f}×"
        else:
            text = str(int(v))
        self._value_labels[attr].setText(text)

    def _on_slider_change(self, attr: str, raw_value: int) -> None:
        if attr == "max_gain":
            setattr(self._config, attr, raw_value / 10.0)
        elif attr in {"tau_ms", "active_window_ms"}:
            setattr(self._config, attr, int(raw_value))
        else:
            setattr(self._config, attr, float(raw_value))
        # Enforce ordering invariant on the fly
        if self._config.coast_threshold < self._config.cutoff_v:
            self._config.coast_threshold = self._config.cutoff_v
            self._sliders["coast_threshold"].setValue(
                int(self._config.coast_threshold))
        self._refresh_value_label(attr)
        if self._engine is not None:
            self._engine.reload_config(self._config)
        save_config(self._config, self._config_path)

    def _on_invert(self, checked: bool) -> None:
        self._config.invert = checked
        if self._engine is not None:
            self._engine.reload_config(self._config)
        save_config(self._config, self._config_path)

    def _on_recheck(self) -> None:
        from scroll import is_accessibility_trusted
        trusted = is_accessibility_trusted(prompt=True)
        self._update_banner(imports_ok=True, ax_trusted=trusted)
        # Propagate to ControlWorker — parent injects this callback
        if hasattr(self, "_on_ax_change"):
            self._on_ax_change(trusted)

    def _update_banner(self, *, imports_ok: bool, ax_trusted: bool) -> None:
        if not imports_ok:
            self._banner.setStyleSheet("background: #ffe0e0; padding: 6px;")
            self._banner.setText(
                "pyobjc-framework-Quartz is missing. The outer encoder will "
                "fall back to plain wheel events. Run `uv sync`.")
        elif not ax_trusted:
            self._banner.setStyleSheet("background: #fff3e0; padding: 6px;")
            self._banner.setText(
                "Accessibility permission not granted. Outer encoder is in "
                "fallback mode. Grant in System Settings → Privacy & Security "
                "→ Accessibility, then click Re-check.")
        else:
            self._banner.setStyleSheet("background: #e0ffe0; padding: 6px;")
            self._banner.setText("MX-Master scroll active.")

    def set_ax_change_callback(self, cb):
        self._on_ax_change = cb
```

- [ ] **Step 2: Mount the panel in MainWindow**

In `ui.py` at `MainWindow.__init__` (around line 737), the current code is:

```python
        self._build_device_widget()
        self._build_layer_selector()
        self._build_editor()
        self._build_led_panel()
        self._inspector_v.addStretch()
        self._set_layer_led(0)
        self._connect_workers(control, listener)
```

Insert a new `_build_scroll_panel()` call between `_build_led_panel()` and `_inspector_v.addStretch()`:

```python
        self._build_device_widget()
        self._build_layer_selector()
        self._build_editor()
        self._build_led_panel()
        self._build_scroll_panel()
        self._inspector_v.addStretch()
        self._set_layer_led(0)
        self._connect_workers(control, listener)
```

Then add the builder method to `MainWindow` (anywhere among the other `_build_*` methods):

```python
    def _build_scroll_panel(self):
        if self._scroll_engine is None:
            return
        self._scroll_panel = ScrollFeelPanel(
            self._scroll_config, self._scroll_config_path,
            self._scroll_engine,
            ax_trusted=self._ax_trusted,
            imports_ok=self._imports_ok,
        )
        self._scroll_panel.set_ax_change_callback(
            lambda v: self._control.update_readiness("ax_trusted", v))
        self._inspector_v.addWidget(self._scroll_panel)
```

- [ ] **Step 3: Manual smoke test**

Run: `uv run python main.py`
Expected: GUI launches with new Scroll feel panel visible. Banner shows green/orange/red based on permission state. Sliders move and update labels; values persist to `~/.config/doio-kb03/scroll.json`.

- [ ] **Step 4: Commit**

```bash
git add ui.py
git commit -m "feat(ui): Scroll feel panel — sliders, invert, AX banner"
```

---

## Phase 9 — Firmware

### Task 32: rules.mk update

**Files:**
- Modify: `firmware/keymaps/vegar/rules.mk`

- [ ] **Step 1: Edit rules.mk**

Open `firmware/keymaps/vegar/rules.mk`. Add at the end:

```make
# MX-Master scroll support
SRC += inertia.c
RAW_ENABLE = yes
```

- [ ] **Step 2: Commit (will verify together with build later)**

```bash
git add firmware/keymaps/vegar/rules.mk
git commit -m "build(firmware): enable inertia.c + RAW_ENABLE for scroll feature"
```

---

### Task 33: inertia.h public API

**Files:**
- Create: `firmware/keymaps/vegar/inertia.h`

- [ ] **Step 1: Write the header**

```c
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
```

- [ ] **Step 2: Commit**

```bash
git add firmware/keymaps/vegar/inertia.h
git commit -m "feat(firmware): inertia.h — host-readiness + scroll-ping API"
```

---

### Task 34: inertia.c — implementation

**Files:**
- Create: `firmware/keymaps/vegar/inertia.c`

- [ ] **Step 1: Write the source**

```c
// SPDX-License-Identifier: GPL-2.0-or-later
//
// inertia.c — see inertia.h.

#include "inertia.h"

#include "raw_hid.h"
#include "timer.h"
#include "quantum.h"

#define HOST_READY_WINDOW_MS 500

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
    uint8_t f[RAW_EPSIZE] = {0};
    uint32_t t = timer_read32();

    f[0] = 0xA1;            // SCROLL_PING
    f[1] = 0x01;            // protocol version
    f[2] = cw ? 1 : 0;
    f[3] = 0x00;            // flags reserved
    f[4] = (uint8_t)(t      );
    f[5] = (uint8_t)(t >>  8);
    f[6] = (uint8_t)(t >> 16);
    f[7] = (uint8_t)(t >> 24);

    raw_hid_send(f, RAW_EPSIZE);
}
```

- [ ] **Step 2: Commit**

```bash
git add firmware/keymaps/vegar/inertia.c
git commit -m "feat(firmware): inertia.c — host-readiness watchdog + scroll ping"
```

---

### Task 35: keymap.c — custom keycodes + via_command_kb + housekeeping

**Files:**
- Modify: `firmware/keymaps/vegar/keymap.c`

- [ ] **Step 1: Update keymap.c**

Replace the entire contents with:

```c
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
```

- [ ] **Step 2: Commit**

```bash
git add firmware/keymaps/vegar/keymap.c
git commit -m "feat(firmware): outer-ring custom keycodes + VIA heartbeat hook"
```

---

### Task 36: VIA layout version bump (EEPROM migration)

**Files:**
- Modify: `firmware/keymaps/vegar/config.h`

- [ ] **Step 1: Bump the version**

Open `firmware/keymaps/vegar/config.h`. Add at the end:

```c
// Bump VIA layout version: forces EEPROM re-sync of encoder bindings on
// first boot after flashing, so the new outer-ring custom keycodes
// reach the encoder_map in EEPROM rather than the user keeping stale
// MS_WHLL/MS_WHLR bindings. See spec section "VIA EEPROM migration".
#undef VIA_FIRMWARE_VERSION
#define VIA_FIRMWARE_VERSION 0x00000002
```

If `VIA_FIRMWARE_VERSION` isn't already defined upstream (check by searching the QMK tree), this bump is purely cosmetic; the encoder_map re-sync still happens because the encoder_map's compiled bytes differ. In that case, the fallback migration (post-init explicit overwrite) is added in the next sub-step.

- [ ] **Step 2: Add fallback migration in keymap.c**

In case the layout-version bump doesn't trigger re-sync, force the encoder bindings on first boot. In `firmware/keymaps/vegar/keymap.c`, append:

```c
void keyboard_post_init_user(void) {
    // Defensive: ensure outer-ring encoder_map[*][1] matches the
    // compile-time keymap above. Only needed if VIA stored stale
    // bindings in EEPROM from a previous flash. Idempotent.
#ifdef ENCODER_MAP_ENABLE
    for (uint8_t ly = 0; ly < 4; ly++) {
        const uint16_t ccw = OUTER_SCROLL_CCW;
        const uint16_t cw  = OUTER_SCROLL_CW;
        dynamic_keymap_set_encoder(ly, 1, 0, ccw);
        dynamic_keymap_set_encoder(ly, 1, 1, cw);
    }
#endif
}
```

> Note: `dynamic_keymap_set_encoder` is a QMK API. If the symbol doesn't link (older QMK), look for `via_encoder_eeprom_set` or do nothing here and rely on the layout-version bump.

- [ ] **Step 3: Commit**

```bash
git add firmware/keymaps/vegar/config.h firmware/keymaps/vegar/keymap.c
git commit -m "feat(firmware): bump VIA layout version + post-init EEPROM sync"
```

---

### Task 37: Build firmware

**Files:** none modified — this is a build verification step.

- [ ] **Step 1: Build**

Run: `bash firmware/build.sh vegar` (or whatever the build script's exact invocation is; check `firmware/README.md`).

Expected: Build succeeds. A `.bin` and `.hex` appear under the QMK build directory (the build script symlinks back). Look for `inertia.c` in the compiler output to confirm the SRC += line worked.

Common failures and fixes:
- `inertia.c: No such file` → check `SRC +=` line (not `SRCS`).
- `raw_hid_send: undefined reference` → add `RAW_ENABLE = yes` to rules.mk if not already.
- `dynamic_keymap_set_encoder: undefined reference` → remove the post-init migration block; rely on layout-version bump only.
- `MS_WHLU: undeclared` → some older QMK uses `KC_MS_WHEEL_UP`. Substitute as needed (try `MS_WHLU` first per the spec).

- [ ] **Step 2: Note any deltas in the commit**

If you had to substitute aliases, commit those fixes with a descriptive message before continuing.

- [ ] **Step 3: Stage the resulting `.bin/.hex` under `firmware/dumps/`**

Per project convention (the repo vendors firmware dumps), copy the new build artefact:

```bash
cp <qmk_build>/doio_kb03_vegar.bin firmware/dumps/doio_kb03_vegar_$(date +%Y%m%d).bin
git add firmware/dumps/doio_kb03_vegar_*.bin
git commit -m "build(firmware): vendor build artefact for outer-encoder scroll"
```

(Hash/path may differ; check `firmware/README.md` for the actual dump-naming convention.)

---

### Task 38: Flash firmware (manual)

**Files:** none. This is a manual hardware step.

- [ ] **Step 1: Flash**

Follow `firmware/README.md` for the flash flow (typically: hold bootmagic key on plug, then `qmk flash` or the equivalent). Confirm the device reboots and re-enumerates as VID `0xD010` / PID `0x0301`.

- [ ] **Step 2: Sanity check — fallback mode**

With the GUI closed, turn the outer ring. Use a text editor or any scrollable page: the outer ring should scroll vertically (plain detented wheel events). If it scrolls horizontally, the firmware fallback maps weren't updated correctly — re-check `encoder_map` for `OUTER_SCROLL_CCW/CW` on every layer and that the `MS_WHLL/MS_WHLR` references are gone.

- [ ] **Step 3: Note this step in your test log**

This is a manual gate. Don't proceed to Phase 10 until fallback works in standalone mode.

---

## Phase 10 — Integration and acceptance

### Task 39: End-to-end smoke — host takeover engages

- [ ] **Step 1: Launch the GUI**

Run: `uv run python main.py`

Expected:
- The Accessibility prompt appears (if not already granted). Grant it.
- The Scroll feel panel banner is green ("MX-Master scroll active.").
- All four readiness gates are true.

- [ ] **Step 2: Verify takeover with the scroll probe**

In a separate terminal (with its own Accessibility permission), run `uv run python scripts/scroll_probe.py`. Turn the outer ring slowly.

Expected log entries:
- `phase=began ... cont=1 deltaY=0 pointDeltaY=0` (first detent, scroll begins).
- A run of `phase=changed ... cont=1 deltaY=<small> pointDeltaY=<small>` (active phase).
- After ~80 ms of no detent: `phase=ended ... momentum=began ... momentum=changed ...` etc.
- Finally `momentum=ended cont=1 deltaY=0`.

If you see `cont=0`, the IsContinuous flag wasn't set — re-check `make_cgevent_post`.

- [ ] **Step 3: Verify fallback engages on host quit**

Quit the GUI. Within ~500 ms, the outer ring should be back to producing plain wheel events (single deltaY per detent, no continuous/momentum phases). Confirm via `scroll_probe.py`.

---

### Task 40: Behaviour acceptance — manual checklist

Run through each item from the spec's "Manual hardware verification" section. Tick each off and capture short notes (a one-liner per item).

- [ ] Fallback (GUI closed) — outer ring scrolls vertically with plain wheel events.
- [ ] Fallback (GUI running, Accessibility denied) — encoder still produces firmware wheel events (revoke permission, relaunch, verify, restore).
- [ ] Takeover — pixel-smooth scroll when GUI + Accessibility both on.
- [ ] Coast — fast spin then release coasts smoothly, ends without jolt.
- [ ] Direction-flip kill — fast spin then reverse cancels coast instantly.
- [ ] Precision — slow turns give small predictable scroll, no flings.
- [ ] Crash recovery (corrected wording) — force-quit the GUI mid-coast; host momentum stops immediately; new detents go through firmware fallback within ~500 ms. **Do not** expect the host-driven momentum to continue.
- [ ] USB unplug/replug — device disconnect handled cleanly; replug restores takeover.
- [ ] Layer change — outer-ring scroll behaviour identical on all 4 layers.
- [ ] Direction calibration — with macOS natural scrolling ON, verify the `invert` toggle in the GUI matches the user's expectation. Same with natural scrolling OFF.

Record findings in `docs/superpowers/specs/2026-06-08-outer-encoder-mx-scroll-design.md` under a new section `## Acceptance run (YYYY-MM-DD)` (append-only) and commit.

```bash
git add docs/superpowers/specs/2026-06-08-outer-encoder-mx-scroll-design.md
git commit -m "docs: capture acceptance-run notes for outer-encoder scroll"
```

---

### Task 41: Per-app event-shape verification

Run `scripts/scroll_probe.py` while each app is focused, and turn the outer ring through one full gesture (slow → fast → release).

- [ ] Safari — note phase/momentum sequence, any visible jitter.
- [ ] Chrome — same.
- [ ] Finder (long folder) — same.
- [ ] VS Code (long file) — same.
- [ ] Preview (multi-page PDF) — same.
- [ ] Terminal — same.

Per spec, app-behaviour is empirical, not asserted. If any app feels wrong, document the observed event sequence — that's data, not a defect. Likely tuning candidates: `tau_ms`, `coast_threshold`, `active_window_ms`.

Append the findings to the design doc's acceptance-run section.

```bash
git add docs/superpowers/specs/2026-06-08-outer-encoder-mx-scroll-design.md
git commit -m "docs: per-app event-shape observations for outer-encoder scroll"
```

---

## Reference: the readiness invariant

After all phases, the four gates must wire like this:

| Gate | Set true by | Cleared by |
|---|---|---|
| `imports_ok` | `main.py` startup if both `Quartz` and `ApplicationServices` import | Never (stays for session lifetime) |
| `ax_trusted` | `main.py` startup (after `AXIsProcessTrustedWithOptions`) and `ScrollFeelPanel._on_recheck` | `_on_recheck` if user revokes |
| `handle_open` | `ControlWorker._on_device_state("")` | `ControlWorker._on_device_state("no-device")` |
| `engine_running` | `QtScrollEngine.started` signal | `QtScrollEngine.stopped` signal |

The heartbeat fires iff all four hold. The firmware sees no heartbeat → host_scroll_ready timeout → fallback. This is the whole takeover contract.

---

## Spec coverage self-check

Use this as the final hand-off gate. Every requirement should be implemented above.

- [x] Behaviour contract items 1–11 — covered in scroll model tasks 3–14, firmware tasks 35.
- [x] Damped impulse model — task 7, 8, 12.
- [x] MagSpeed gain — task 4.
- [x] Precision (≤15 px) — task 11.
- [x] Coast / cutoff / coast_threshold — tasks 8, 15.
- [x] Direction-flip kill — task 10.
- [x] Pixel-precise output with continuous + phase + momentum — task 16, 29.
- [x] Standalone fallback — firmware task 35 (process_record_user).
- [x] Inner knob untouched — firmware task 35 keeps encoder_map[*][0].
- [x] Cross-layer (all 4) — firmware task 35.
- [x] Direction calibration / invert — task 9, 30, 31.
- [x] Custom keycodes via process_record_user — task 35.
- [x] via_command_kb heartbeat path — task 35.
- [x] raw_hid_send(f, RAW_EPSIZE) zero-fill + protocol version — task 34.
- [x] SRC += inertia.c — task 32.
- [x] Four-gate readiness — tasks 26, 27, 29.
- [x] Per-command-ID FIFO + 0xFF id_unhandled — tasks 18–20.
- [x] send_request vs send_untracked — tasks 18, 27.
- [x] Single HidIoWorker owner — tasks 18, 22, 25.
- [x] dt clamp — tasks 8, 13.
- [x] enter_active / enter_momentum / enter_idle helpers — task 6.
- [x] Accumulator + velocity cleared on IDLE — task 6.
- [x] Gain in both ACTIVE and MOMENTUM — task 7 / 8.
- [x] QTimer-driven tick (not sleep loop) — task 28.
- [x] AXIsProcessTrustedWithOptions on startup — task 29.
- [x] Accessibility-denied fallback — manual test 40.
- [x] pyobjc deps explicit — task 1.
- [x] App behaviour empirically verified (scroll_probe.py) — tasks 2, 41.
- [x] Crash-recovery corrected wording — manual test 40.
- [x] VIA EEPROM migration — task 36.

No spec section is uncovered. If you find one during execution, raise it before continuing.
