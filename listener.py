"""Live-press listener. Pure report decode (unit-tested) + a QObject worker
that opens the keyboard + consumer interfaces and emits decoded events.
Stays pure of layout/snapshot knowledge — matching happens in the UI."""

import time
import threading

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
    keys = [u for u in report[offset + 2 : offset + 8] if u]
    return mods, keys


def decode_consumer_report(report: list[int]) -> list[int]:
    """[consumer usage ids] — single LE16 usage at the verified offset."""
    off = CONSUMER_USAGE_OFFSET
    if len(report) < off + 2:
        return []
    usage = report[off] | (report[off + 1] << 8)
    return [usage] if usage else []


class Listener(QObject):
    input_event = Signal(str, int, list)  # iface_kind, mods, keycodes
    permission_state = Signal(str)  # "" ok / "input-monitoring-denied"

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()
        self._devs = {}  # path -> (iface_kind, hid.device)
        self._permission = None

    def start(self):
        """init slot — runs ON the worker thread (connected queued)."""
        try:
            self._loop()
        finally:
            self._close_all()

    def stop(self):
        self._stop.set()

    def _open(self):
        denied = False
        try:
            devices = hid.enumerate(VID, PID)
        except OSError:
            return  # Retry enumeration at the next scan.
        present = {d["path"] for d in devices}
        for path in list(self._devs):
            if path not in present:
                self._close(path)
        for d in devices:
            up, u = d["usage_page"], d["usage"]
            kind = (
                "keyboard"
                if (up, u) == (0x01, 0x06)
                else "consumer"
                if up in (0x01, 0x0C) and u != 0x06
                else None
            )
            if kind is None or d["path"] in self._devs:
                continue
            dev = None
            try:
                dev = hid.device()
                dev.open_path(d["path"])
                dev.set_nonblocking(1)
                self._devs[d["path"]] = (kind, dev)
            except Exception:  # noqa: BLE001 — keyboard iface needs permission
                if dev is not None:
                    try:
                        dev.close()
                    except OSError:
                        pass
                if kind == "keyboard":
                    denied = True
        # Absence is not evidence of a denied Input Monitoring permission.
        state = "input-monitoring-denied" if denied else ""
        if state != self._permission:
            self._permission = state
            self.permission_state.emit(state)

    def _close(self, path):
        _, dev = self._devs.pop(path)
        try:
            dev.close()
        except OSError:
            pass

    def _close_all(self):
        for path in list(self._devs):
            self._close(path)

    def _poll_once(self):
        for path, (kind, dev) in list(self._devs.items()):
            try:
                data = dev.read(64)
            except OSError:
                self._close(path)
                continue
            if not data:
                continue
            if kind == "keyboard":
                mods, keys = decode_keyboard_report(data)
                if keys:
                    self.input_event.emit("keyboard", mods, keys)
            else:
                usages = decode_consumer_report(data)
                if usages:
                    self.input_event.emit("consumer", 0, usages)

    def _loop(self):
        next_scan = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_scan:
                self._open()
                next_scan = time.monotonic() + 1.0
            self._poll_once()
            delay = 0.005 if self._devs else max(0.0, next_scan - time.monotonic())
            self._stop.wait(delay)
