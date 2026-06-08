"""ScrollEngine: MX-Master-style scroll wheel emulation for the outer
encoder. Pure inertia state machine + macOS event posting.

The state machine and the Quartz post are split: pass `post_scroll`
(a callable taking pixels, scroll_phase, momentum_phase) into the
engine so the model is unit-testable without macOS.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from enum import Enum
from pathlib import Path


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


from typing import Callable


class ScrollPhase:
    """Mirror of CoreGraphics CGScrollPhase values (NOT NSEvent values).
    Verified at runtime against Quartz.kCGScrollPhase* on Darwin.
    """
    NONE = 0       # local sentinel; CoreGraphics has no NONE
    BEGAN = 1
    CHANGED = 2
    ENDED = 4
    CANCELLED = 8
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


def magspeed_gain(abs_v: float, c: ScrollConfig) -> float:
    if abs_v <= c.slow_threshold:
        return 1.0
    if abs_v >= c.fast_threshold:
        return c.max_gain
    t = (abs_v - c.slow_threshold) / (c.fast_threshold - c.slow_threshold)
    return 1.0 + t * (c.max_gain - 1.0)


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
