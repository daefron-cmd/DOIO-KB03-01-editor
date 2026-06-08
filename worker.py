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
        fut = self._io.send_request(payload)
        try:
            return fut.result(timeout=self.REPLY_TIMEOUT_S)
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
