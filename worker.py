"""Control worker: owns the 0xFF60 handle, runs core calls on its own thread,
emits snapshot/ack/device-state signals. moveToThread pattern — the handle is
created in start() which runs on the worker thread."""

from PySide6.QtCore import QObject, QTimer, Signal, Slot

import core
from model import key_id, enc_id


class ControlWorker(QObject):
    snapshot_ready = Signal(object)      # Snapshot
    device_state = Signal(str)           # "" ok / "no-device"
    set_ack = Signal(object, bool)       # control_id, ok
    lighting_saved = Signal(bool)
    loading = Signal(bool)
    matrix_state = Signal(str)           # "available" / "unsupported"
    matrix_press = Signal(object)        # control_id from VIA switch_matrix_state
    matrix_release = Signal(object)      # control_id from VIA switch_matrix_state

    def __init__(self):
        super().__init__()
        self._dev = None
        self._matrix_timer = None
        self._pressed_cols: set[int] = set()
        self._matrix_state = ""

    @Slot()
    def start(self):
        self._open_and_load()

    @Slot()
    def reconnect(self):
        self._open_and_load()

    def _open_and_load(self):
        self._dev = core.open_raw()
        if self._dev is None:
            self.device_state.emit("no-device")
            return
        self.device_state.emit("")
        self._start_matrix_poll()
        self.load_all()

    @Slot()
    def load_all(self):
        if self._dev is None:
            return
        self.loading.emit(True)
        try:
            snap = core.read_all(self._dev)
        except Exception:  # noqa: BLE001 — device yanked mid-read
            self.loading.emit(False)
            self.device_state.emit("no-device")
            return
        self.loading.emit(False)
        self.snapshot_ready.emit(snap)

    @Slot(int, int, int)
    def set_key(self, layer, col, keycode):
        ok = self._guarded(lambda: core.set_key(self._dev, layer, col, keycode))
        self.set_ack.emit(key_id(col), ok)

    @Slot(int, int, int, int)
    def set_encoder(self, layer, enc, direction, keycode):
        ok = self._guarded(
            lambda: core.set_encoder(self._dev, layer, enc, direction, keycode))
        self.set_ack.emit(enc_id(enc, direction), ok)

    @Slot(int, int)
    def get_key(self, layer, col) -> int:
        if self._dev is None:
            return 0
        return core.get_key(self._dev, layer, col)

    @Slot(int, int, int)
    def set_light_scalar(self, value_id, value):
        self._guarded(lambda: core.set_light_scalar(self._dev, value_id, value))

    @Slot(int, int)
    def set_color(self, hue, sat):
        self._guarded(lambda: core.set_color(self._dev, hue, sat))

    @Slot()
    def save(self):
        self.lighting_saved.emit(
            self._guarded(lambda: core.save_lighting(self._dev)))

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
        if self._dev is None:
            return
        try:
            cols = core.pressed_cols(self._dev)
        except Exception:  # noqa: BLE001 — device yanked mid-poll
            self.device_state.emit("no-device")
            if self._matrix_timer is not None:
                self._matrix_timer.stop()
            return
        if cols is None:
            if self._matrix_state != "unsupported":
                self._matrix_state = "unsupported"
                self.matrix_state.emit("unsupported")
            if self._matrix_timer is not None:
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

    def _guarded(self, fn) -> bool:
        if self._dev is None:
            return False
        try:
            fn()
            return True
        except Exception:  # noqa: BLE001 — surface as a failed ack/device-state
            self.device_state.emit("no-device")
            return False
