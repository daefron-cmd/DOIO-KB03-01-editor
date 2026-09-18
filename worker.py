"""ControlWorker: thread-bound owner of the VIA command/reply lifecycle.

The HID handle itself is owned by HidIoWorker. ControlWorker submits
requests via io.send_request(builder), receives results via Future,
and emits the same Qt signals it always did.
"""

import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, fields

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

import core
from model import Snapshot, key_id, enc_id


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


_READINESS_GATES = frozenset(f.name for f in fields(Readiness))


class ControlWorker(QObject):
    snapshot_ready = Signal(object)
    device_state = Signal(str)
    set_ack = Signal(object, bool)
    lighting_saved = Signal(bool)
    loading = Signal(bool)
    matrix_state = Signal(str)
    matrix_press = Signal(object)
    matrix_release = Signal(object)
    readiness_changed = Signal(object)

    REPLY_TIMEOUT_S = 1.0
    HEARTBEAT_INTERVAL_S = 0.2

    def __init__(self, io):
        super().__init__()
        self._io = io
        self._matrix_timer = None
        self._heartbeat_timer = None
        self._last_heartbeat_s = 0.0
        self._pressed_cols: set[int] = set()
        self._matrix_state = ""
        self._readiness = Readiness()

    def _request(self, payload: list[int]) -> list[int] | None:
        fut = self._io.send_request(payload)
        deadline = time.monotonic() + self.REPLY_TIMEOUT_S
        try:
            while True:
                timeout = min(0.05, max(0.0, deadline - time.monotonic()))
                try:
                    return fut.result(timeout=timeout)
                except FutureTimeoutError:
                    if time.monotonic() >= deadline:
                        raise
                    self._send_heartbeat_if_due()
        except FutureTimeoutError:
            # Timed-out future is still in HidIoWorker's queues. Remove
            # it so a late reply doesn't get mis-attributed.
            self._io.cancel(fut)
            self.device_state.emit("no-device")
            return None
        except Exception:  # TransportClosedError, IdUnhandledError, etc.
            self.device_state.emit("no-device")
            return None

    @Slot()
    def start(self):
        self._start_matrix_poll()
        if self._readiness.handle_open:
            self.load_all()
        else:
            self.device_state.emit("no-device")
        # Do NOT infer handle_open from matrix state. handle_open is set
        # by _on_device_state from HidIoWorker.

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
                keymap=keymap,
                encoders=encoders,
                brightness=b[3],
                effect=e[3],
                speed=s[3],
                hue=c[3],
                sat=c[4],
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
        if self._matrix_timer is None:
            self._matrix_timer = QTimer(self)
            self._matrix_timer.setInterval(30)
            self._matrix_timer.timeout.connect(self._poll_matrix)
        if self._readiness.handle_open:
            self._matrix_timer.start()

    @Slot()
    def _poll_matrix(self):
        if not self._readiness.handle_open:
            return
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

    @Slot(str, bool)
    def update_readiness(self, gate: str, value: bool) -> None:
        """Single mutation point. Must only run on control_thread.
        External callers connect signals to the bound slots below
        (on_engine_started/stopped, on_ax_trusted_changed, etc.) so
        delivery is queued onto this thread.
        """
        if gate not in _READINESS_GATES:
            raise ValueError(f"unknown readiness gate: {gate}")
        was_ready = self._readiness.is_ready()
        setattr(self._readiness, gate, value)
        is_ready = self._readiness.is_ready()
        if is_ready and not was_ready:
            self._start_heartbeat()
        elif not is_ready and was_ready:
            self._stop_heartbeat()
        self.readiness_changed.emit(
            {
                "handle_open": self._readiness.handle_open,
                "imports_ok": self._readiness.imports_ok,
                "ax_trusted": self._readiness.ax_trusted,
                "engine_running": self._readiness.engine_running,
                "ready": is_ready,
            }
        )

    # ---- bound adapters: connect signals to THESE, not to lambdas. ----

    @Slot()
    def on_engine_started(self) -> None:
        self.update_readiness("engine_running", True)

    @Slot()
    def on_engine_stopped(self) -> None:
        self.update_readiness("engine_running", False)

    @Slot(bool)
    def on_ax_trusted_changed(self, trusted: bool) -> None:
        self.update_readiness("ax_trusted", trusted)

    @Slot(bool)
    def set_imports_ok(self, ok: bool) -> None:
        self.update_readiness("imports_ok", ok)

    @Slot(str)
    def _on_device_state(self, s: str) -> None:
        was_open = self._readiness.handle_open
        if s == "":
            self.update_readiness("handle_open", True)
            self.device_state.emit("")
            if not was_open:
                self.load_all()
                self._start_matrix_poll()
        elif s == "no-device":
            self.update_readiness("handle_open", False)
            if self._matrix_timer is not None:
                self._matrix_timer.stop()
            for col in sorted(self._pressed_cols):
                self.matrix_release.emit(key_id(col))
            self._pressed_cols.clear()
            self._matrix_state = ""
            self.matrix_state.emit("")
            self.device_state.emit("no-device")

    def _start_heartbeat(self) -> None:
        # MUST be called on control_thread. update_readiness enforces this
        # transitively because external callers go through queued slots.
        assert self.thread() == QThread.currentThread(), (
            "_start_heartbeat called off-thread — check signal wiring"
        )
        if self._heartbeat_timer is None:
            self._heartbeat_timer = QTimer(self)
            self._heartbeat_timer.setInterval(200)
            self._heartbeat_timer.timeout.connect(self._send_heartbeat)
        # Send one heartbeat immediately so firmware doesn't wait up to
        # 200 ms to flip from fallback to host-takeover.
        self._send_heartbeat()
        self._heartbeat_timer.start()

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.stop()

    @Slot()
    def _send_heartbeat(self) -> None:
        # send_untracked is fire-and-forget; never blocks. Even if a VIA
        # request is in flight on the IO thread, the heartbeat enqueues
        # and the IO loop drains it without waiting for a reply.
        self._io.send_untracked([0xA0, 0x01])
        self._last_heartbeat_s = time.monotonic()

    def _send_heartbeat_if_due(self) -> None:
        if not self._readiness.is_ready():
            return
        if time.monotonic() - self._last_heartbeat_s >= self.HEARTBEAT_INTERVAL_S:
            self._send_heartbeat()
