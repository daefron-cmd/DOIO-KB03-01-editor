"""PySide6 presentation. Depends on core (constants), catalog (semantics),
model, and the two workers via signals. Never touches a HID handle."""

from functools import partial
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QGraphicsDropShadowEffect, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton, QRadioButton,
    QSizePolicy, QSlider, QVBoxLayout, QWidget,
)
import re

import core
from catalog import CATALOG, render, resolve_controls
from inferred_layer import InferredLayerState
from model import LightingState, Snapshot, key_id, enc_id

ROOT = Path(__file__).resolve().parent

# control_id -> (label, slot-setter) wiring is built from device topology.
KEY_COLS = [0, 1, 2, 4]   # Key1, Key2, Key3, Knob push (col 3 = advanced)
# (enc, dir); verified Task 11: enc 1 = outer ring, enc 0 = inner knob. Outer
# ring listed first (primary control). dir 0/1 = CCW/CW per QMK convention.
ENCODERS = [(1, 0), (1, 1), (0, 0), (0, 1)]
ENC_NAMES = {1: "Outer ring", 0: "Inner knob"}
DIR_NAMES = {0: "CCW", 1: "CW"}

# QMK RGB Matrix enum names. Verified on this KB03 with
# scripts/probe_led_effects.py: indices 0..31 read back as requested.
EFFECTS = [
    "RGB_MATRIX_NONE",
    "RGB_MATRIX_SOLID_COLOR",
    "RGB_MATRIX_ALPHAS_MODS",
    "RGB_MATRIX_GRADIENT_UP_DOWN",
    "RGB_MATRIX_GRADIENT_LEFT_RIGHT",
    "RGB_MATRIX_BREATHING",
    "RGB_MATRIX_BAND_SAT",
    "RGB_MATRIX_BAND_VAL",
    "RGB_MATRIX_BAND_PINWHEEL_SAT",
    "RGB_MATRIX_BAND_PINWHEEL_VAL",
    "RGB_MATRIX_BAND_SPIRAL_SAT",
    "RGB_MATRIX_BAND_SPIRAL_VAL",
    "RGB_MATRIX_CYCLE_ALL",
    "RGB_MATRIX_CYCLE_LEFT_RIGHT",
    "RGB_MATRIX_CYCLE_UP_DOWN",
    "RGB_MATRIX_CYCLE_OUT_IN",
    "RGB_MATRIX_CYCLE_OUT_IN_DUAL",
    "RGB_MATRIX_RAINBOW_MOVING_CHEVRON",
    "RGB_MATRIX_CYCLE_PINWHEEL",
    "RGB_MATRIX_CYCLE_SPIRAL",
    "RGB_MATRIX_DUAL_BEACON",
    "RGB_MATRIX_RAINBOW_BEACON",
    "RGB_MATRIX_RAINBOW_PINWHEELS",
    "RGB_MATRIX_FLOWER_BLOOMING",
    "RGB_MATRIX_RAINDROPS",
    "RGB_MATRIX_JELLYBEAN_RAINDROPS",
    "RGB_MATRIX_HUE_BREATHING",
    "RGB_MATRIX_HUE_PENDULUM",
    "RGB_MATRIX_HUE_WAVE",
    "RGB_MATRIX_PIXEL_FRACTAL",
    "RGB_MATRIX_PIXEL_FLOW",
    "RGB_MATRIX_PIXEL_RAIN",
]

# Photo-calibrated LED color samples from hue 0..255 in steps of 17 at
# saturation 255. These intentionally model the KB03 LEDs/case diffusion rather
# than an ideal HSV color wheel.
LED_HUE_SAMPLES = [
    (0, "#ff2a11"),
    (17, "#ff2a7a"),
    (34, "#d02cff"),
    (51, "#9b2cff"),
    (68, "#522dff"),
    (85, "#1f54ff"),
    (102, "#00a4ff"),
    (119, "#00d9ff"),
    (136, "#00d9d0"),
    (153, "#00d584"),
    (170, "#1fd556"),
    (187, "#83df3d"),
    (204, "#d8ec3f"),
    (221, "#ffd03a"),
    (238, "#ff8123"),
    (255, "#ff2a11"),
]


