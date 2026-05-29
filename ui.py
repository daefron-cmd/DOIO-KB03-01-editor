"""PySide6 presentation. Depends on core (constants), catalog (semantics),
model, and the two workers via signals. Never touches a HID handle."""

from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QRadioButton, QSlider, QVBoxLayout, QWidget,
)

import core
from catalog import CATALOG, render, resolve_controls
from model import Snapshot, key_id, enc_id

# control_id -> (label, slot-setter) wiring is built from device topology.
KEY_COLS = [0, 1, 2, 4]   # Key1, Key2, Key3, Knob push (col 3 = advanced)
# (enc, dir); verified Task 11: enc 1 = outer ring, enc 0 = inner knob. Outer
# ring listed first (primary control). dir 0/1 = CCW/CW per QMK convention.
ENCODERS = [(1, 0), (1, 1), (0, 0), (0, 1)]
ENC_NAMES = {1: "Outer ring", 0: "Inner knob"}
DIR_NAMES = {0: "CCW", 1: "CW"}

# index -> name. Lighting control + all sliders verified working on hardware
# 2026-05-29 (Task 11), but the per-index effect NAMES are still best-guess and
# were not individually confirmed (cosmetic; low priority on this unit).
EFFECTS = [
    "SOLID_COLOR_OFF/NONE", "SOLID_COLOR", "GRADIENT_UP_DOWN",
    "GRADIENT_LEFT_RIGHT", "BREATHING", "BAND_SAT", "BAND_VAL",
]  # extend/correct per Task 11


