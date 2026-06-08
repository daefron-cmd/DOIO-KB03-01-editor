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
