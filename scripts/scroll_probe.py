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


def _tap_callback(proxy, type_, ev, refcon):
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
