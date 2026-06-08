"""Scroll event probe. Logs every scroll-wheel CGEvent that flows through
the session tap. Use it to verify our emitted scroll events have the
right phase/momentum-phase/IsContinuous/deltaY shape, and to compare
against a real trackpad. Requires Accessibility permission for
Terminal/iTerm (whatever runs this).

Run with the GUI closed — it does not touch 0xFF60.

    uv run python scripts/scroll_probe.py
"""

from __future__ import annotations

import collections
import sys
import time

import Quartz


_intervals = collections.deque(maxlen=200)
_last_t = None

def _record_event_time():
    global _last_t
    now = time.monotonic()
    if _last_t is not None:
        _intervals.append(now - _last_t)
    _last_t = now

def _stats_line():
    if not _intervals:
        return ""
    sorted_iv = sorted(_intervals)
    n = len(sorted_iv)
    return (f"  intervals(ms) min={sorted_iv[0]*1000:.1f} "
            f"med={sorted_iv[n//2]*1000:.1f} "
            f"max={sorted_iv[-1]*1000:.1f} n={n}")


SCROLL_WHEEL_EVENT = Quartz.kCGEventScrollWheel
MASK = Quartz.CGEventMaskBit(SCROLL_WHEEL_EVENT)


def _phase_name(value: int) -> str:
    # CoreGraphics CGScrollPhase values (NOT NSEventPhase).
    return {
        0: "none",
        1: "began",
        2: "changed",
        4: "ended",
        8: "cancelled",
        128: "may-begin",
    }.get(value, f"unknown({value})")


def _momentum_name(value: int) -> str:
    return {
        0: "none",
        1: "began",
        2: "changed",
        3: "ended",
    }.get(value, f"unknown({value})")


_event_count = 0

def _tap_callback(proxy, type_, ev, refcon):
    global _event_count
    if type_ != SCROLL_WHEEL_EVENT:
        return ev
    g = Quartz.CGEventGetIntegerValueField
    gd = Quartz.CGEventGetDoubleValueField
    phase = g(ev, Quartz.kCGScrollWheelEventScrollPhase)
    mom   = g(ev, Quartz.kCGScrollWheelEventMomentumPhase)
    cont  = g(ev, Quartz.kCGScrollWheelEventIsContinuous)
    dy    = g(ev, Quartz.kCGScrollWheelEventDeltaAxis1)
    pdy   = g(ev, Quartz.kCGScrollWheelEventPointDeltaAxis1)
    # FixedPt field may or may not be exposed; guard.
    try:
        fpdy = gd(ev, Quartz.kCGScrollWheelEventFixedPtDeltaAxis1)
    except Exception:
        fpdy = float("nan")
    print(
        f"{time.monotonic():.3f}  phase={phase}({_phase_name(phase):<9}) "
        f"momentum={mom}({_momentum_name(mom):<7}) cont={cont} "
        f"deltaY={dy:>5} pointDeltaY={pdy:>5} fixedPtDeltaY={fpdy:>8.2f}",
        flush=True,
    )
    _record_event_time()
    _event_count += 1
    if _event_count % 50 == 0:
        print(_stats_line(), file=sys.stderr, flush=True)
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