class MainWindow(QMainWindow):
    # Request signals → control-worker slots. Emitting (not calling) is what
    # makes the cross-thread delivery QUEUED, so worker code runs on its own
    # thread and the HID handle is never touched from the UI thread.
    req_set_key = Signal(int, int, int)
    req_set_encoder = Signal(int, int, int, int)
    req_set_color = Signal(int, int)
    req_set_scalar = Signal(int, int)
    req_load_all = Signal()
    req_save = Signal()
    req_reconnect = Signal()

    def __init__(self, control, listener):
        super().__init__()
        self.setWindowTitle("DOIO KB03-01")
        self._control = control
        self._listener = listener
        self._snapshot: Snapshot | None = None
        self._layer = 0
        self._control_buttons: dict[tuple, QPushButton] = {}
        self._selected: tuple | None = None
        self._pending_code: dict[tuple, tuple[int, int]] = {}  # cid -> (layer, code)

        # TODO(gui): use pictures/gui_background.png (2048x2048) as the window
        # background and position the key/encoder controls over the device image
        # instead of the plain vertical layout. Consider downsizing the asset
        # (~8MB) and committing it once the layout coordinates are pinned.
        root = QWidget()
        self.setCentralWidget(root)
        self._v = QVBoxLayout(root)

        self._banner = QLabel("")
        self._banner.setStyleSheet("color: #b00; font-weight: bold;")
        self._reconnect_btn = QPushButton("Reconnect")
        self._reconnect_btn.clicked.connect(self.req_reconnect)
        self._reconnect_btn.hide()
        banner_row = QHBoxLayout()
        banner_row.addWidget(self._banner)
        banner_row.addWidget(self._reconnect_btn)
        banner_row.addStretch()
        self._v.addLayout(banner_row)

        self._build_layer_selector()
        self._build_device_widget()
        self._build_editor()
        self._build_led_panel()

        # UI → worker requests (auto-connection across threads → QUEUED,
        # because `control` lives on control_thread). EMIT these, never call.
        self.req_set_key.connect(control.set_key)
        self.req_set_encoder.connect(control.set_encoder)
        self.req_set_color.connect(control.set_color)
        self.req_set_scalar.connect(control.set_light_scalar)
        self.req_load_all.connect(control.load_all)
        self.req_save.connect(control.save)
        self.req_reconnect.connect(control.reconnect)

        # worker → UI signals
        control.device_state.connect(self._on_device_state)
        control.loading.connect(self._on_loading)
        control.snapshot_ready.connect(self._on_snapshot)
        control.set_ack.connect(self._on_set_ack)
        listener.input_event.connect(self._on_input_event)
        listener.permission_state.connect(self._on_permission_state)

    # --- builders ---
    def _build_layer_selector(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Layer:"))
        self._layer_group = QButtonGroup(self)
        for ly in range(4):
            rb = QRadioButton(str(ly))
            if ly == 0:
                rb.setChecked(True)
            rb.toggled.connect(partial(self._on_layer_pick, ly))
            self._layer_group.addButton(rb)
            row.addWidget(rb)
        row.addStretch()
        self._v.addLayout(row)

    def _build_device_widget(self):
        keys_row = QHBoxLayout()
        for col in (0, 1, 2):
            btn = QPushButton("—")
            btn.clicked.connect(partial(self._select, key_id(col)))
            self._control_buttons[key_id(col)] = btn
            keys_row.addWidget(btn)
        self._v.addLayout(keys_row)

        enc_row = QHBoxLayout()
        for enc, direction in ENCODERS:
            btn = QPushButton(f"{ENC_NAMES[enc]} {DIR_NAMES[direction]}\n—")
            btn.clicked.connect(partial(self._select, enc_id(enc, direction)))
            self._control_buttons[enc_id(enc, direction)] = btn
            enc_row.addWidget(btn)
        push = QPushButton("—")  # inner push = matrix col 4
        push.clicked.connect(partial(self._select, key_id(4)))
        self._control_buttons[key_id(4)] = push
        enc_row.addWidget(push)
        self._v.addLayout(enc_row)

        # advanced: matrix col 3 "Layers" (physical meaning confirmed in Task 11)
        adv_row = QHBoxLayout()
        adv_row.addWidget(QLabel("Advanced:"))
        adv = QPushButton("—")
        adv.setToolTip("col 3 'Layers' — overwriting may remove the device's "
                       "only physical layer-switch; the app can rewrite it back")
        adv.clicked.connect(partial(self._select, key_id(3)))
        self._control_buttons[key_id(3)] = adv
        adv_row.addWidget(adv)
        adv_row.addStretch()
        self._v.addLayout(adv_row)

    def _build_editor(self):
        self._editor_label = QLabel("Select a control to edit")
        self._v.addWidget(self._editor_label)
        self._combo = QComboBox()
        for cat, label, code in CATALOG:
            self._combo.addItem(f"[{cat}] {label}", code)
        self._combo.setEnabled(False)
        self._combo.activated.connect(self._on_pick_keycode)
        self._v.addWidget(self._combo)

    def _build_led_panel(self):
        grid = QGridLayout()
        self._effect = QComboBox()
        for i, name in enumerate(EFFECTS):
            self._effect.addItem(f"{i} — {name}", i)
        self._effect.activated.connect(
            lambda _i: self.req_set_scalar.emit(
                core.LIGHT_EFFECT, self._effect.currentData()))
        grid.addWidget(QLabel("Effect"), 0, 0)
        grid.addWidget(self._effect, 0, 1)

        self._sliders = {}
        self._pending = {}                 # value_id/"color" -> latest value
        self._tick = QTimer(self)          # ~25 Hz coalescing flush
        self._tick.setInterval(40)
        self._tick.timeout.connect(self._flush_sliders)
        self._tick.start()

        specs = [("Brightness", core.LIGHT_BRIGHTNESS, 200),
                 ("Speed", core.LIGHT_SPEED, 255),
                 ("Hue", "hue", 255),
                 ("Sat", "sat", 255)]
        for r, (name, key, maximum) in enumerate(specs, start=1):
            s = QSlider(Qt.Horizontal)
            s.setMaximum(maximum)          # brightness capped at 200 (render cap)
            s.valueChanged.connect(partial(self._on_slider, key))
            self._sliders[key] = s
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(s, r, 1)

        save = QPushButton("Save to keyboard")
        save.clicked.connect(self.req_save)   # signal→slot across threads = queued
        grid.addWidget(save, len(specs) + 1, 1)
        self._v.addLayout(grid)

    def _on_slider(self, key, value):
        self._pending[key] = value         # coalesce to latest; flushed at 25 Hz

    def _flush_sliders(self):
        if not self._pending:
            return
        pend = self._pending
        self._pending = {}
        if "hue" in pend or "sat" in pend:
            hue = self._sliders["hue"].value()
            sat = self._sliders["sat"].value()
            self.req_set_color.emit(hue, sat)   # both channels, one command
        for key, value in pend.items():
            if key in (core.LIGHT_BRIGHTNESS, core.LIGHT_SPEED):
                self.req_set_scalar.emit(key, value)

    # --- worker/listener slots ---
    def _on_device_state(self, state):
        if state == "no-device":
            self._banner.setText("DOIO not found — plug it in")
            self._reconnect_btn.show()
        else:
            self._banner.setText("")
            self._reconnect_btn.hide()

    def _on_permission_state(self, state):
        if state == "input-monitoring-denied":
            self._banner.setText("Grant Input Monitoring in System Settings to see live presses")

    def _on_loading(self, busy):
        if busy:
            self._banner.setText("Reading keyboard…")
        elif self._banner.text() == "Reading keyboard…":
            self._banner.setText("")

    def _on_snapshot(self, snap: Snapshot):
        self._snapshot = snap
        self._effect.setCurrentIndex(min(snap.effect, self._effect.count() - 1))
        inits = {core.LIGHT_BRIGHTNESS: min(snap.brightness, 200),
                 core.LIGHT_SPEED: snap.speed, "hue": snap.hue, "sat": snap.sat}
        for key, value in inits.items():
            s = self._sliders[key]
            s.blockSignals(True)
            s.setValue(value)
            s.blockSignals(False)
        self._refresh_controls()

    def _on_layer_pick(self, ly, checked):
        if checked:
            self._layer = ly
            self._refresh_controls()

    def _refresh_controls(self):
        if self._snapshot is None:
            return
        for col in (0, 1, 2, 3, 4):
            self._control_buttons[key_id(col)].setText(
                render(self._snapshot.keymap[self._layer][col]))
        for enc, direction in ENCODERS:
            label = f"{ENC_NAMES[enc]} {DIR_NAMES[direction]}"
            mapping = render(self._snapshot.encoders[self._layer][enc][direction])
            self._control_buttons[enc_id(enc, direction)].setText(
                f"{label}\n{mapping}")

    def _select(self, cid):
        self._selected = cid
        self._editor_label.setText(f"Editing {cid}")
        self._combo.setEnabled(True)

    def _on_pick_keycode(self, _index):
        if self._selected is None:
            return
        code = self._combo.currentData()
        cid = self._selected
        # carry (layer, code) with the request so a later combo/layer change
        # can't corrupt the snapshot update when the queued ack returns.
        self._pending_code[cid] = (self._layer, code)
        if cid[0] == "key":
            self.req_set_key.emit(self._layer, cid[1], code)
        else:
            self.req_set_encoder.emit(self._layer, cid[1], cid[2], code)

    def _on_set_ack(self, cid, ok):
        pending = self._pending_code.pop(cid, None)
        if not ok or pending is None:
            self._banner.setText(f"Write failed for {cid} — resyncing")
            # v1: rare write-failure resyncs via full load_all() (see plan notes).
            # worker.get_key/get_encoder exist as the hook for targeted resync.
            self.req_load_all.emit()
            return
        layer, code = pending  # success → local snapshot is source of truth
        if self._snapshot is None:
            return
        if cid[0] == "key":
            self._snapshot.keymap[layer][cid[1]] = code
        else:
            self._snapshot.encoders[layer][cid[1]][cid[2]] = code
        if layer == self._layer:
            self._refresh_controls()

    def _on_input_event(self, iface_kind, mods, keycodes):
        if self._snapshot is None:
            return
        for cid in resolve_controls(self._snapshot, iface_kind, mods, keycodes):
            self._flash(cid)

    def _flash(self, cid):
        btn = self._control_buttons.get(cid)
        if btn is None:
            return
        btn.setStyleSheet("background: #6cf;")
        QTimer.singleShot(150, lambda: btn.setStyleSheet(""))