class RoundIndicator(QWidget):
    def __init__(self, color: str, border: str, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._border = QColor(border)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_colors(self, color: str, border: str):
        self._color = QColor(color)
        self._border = QColor(border)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen_width = max(1, round(min(self.width(), self.height()) * 0.12))
        painter.setPen(QPen(self._border, pen_width))
        painter.setBrush(self._color)
        inset = pen_width / 2
        painter.drawEllipse(self.rect().adjusted(
            round(inset), round(inset), -round(inset), -round(inset)))


class DevicePanel(QWidget):
    """Square image panel with controls positioned in source-image coordinates."""

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(image_path)
        self._image = QLabel(self)
        self._image.hide()
        self._image.setScaledContents(True)
        self._controls: dict[tuple, tuple[QPushButton, QRect, QRect]] = {}
        self._indicators: dict[str, tuple[RoundIndicator, QRect]] = {}
        self._active: tuple | None = None
        self.setObjectName("devicePanel")
        self.setMinimumSize(560, 560)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def has_image(self) -> bool:
        return not self._pixmap.isNull()

    def add_control(
        self,
        cid: tuple,
        source_rect: QRect,
        text: str,
        on_click,
        target_rect: QRect | None = None,
    ):
        btn = QPushButton(text, self)
        btn.clicked.connect(on_click)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("deviceControl", True)
        btn.setProperty("keycapControl", True)
        btn.setProperty("darkControl", False)
        halo = QGraphicsDropShadowEffect(btn)
        halo.setBlurRadius(3.0)
        halo.setColor(QColor(255, 252, 235, 225))
        halo.setOffset(0, 0)
        btn.setGraphicsEffect(halo)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._controls[cid] = (btn, source_rect, target_rect or source_rect)
        self._apply_button_state(cid)
        self._layout_children()
        return btn

    def add_indicator(self, name: str, source_rect: QRect):
        dot = RoundIndicator("#d33", "#661", self)
        self._indicators[name] = (dot, source_rect)
        self._layout_children()
        return dot

    def set_active(self, cid: tuple | None):
        old = self._active
        self._active = cid
        if old in self._controls:
            self._apply_button_state(old)
        if cid in self._controls:
            self._apply_button_state(cid)

    def flash(self, cid: tuple, duration_ms: int = 150):
        if cid not in self._controls:
            return
        self._apply_button_state(cid, flash=True)
        QTimer.singleShot(duration_ms, lambda: self._apply_button_state(cid))

    def resizeEvent(self, _event):
        self._layout_children()

    def paintEvent(self, _event):
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        image_rect = self._image_rect()
        painter.drawPixmap(image_rect, self._pixmap)
        self._draw_leaders(painter)

    def _layout_children(self):
        if self._pixmap.isNull():
            return
        for btn, src, _target in self._controls.values():
            btn.setGeometry(self._scaled_rect(src, min_width=88, min_height=42))
            btn.raise_()
        for dot, src in self._indicators.values():
            dot.setGeometry(self._scaled_rect(src, min_width=10, min_height=10))
            dot.raise_()
        self.update()

    def _apply_button_state(self, cid: tuple, flash: bool = False):
        btn, _src, _target = self._controls[cid]
        btn.setProperty("active", cid == self._active)
        btn.setProperty("flash", flash)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _image_rect(self) -> QRect:
        side = min(self.width(), self.height())
        return QRect((self.width() - side) // 2, (self.height() - side) // 2, side, side)

    def _scaled_rect(self, src: QRect, min_width: int, min_height: int) -> QRect:
        image_rect = self._image_rect()
        scale = image_rect.width() / self._pixmap.width()
        return QRect(
            image_rect.x() + round(src.x() * scale),
            image_rect.y() + round(src.y() * scale),
            max(min_width, round(src.width() * scale)),
            max(min_height, round(src.height() * scale)),
        )

    def _scaled_center(self, src: QRect) -> QPoint:
        image_rect = self._image_rect()
        scale = image_rect.width() / self._pixmap.width()
        return QPoint(
            image_rect.x() + round(src.center().x() * scale),
            image_rect.y() + round(src.center().y() * scale),
        )

    def _draw_leaders(self, painter: QPainter):
        shadow = QPen(QColor(255, 249, 224, 185), 4)
        shadow.setCapStyle(Qt.RoundCap)
        ink = QPen(QColor(42, 38, 28, 205), 2)
        ink.setCapStyle(Qt.RoundCap)
        for btn, _src, target in self._controls.values():
            label = btn.geometry()
            start = self._leader_start(label, self._scaled_center(target))
            end = self._scaled_center(target)
            painter.setPen(shadow)
            painter.drawLine(start, end)
            painter.setPen(ink)
            painter.drawLine(start, end)
            painter.setBrush(QColor(42, 38, 28, 210))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(end, 3, 3)

    def _leader_start(self, label: QRect, target: QPoint) -> QPoint:
        center = label.center()
        dx = target.x() - center.x()
        dy = target.y() - center.y()
        if abs(dx) >= abs(dy):
            x = label.right() if dx > 0 else label.left()
            return QPoint(x, center.y())
        y = label.bottom() if dy > 0 else label.top()
        return QPoint(center.x(), y)


_APP_STYLE = """
QWidget {
    background: #f4f1e8;
    color: #201f1c;
    font-size: 13px;
}
QMainWindow {
    background: #f4f1e8;
}
QFrame#topBar,
QFrame#inspectorPanel {
    background: #fffdf7;
    border: 1px solid #d6d0c3;
    border-radius: 8px;
}
QFrame#section {
    background: transparent;
    border-top: 1px solid #ddd5c8;
}
QLabel#title {
    color: #151513;
    font-size: 18px;
    font-weight: 800;
}
QLabel#subtle,
QLabel#sectionLabel,
QLabel#valueLabel {
    color: #686257;
}
QLabel#sectionLabel {
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
}
QLabel#banner {
    color: #7a2e16;
    font-weight: 700;
}
QLabel#layerStatus {
    color: #3d3a35;
    font-weight: 700;
}
QLabel#lightingStatus {
    color: #686257;
    font-size: 12px;
    font-weight: 700;
}
QLabel#colorSwatch {
    background: #222;
    border: 1px solid #746b5d;
    border-radius: 7px;
    min-height: 24px;
}
QPushButton {
    background: #262521;
    border: 1px solid #141411;
    border-radius: 7px;
    color: #fffaf0;
    font-weight: 700;
    padding: 8px 12px;
}
QPushButton:hover {
    background: #343229;
}
QPushButton:pressed {
    background: #161512;
}
QPushButton#secondaryButton {
    background: #fffdf8;
    border: 1px solid #bdb4a6;
    color: #27231d;
}
QPushButton#secondaryButton:hover {
    background: #f3ecdd;
}
QPushButton[deviceControl="true"] {
    background: rgba(255, 247, 216, 128);
    border: 1px solid transparent;
    border-radius: 6px;
    color: #11100d;
    font-size: 12px;
    font-weight: 900;
    padding: 2px;
}
QPushButton[deviceControl="true"][keycapControl="true"] {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #fff7dc,
        stop:0.55 #efe2bd,
        stop:1 #d5c39a
    );
    border: 1px solid rgba(82, 70, 48, 115);
    color: #171511;
    font-size: 13px;
    letter-spacing: 0;
    padding: 0;
}
QPushButton[deviceControl="true"][darkControl="true"] {
    background: rgba(18, 17, 14, 58);
    color: #fff1c6;
}
QPushButton[deviceControl="true"]:hover {
    background: rgba(255, 247, 216, 170);
    border: 1px solid rgba(22, 92, 96, 185);
}
QPushButton[deviceControl="true"][keycapControl="true"]:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #fffbe9,
        stop:0.58 #f4e8c8,
        stop:1 #dac89d
    );
    border: 1px solid rgba(22, 92, 96, 150);
}
QPushButton[deviceControl="true"][darkControl="true"]:hover {
    background: rgba(18, 17, 14, 95);
}
QPushButton[deviceControl="true"][active="true"] {
    background: rgba(255, 224, 139, 132);
    border: 2px solid rgba(191, 104, 18, 220);
}
QPushButton[deviceControl="true"][keycapControl="true"][active="true"] {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #fff8df,
        stop:0.58 #f2dfac,
        stop:1 #cfb26f
    );
    border: 2px solid rgba(191, 104, 18, 215);
}
QPushButton[deviceControl="true"][darkControl="true"][active="true"] {
    background: rgba(191, 104, 18, 112);
    color: #fff8dc;
}
QPushButton[deviceControl="true"][flash="true"] {
    background: rgba(103, 218, 229, 82);
    border: 2px solid rgba(0, 93, 106, 230);
    color: #071719;
}
QComboBox {
    background: #fffdf8;
    border: 1px solid #bdb4a6;
    border-radius: 7px;
    min-height: 34px;
    padding: 4px 10px;
}
QComboBox:disabled {
    color: #878176;
    background: #ebe6dc;
}
QRadioButton {
    spacing: 6px;
    font-weight: 700;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
}
QSlider::groove:horizontal {
    background: #d8d0c2;
    border-radius: 3px;
    height: 6px;
}
QSlider::sub-page:horizontal {
    background: #257b83;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #fffdf8;
    border: 2px solid #257b83;
    border-radius: 8px;
    margin: -6px 0;
    width: 16px;
}
"""

_LAYER_LED_COLORS = {
    0: ("#ff3030", "#7a0000"),
    1: ("#39d353", "#116322"),
    2: ("#2f81f7", "#0b3d91"),
    3: ("#f5f5f0", "#8a8a80"),
}

_LAYER_NAMES = {
    0: "Layer 0 / red",
    1: "Layer 1 / green",
    2: "Layer 2 / blue",
    3: "Layer 3 / white",
}


def _mix(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def calibrated_led_color(hue: int, sat: int, brightness: int) -> QColor:
    hue = max(0, min(255, hue))
    sat = max(0, min(255, sat))
    brightness = max(0, min(200, brightness))
    # The KB03 hue wheel runs opposite the photographed sample order on each
    # side of the midpoint: 0, 128 and 255 line up, but 64 behaves like 192.
    lookup_hue = 255 if hue == 255 else (256 - hue) % 256
    samples = LED_HUE_SAMPLES
    lo_h, lo_hex = samples[0]
    hi_h, hi_hex = samples[-1]
    for index in range(len(samples) - 1):
        if samples[index][0] <= lookup_hue <= samples[index + 1][0]:
            lo_h, lo_hex = samples[index]
            hi_h, hi_hex = samples[index + 1]
            break
    span = max(1, hi_h - lo_h)
    t = (lookup_hue - lo_h) / span
    lo = QColor(lo_hex)
    hi = QColor(hi_hex)
    r = _mix(lo.red(), hi.red(), t)
    g = _mix(lo.green(), hi.green(), t)
    b = _mix(lo.blue(), hi.blue(), t)

    # Desaturate toward the photographed "white LED through smoky case" tone,
    # then apply the same 0..200 brightness cap the hardware UI uses.
    white = QColor("#fff7e5")
    sat_t = sat / 255
    value_t = brightness / 200
    return QColor(
        round(_mix(white.red(), r, sat_t) * value_t),
        round(_mix(white.green(), g, sat_t) * value_t),
        round(_mix(white.blue(), b, sat_t) * value_t),
    )


_LABEL_SPLIT_RE = re.compile(r"^(.+?)\s\s+\((.+)\)\s*$")


def _split_catalog_label(label: str) -> tuple[str | None, str]:
    """Split a catalog label of the form 'name  (qmk)' into (name, qmk).

    Falls back to (None, label) for entries where the label IS the QMK
    identifier (modifiers like 'KC_LCTL', layer ops like 'MO(1)', lighting
    keycodes like 'RGB_TOG').
    """
    m = _LABEL_SPLIT_RE.match(label)
    if m:
        return m.group(1), m.group(2)
    return None, label


class KeycodePickerDialog(QDialog):
    """Modal browser+search for the keycode catalog.

    Left: category list ("All" + each catalog category).
    Right: items, filtered by AND of (selected category, search query).
    Search matches case-insensitively against the name, qmk code, category,
    and 0xHEX, so 'vol', 'F7', 'MO', and '0x004F' all work — regardless of
    which display toggles are on.
    Top toggles ("Name" / "QMK code" / "Hex") choose what's *displayed* on
    each row; the choice persists for the rest of the session.
    Double-click or Enter on a single match accepts; the chosen keycode is
    available via `selected_code()` after `exec()` returns Accepted.
    """

    # Persisted across dialog instances within the process.
    _show_name = True
    _show_qmk = True
    _show_hex = True

    def __init__(self, current: int | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick a keycode")
        self.setModal(True)
        self.resize(640, 480)

        # Pre-split each catalog label once; both render and search use it.
        self._entries: list[tuple[str, str | None, str, int]] = [
            (cat, *_split_catalog_label(label), code)
            for cat, label, code in CATALOG
        ]
        self._categories = sorted({cat for cat, _, _, _ in self._entries})
        self._selected_code: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Search (name, category, or 0x… hex — e.g. vol, F7, MO, 0x004F)")
        self._search.textChanged.connect(self._refresh_items)
        self._search.returnPressed.connect(self._on_search_enter)
        outer.addWidget(self._search)

        toggles = QHBoxLayout()
        toggles.setSpacing(12)
        toggles.addWidget(QLabel("Show:"))
        self._cb_name = QCheckBox("Name")
        self._cb_qmk = QCheckBox("QMK code")
        self._cb_hex = QCheckBox("Hex")
        self._cb_name.setChecked(KeycodePickerDialog._show_name)
        self._cb_qmk.setChecked(KeycodePickerDialog._show_qmk)
        self._cb_hex.setChecked(KeycodePickerDialog._show_hex)
        for cb in (self._cb_name, self._cb_qmk, self._cb_hex):
            cb.toggled.connect(self._on_toggle_changed)
            toggles.addWidget(cb)
        toggles.addStretch()
        outer.addLayout(toggles)

        body = QHBoxLayout()
        body.setSpacing(10)

        self._cat_list = QListWidget()
        self._cat_list.setMaximumWidth(140)
        self._cat_list.addItem("All")
        for cat in self._categories:
            self._cat_list.addItem(cat)
        self._cat_list.currentRowChanged.connect(self._refresh_items)
        body.addWidget(self._cat_list)

        self._item_list = QListWidget()
        self._item_list.itemDoubleClicked.connect(lambda _: self._accept_current())
        self._item_list.currentRowChanged.connect(self._update_ok_enabled)
        body.addWidget(self._item_list, stretch=1)

        outer.addLayout(body, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_current)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        outer.addWidget(buttons)

        # Pre-select the category that contains the current code, if any.
        initial_row = 0
        if current is not None:
            for i, cat in enumerate(self._categories, start=1):
                if any(c == current and cat_ == cat
                       for cat_, _, _, c in self._entries):
                    initial_row = i
                    break
        self._cat_list.setCurrentRow(initial_row)
        self._refresh_items()
        if current is not None:
            self._select_code(current)
        self._search.setFocus()

    def _on_toggle_changed(self, _checked: bool) -> None:
        KeycodePickerDialog._show_name = self._cb_name.isChecked()
        KeycodePickerDialog._show_qmk = self._cb_qmk.isChecked()
        KeycodePickerDialog._show_hex = self._cb_hex.isChecked()
        self._refresh_items()

    def _format_entry(self, name: str | None, qmk: str, code: int) -> str:
        parts: list[str] = []
        if KeycodePickerDialog._show_name and name is not None:
            parts.append(name)
        if KeycodePickerDialog._show_qmk:
            parts.append(qmk)
        if KeycodePickerDialog._show_hex:
            parts.append(f"0x{code:04X}")
        return "   ·  ".join(parts)

    def _refresh_items(self) -> None:
        query = self._search.text().strip().lower()
        cat_idx = self._cat_list.currentRow()
        # When the user is searching, treat the category filter as global so a
        # leftover sidebar selection can't hide an obvious match.
        chosen_cat = (None if query or cat_idx <= 0
                      else self._categories[cat_idx - 1])
        self._cat_list.setEnabled(not query)

        self._item_list.clear()
        for cat, name, qmk, code in self._entries:
            if chosen_cat and cat != chosen_cat:
                continue
            # Search always looks at every searchable facet, even when the
            # corresponding display toggle is off.
            hay = f"{cat} {name or ''} {qmk} 0x{code:04x}".lower()
            if query and query not in hay:
                continue
            item = QListWidgetItem(self._format_entry(name, qmk, code))
            item.setData(Qt.UserRole, code)
            self._item_list.addItem(item)
        if self._item_list.count() and self._item_list.currentRow() < 0:
            self._item_list.setCurrentRow(0)
        self._update_ok_enabled()

    def _update_ok_enabled(self) -> None:
        self._ok_button.setEnabled(self._item_list.currentRow() >= 0)

    def _select_code(self, code: int) -> None:
        for row in range(self._item_list.count()):
            if self._item_list.item(row).data(Qt.UserRole) == code:
                self._item_list.setCurrentRow(row)
                self._item_list.scrollToItem(self._item_list.item(row))
                return

    def _on_search_enter(self) -> None:
        # Enter on a single match accepts immediately; otherwise jump into
        # the result list so arrow keys take over.
        if self._item_list.count() == 1:
            self._item_list.setCurrentRow(0)
            self._accept_current()
        elif self._item_list.count():
            self._item_list.setFocus()

    def _accept_current(self) -> None:
        row = self._item_list.currentRow()
        if row < 0:
            return
        self._selected_code = self._item_list.item(row).data(Qt.UserRole)
        self.accept()

    def selected_code(self) -> int | None:
        return self._selected_code


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

    def __init__(self, control, listener, *,
                 scroll_engine=None, imports_ok: bool = True,
                 ax_trusted_initial: bool = True,
                 config=None, config_path=None):
        super().__init__()
        self.setWindowTitle("DOIO KB03-01")
        self._control = control
        self._listener = listener
        self._scroll_engine = scroll_engine
        self._scroll_config = config
        self._scroll_config_path = config_path
        self._imports_ok = imports_ok
        self._ax_trusted = ax_trusted_initial
        self.scroll_panel = None  # set by _build_scroll_panel; public for main.py
        self._snapshot: Snapshot | None = None
        self._layer = 0
        self._inferred_layer = InferredLayerState(layer_count=4)
        self._control_buttons: dict[tuple, QPushButton] = {}
        self._selected: tuple | None = None
        self._pending_code: dict[tuple, tuple[int, int]] = {}  # cid -> (layer, code)
        self._device_state = ""
        self._permission_state = ""
        self._matrix_state = ""
        self._is_loading = False
        self._saved_lighting: LightingState | None = None
        self._lighting: LightingState | None = None
        self._lighting_saving = False

        self.setMinimumSize(1060, 720)
        root = QWidget()
        root.setStyleSheet(_APP_STYLE)
        self.setCentralWidget(root)
        self._v = QVBoxLayout(root)
        self._v.setContentsMargins(16, 14, 16, 16)
        self._v.setSpacing(12)

        self._build_header()

        body = QHBoxLayout()
        body.setSpacing(14)
        self._v.addLayout(body, stretch=1)

        self._workspace = QWidget()
        self._workspace_v = QVBoxLayout(self._workspace)
        self._workspace_v.setContentsMargins(0, 0, 0, 0)
        self._workspace_v.setSpacing(10)
        body.addWidget(self._workspace, stretch=1)

        self._inspector = QFrame()
        self._inspector.setObjectName("inspectorPanel")
        self._inspector.setMinimumWidth(340)
        self._inspector.setMaximumWidth(420)
        self._inspector_v = QVBoxLayout(self._inspector)
        self._inspector_v.setContentsMargins(16, 14, 16, 16)
        self._inspector_v.setSpacing(14)
        body.addWidget(self._inspector)

        self._build_device_widget()
        self._build_layer_selector()
        self._build_editor()
        self._build_led_panel()
        self._inspector_v.addStretch()
        self._set_layer_led(0)
        self._connect_workers(control, listener)

    def _build_header(self):
        header = QFrame()
        header.setObjectName("topBar")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        title = QLabel("DOIO KB03-01")
        title.setObjectName("title")
        subtitle = QLabel("Layer map, live input, and RGB matrix")
        subtitle.setObjectName("subtle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        row.addLayout(title_block)
        row.addStretch()

        self._banner = QLabel("")
        self._banner.setObjectName("banner")
        self._reconnect_btn = QPushButton("Reconnect")
        self._reconnect_btn.clicked.connect(self.req_reconnect)
        self._reconnect_btn.hide()
        row.addWidget(self._banner)
        row.addWidget(self._reconnect_btn)
        self._v.addWidget(header)

    def _connect_workers(self, control, listener):
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
        control.lighting_saved.connect(self._on_lighting_saved)
        control.matrix_state.connect(self._on_matrix_state)
        control.matrix_press.connect(self._on_matrix_press)
        control.matrix_release.connect(self._on_matrix_release)
        listener.input_event.connect(self._on_input_event)
        listener.permission_state.connect(self._on_permission_state)

    # --- builders ---
    def _build_layer_selector(self):
        self._add_section_label("Layer")
        row = QHBoxLayout()
        row.setSpacing(10)
        self._layer_group = QButtonGroup(self)
        self._layer_buttons = []
        for ly in range(4):
            rb = QRadioButton(str(ly))
            if ly == 0:
                rb.setChecked(True)
            rb.toggled.connect(partial(self._on_layer_pick, ly))
            self._layer_group.addButton(rb)
            self._layer_buttons.append(rb)
            row.addWidget(rb)
        row.addStretch()
        self._inspector_v.addLayout(row)
        self._layer_status = QLabel("")
        self._layer_status.setObjectName("layerStatus")
        self._inspector_v.addWidget(self._layer_status)

    def _build_device_widget(self):
        self._device_panel = DevicePanel(str(ROOT / "pictures" / "gui_background.png"))
        if not self._device_panel.has_image():
            self._banner.setText("Missing pictures/gui_background.png")

        # Source rectangles are in the 2048x2048 artwork coordinate space.
        key_targets = {
            key_id(0): QRect(694, 546, 150, 92),
            key_id(1): QRect(954, 546, 150, 92),
            key_id(2): QRect(1214, 546, 150, 92),
            key_id(4): QRect(972, 986, 155, 110),  # inner knob push
        }
        key_labels = {
            key_id(0): QRect(350, 225, 190, 92),
            key_id(1): QRect(929, 150, 190, 92),
            key_id(2): QRect(1508, 225, 190, 92),
            key_id(4): QRect(929, 1608, 190, 92),
        }
        for cid, label_rect in key_labels.items():
            btn = self._device_panel.add_control(
                cid, label_rect, "—", partial(self._select, cid),
                target_rect=key_targets[cid])
            self._control_buttons[cid] = btn

        encoder_targets = {
            enc_id(1, 0): QRect(746, 1128, 190, 76),
            enc_id(1, 1): QRect(1132, 1128, 190, 76),
            enc_id(0, 0): QRect(878, 908, 160, 70),
            enc_id(0, 1): QRect(1084, 908, 160, 70),
        }
        encoder_labels = {
            enc_id(0, 0): QRect(330, 805, 220, 88),
            enc_id(0, 1): QRect(1498, 805, 220, 88),
            enc_id(1, 0): QRect(330, 1190, 220, 88),
            enc_id(1, 1): QRect(1498, 1190, 220, 88),
        }
        for cid, label_rect in encoder_labels.items():
            enc, direction = cid[1], cid[2]
            text = f"{ENC_NAMES[enc]} {DIR_NAMES[direction]}\n—"
            btn = self._device_panel.add_control(
                cid, label_rect, text, partial(self._select, cid),
                target_rect=encoder_targets[cid])
            self._control_buttons[cid] = btn

        self._layer_led = self._device_panel.add_indicator(
            "layer", QRect(664, 802, 50, 50))
        self._workspace_v.addWidget(self._device_panel, stretch=1)

    def _build_editor(self):
        self._add_section_label("Assignment")
        self._editor_label = QLabel("Select a control to edit")
        self._editor_label.setWordWrap(True)
        self._inspector_v.addWidget(self._editor_label)
        self._picker_btn = QPushButton("—")
        self._picker_btn.setEnabled(False)
        self._picker_btn.clicked.connect(self._open_picker)
        self._inspector_v.addWidget(self._picker_btn)
        self._current_pick: int | None = None

    def _build_led_panel(self):
        self._add_section_label("RGB Matrix")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self._effect = QComboBox()
        for i, name in enumerate(EFFECTS):
            self._effect.addItem(f"{i} — {name}", i)
        self._effect.activated.connect(self._on_effect_pick)
        grid.addWidget(QLabel("Effect"), 0, 0)
        grid.addWidget(self._effect, 0, 1, 1, 2)

        self._sliders = {}
        self._slider_values = {}
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
            value = QLabel("0")
            value.setObjectName("valueLabel")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setMinimumWidth(30)
            self._slider_values[key] = value
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(s, r, 1)
            grid.addWidget(value, r, 2)

        self._color_swatch = QLabel("")
        self._color_swatch.setObjectName("colorSwatch")
        grid.addWidget(QLabel("Preview"), len(specs) + 1, 0)
        grid.addWidget(self._color_swatch, len(specs) + 1, 1, 1, 2)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._revert_lighting_btn = QPushButton("Revert")
        self._revert_lighting_btn.setObjectName("secondaryButton")
        self._revert_lighting_btn.clicked.connect(self._revert_lighting)
        self._save_lighting_btn = QPushButton("Save lighting")
        self._save_lighting_btn.clicked.connect(self._save_lighting)
        actions.addWidget(self._revert_lighting_btn)
        actions.addWidget(self._save_lighting_btn)
        grid.addLayout(actions, len(specs) + 2, 1, 1, 2)

        self._lighting_status = QLabel("Lighting not loaded")
        self._lighting_status.setObjectName("lightingStatus")
        self._lighting_status.setWordWrap(True)
        grid.addWidget(self._lighting_status, len(specs) + 3, 0, 1, 3)
        self._inspector_v.addLayout(grid)
        self._refresh_lighting_ui()

    def _add_section_label(self, text: str):
        if self._inspector_v.count():
            rule = QFrame()
            rule.setObjectName("section")
            rule.setFixedHeight(1)
            self._inspector_v.addWidget(rule)
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        self._inspector_v.addWidget(label)

    def _on_slider(self, key, value):
        self._slider_values[key].setText(str(value))
        if self._lighting is not None:
            self._lighting = self._lighting_with(key, value)
            self._refresh_lighting_ui()
        self._pending[key] = value         # coalesce to latest; flushed at 25 Hz

    def _on_effect_pick(self, _index):
        effect = self._effect.currentData()
        if self._lighting is not None:
            self._lighting = self._lighting_with("effect", effect)
            self._refresh_lighting_ui()
        self.req_set_scalar.emit(core.LIGHT_EFFECT, effect)

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

    def _lighting_with(self, key, value) -> LightingState:
        state = self._lighting
        if state is None:
            state = LightingState(0, 0, 0, 0, 0)
        values = {
            "brightness": state.brightness,
            "effect": state.effect,
            "speed": state.speed,
            "hue": state.hue,
            "sat": state.sat,
        }
        if key == core.LIGHT_BRIGHTNESS:
            values["brightness"] = value
        elif key == core.LIGHT_SPEED:
            values["speed"] = value
        else:
            values[key] = value
        return LightingState(**values)

    def _save_lighting(self):
        if self._lighting is None or self._lighting_saving:
            return
        self._lighting_saving = True
        self._refresh_lighting_ui()
        self.req_save.emit()   # signal→slot across threads = queued

    def _revert_lighting(self):
        if self._saved_lighting is None:
            return
        self._apply_lighting(self._saved_lighting, live_preview=True)

    def _apply_lighting(self, state: LightingState, live_preview: bool):
        self._lighting = state
        effect_index = min(state.effect, self._effect.count() - 1)
        self._effect.blockSignals(True)
        self._effect.setCurrentIndex(effect_index)
        self._effect.blockSignals(False)
        values = {
            core.LIGHT_BRIGHTNESS: min(state.brightness, 200),
            core.LIGHT_SPEED: state.speed,
            "hue": state.hue,
            "sat": state.sat,
        }
        for key, value in values.items():
            slider = self._sliders[key]
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            self._slider_values[key].setText(str(value))
        if live_preview:
            self.req_set_scalar.emit(core.LIGHT_EFFECT, state.effect)
            self.req_set_scalar.emit(core.LIGHT_BRIGHTNESS, min(state.brightness, 200))
            self.req_set_scalar.emit(core.LIGHT_SPEED, state.speed)
            self.req_set_color.emit(state.hue, state.sat)
        self._refresh_lighting_ui()

    def _refresh_lighting_ui(self):
        if not hasattr(self, "_lighting_status"):
            return
        loaded = self._lighting is not None
        dirty = loaded and self._lighting != self._saved_lighting
        self._save_lighting_btn.setEnabled(loaded and dirty and not self._lighting_saving)
        self._revert_lighting_btn.setEnabled(loaded and dirty and not self._lighting_saving)
        if self._lighting_saving:
            self._save_lighting_btn.setText("Saving...")
            self._lighting_status.setText("Saving lighting to keyboard")
        else:
            self._save_lighting_btn.setText("Save lighting")
            if not loaded:
                self._lighting_status.setText("Lighting not loaded")
            elif dirty:
                self._lighting_status.setText("Live preview active; not saved yet")
            else:
                self._lighting_status.setText("Lighting saved")
        if loaded:
            color = calibrated_led_color(
                self._sliders["hue"].value(),
                self._sliders["sat"].value(),
                self._sliders[core.LIGHT_BRIGHTNESS].value(),
            )
            self._color_swatch.setStyleSheet(
                "background: %s; border: 1px solid #746b5d; border-radius: 7px;"
                % color.name())

    # --- worker/listener slots ---
    def _on_device_state(self, state):
        self._device_state = state
        self._update_banner()

    def _on_permission_state(self, state):
        self._permission_state = state
        self._update_banner()

    def _on_matrix_state(self, state):
        self._matrix_state = state
        self._update_banner()

    def _on_loading(self, busy):
        self._is_loading = busy
        self._update_banner()

    def _update_banner(self):
        if self._permission_state == "input-monitoring-denied":
            if self._matrix_state == "available":
                self._banner.setText(
                    "Keyboard HID is blocked; key highlights are using VIA fallback")
                self._reconnect_btn.hide()
                return
            self._banner.setText(
                "Keyboard input is blocked — restart the launching terminal after granting Input Monitoring")
            self._reconnect_btn.hide()
            return
        if self._is_loading:
            self._banner.setText("Reading keyboard…")
            self._reconnect_btn.hide()
            return
        state = self._device_state
        if state == "no-device":
            self._banner.setText("DOIO not found — plug it in")
            self._reconnect_btn.show()
        else:
            self._banner.setText("")
            self._reconnect_btn.hide()

    def _on_snapshot(self, snap: Snapshot):
        self._snapshot = snap
        self._inferred_layer.layer_count = len(snap.keymap)
        loaded_lighting = LightingState.from_snapshot(snap)
        self._saved_lighting = LightingState(
            brightness=min(loaded_lighting.brightness, 200),
            effect=loaded_lighting.effect,
            speed=loaded_lighting.speed,
            hue=loaded_lighting.hue,
            sat=loaded_lighting.sat,
        )
        self._apply_lighting(self._saved_lighting, live_preview=False)
        self._refresh_controls()

    def _on_lighting_saved(self, ok: bool):
        self._lighting_saving = False
        if ok and self._lighting is not None:
            self._saved_lighting = self._lighting
        elif not ok:
            self._banner.setText("Lighting save failed — reconnecting may be needed")
        self._refresh_lighting_ui()

    def _on_layer_pick(self, ly, checked):
        if checked:
            self._layer = ly
            self._inferred_layer.layer_mask = 1 << ly
            self._set_layer_led(ly)
            self._refresh_controls()

    def _refresh_controls(self):
        if self._snapshot is None:
            return
        for col in (0, 1, 2, 4):
            self._control_buttons[key_id(col)].setText(
                self._button_text(self._snapshot.keymap[self._layer][col]))
        for enc, direction in ENCODERS:
            label = f"{self._short_encoder_name(enc)} {DIR_NAMES[direction]}"
            mapping = render(self._snapshot.encoders[self._layer][enc][direction])
            self._control_buttons[enc_id(enc, direction)].setText(
                f"{label}\n{self._button_text(mapping=mapping)}")

    def _select(self, cid):
        self._selected = cid
        self._device_panel.set_active(cid)
        self._editor_label.setText(f"Editing {self._control_name(cid)}")
        self._picker_btn.setEnabled(True)
        code = self._current_code(cid)
        self._current_pick = code
        self._picker_btn.setText(render(code) if code is not None else "—")

    def _open_picker(self):
        if self._selected is None:
            return
        dlg = KeycodePickerDialog(current=self._current_pick, parent=self)
        if dlg.exec() == QDialog.Accepted:
            code = dlg.selected_code()
            if code is not None and code != self._current_pick:
                self._on_pick_keycode(code)

    def _on_pick_keycode(self, code: int):
        if self._selected is None:
            return
        cid = self._selected
        self._current_pick = code
        self._picker_btn.setText(render(code))
        # carry (layer, code) with the request so a later layer change can't
        # corrupt the snapshot update when the queued ack returns.
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

    def _on_matrix_press(self, cid):
        self._flash(cid)
        if self._snapshot is None or cid[0] != "key":
            return
        previous = self._inferred_layer.highest
        self._inferred_layer.press(self._snapshot, cid[1])
        self._sync_inferred_layer(previous)

    def _on_matrix_release(self, cid):
        if cid[0] != "key":
            return
        previous = self._inferred_layer.highest
        self._inferred_layer.release(cid[1])
        self._sync_inferred_layer(previous)

    def _sync_inferred_layer(self, previous: int):
        target = self._inferred_layer.highest
        if target == previous or target >= len(self._layer_buttons):
            return
        self._layer_buttons[target].setChecked(True)

    def _set_layer_led(self, layer: int):
        dot = getattr(self, "_layer_led", None)
        if dot is None:
            return
        color, border = _LAYER_LED_COLORS.get(layer, ("#ffd33d", "#7a5c00"))
        dot.set_colors(color, border)
        name = _LAYER_NAMES.get(layer, f"Layer {layer} / yellow")
        self._layer_status.setText(f"Selected layer: {name}")

    def _flash(self, cid):
        self._device_panel.flash(cid)

    def _current_code(self, cid) -> int | None:
        if self._snapshot is None:
            return None
        if cid[0] == "key":
            return self._snapshot.keymap[self._layer][cid[1]]
        return self._snapshot.encoders[self._layer][cid[1]][cid[2]]

    def _control_name(self, cid) -> str:
        if cid[0] == "key":
            labels = {0: "Key 1", 1: "Key 2", 2: "Key 3", 4: "Knob push"}
            return labels.get(cid[1], f"Matrix column {cid[1]}")
        return f"{ENC_NAMES[cid[1]]} {DIR_NAMES[cid[2]]}"

    def _short_encoder_name(self, enc: int) -> str:
        return "Outer" if enc == 1 else "Inner"

    def _button_text(self, code: int | None = None, mapping: str | None = None) -> str:
        text = mapping if mapping is not None else render(code)
        if "  (" in text and text.endswith(")"):
            label, qmk = text.rsplit("  (", 1)
            qmk = qmk[:-1]
            if label.startswith("(") and label.endswith(")"):
                label = label[1:-1]
            if len(label) <= 8 and len(qmk) <= 12:
                return f"{label}\n{qmk}"
            return label
        return text.replace("KC_AUDIO_", "").replace("KC_MEDIA_", "")
