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


def magspeed_gain(abs_v: float, c: ScrollConfig) -> float:
    if abs_v <= c.slow_threshold:
        return 1.0
    if abs_v >= c.fast_threshold:
        return c.max_gain
    t = (abs_v - c.slow_threshold) / (c.fast_threshold - c.slow_threshold)
    return 1.0 + t * (c.max_gain - 1.0)
