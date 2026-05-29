"""PySide6 presentation. Depends on core (constants), catalog (semantics),
model, and the two workers via signals. Never touches a HID handle."""

from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

import core
from catalog import CATALOG, render, resolve_controls
from model import Snapshot, key_id, enc_id

# control_id -> (label, slot-setter) wiring is built from device topology.
KEY_COLS = [0, 1, 2, 4]   # Key1, Key2, Key3, Knob push (col 3 = advanced)
ENCODERS = [(0, 0), (0, 1), (1, 0), (1, 1)]  # (enc, dir); ring vs inner per Task 11


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

        root = QWidget()
        self.setCentralWidget(root)
        self._v = QVBoxLayout(root)

        self._banner = QLabel("")
        self._banner.setStyleSheet("color: #b00; font-weight: bold;")
        self._v.addWidget(self._banner)

        self._build_layer_selector()
        self._build_device_widget()
        self._build_editor()
        # LED panel added in Task 13: self._build_led_panel()

        # UI → worker requests (auto-connection across threads → QUEUED,
        # because `control` lives on control_thread). EMIT these, never call.
        self.req_set_key.connect(control.set_key)
        self.req_set_encoder.connect(control.set_encoder)
        self.req_set_color.connect(control.set_color)
        self.req_set_scalar.connect(control.set_light_scalar)
        self.req_load_all.connect(control.load_all)
        self.req_save.connect(control.save)

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
            btn = QPushButton("—")
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

    # --- worker/listener slots ---
    def _on_device_state(self, state):
        self._banner.setText("DOIO not found — plug it in" if state == "no-device" else "")

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
            self._control_buttons[enc_id(enc, direction)].setText(
                render(self._snapshot.encoders[self._layer][enc][direction]))

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
