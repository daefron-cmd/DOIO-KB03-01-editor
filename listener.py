"""Live-press listener. Pure report decode (unit-tested) + a QObject worker
that opens the keyboard + consumer interfaces and emits decoded events.
Stays pure of layout/snapshot knowledge — matching happens in the UI."""

import time

import hid
from PySide6.QtCore import QObject, Signal

VID, PID = 0xD010, 0x0301

# Verified on hardware 2026-05-29 (Task 11 step 1): the knob's media usages
# arrive on the 0x0001/0x02 interface (which opens WITHOUT Input Monitoring),
# NOT on 0x000C/0x01. Layout is [report-id 0x04][LE16 usage]: 04 E9 00 = vol+
# (0x00E9), 04 EA 00 = vol- (0x00EA), 04 00 00 = release. Usage is at offset 1.
CONSUMER_USAGE_OFFSET = 1


def decode_keyboard_report(report: list[int]) -> tuple[int, list[int]]:
    """(modifiers, [keycodes]) from a keyboard report.

    QMK devices may expose either a plain 8-byte boot report
    [mods, reserved, key1..key6] or the same payload prefixed by a report ID.
    """
    offset = 1 if len(report) >= 9 else 0
    mods = report[offset]
    keys = [u for u in report[offset + 2:offset + 8] if u]
    return mods, keys


def decode_consumer_report(report: list[int]) -> list[int]:
    """[consumer usage ids] — single LE16 usage at the verified offset."""
    off = CONSUMER_USAGE_OFFSET
    if len(report) < off + 2:
        return []
    usage = report[off] | (report[off + 1] << 8)
    return [usage] if usage else []


class Listener(QObject):
    input_event = Signal(str, int, list)        # iface_kind, mods, keycodes
    permission_state = Signal(str)              # "" ok / "input-monitoring-denied"

    def __init__(self):
        super().__init__()
        self._running = False
        self._devs = []  # (iface_kind, hid.device)

    def start(self):
        """init slot — runs ON the worker thread (connected queued)."""
        self._open()
        self._running = True
        self._loop()

    def stop(self):
        self._running = False

    def _open(self):
        denied = False
        keyboard_opened = False
        for d in hid.enumerate(VID, PID):
            up, u = d["usage_page"], d["usage"]
            kind = ("keyboard" if (up, u) == (0x01, 0x06)
                    else "consumer" if up in (0x01, 0x0C) and u != 0x06
                    else None)
            if kind is None:
                continue
            try:
                dev = hid.device()
                dev.open_path(d["path"])
                dev.set_nonblocking(1)
                self._devs.append((kind, dev))
                if kind == "keyboard":
                    keyboard_opened = True
            except Exception:  # noqa: BLE001 — keyboard iface needs permission
                if kind == "keyboard":
                    denied = True
        if not keyboard_opened:
            denied = True
        self.permission_state.emit("input-monitoring-denied" if denied else "")

    def _loop(self):
        while self._running:
            for kind, dev in self._devs:
                data = dev.read(64)
                if not data:
                    continue
                if kind == "keyboard":
                    mods, keys = decode_keyboard_report(data)
                    if keys:  # ignore mods-only transients for flashing
                        self.input_event.emit("keyboard", mods, keys)
                else:
                    usages = decode_consumer_report(data)
                    if usages:
                        self.input_event.emit("consumer", 0, usages)
            time.sleep(0.005)
