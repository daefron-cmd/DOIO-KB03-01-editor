"""Virtual, unbounded text surface for tuning scroll-wheel behaviour."""

from math import ceil, floor

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


_TEXT_ROWS = (
    "Turn one detent at a time and watch for a small, predictable nudge.",
    "Build speed gradually; the numbered gutter makes gain changes visible.",
    "Release the ring and compare the coast distance with the fixed marker.",
    "Reverse during momentum to check whether braking feels immediate.",
    "Try a fast spin, then a slow correction in the opposite direction.",
    "Look for a smooth hand-off from active movement into momentum.",
    "Fine motion should remain readable without sudden whole-line jumps.",
    "Repeated passes make acceleration differences easier to compare.",
    "Keep the pointer over this field so generated scroll events land here.",
    "There is no first or last row; only visible text is rendered.",
    "A stable center reference reveals overshoot, jitter, and late braking.",
    "Reset the origin whenever you want a fresh calibration pass.",
)


_SCROLL_LAB_STYLE = """
QWidget#scrollLabRoot {
    background: #111316;
    color: #f4f6f1;
    font-family: "Avenir Next";
}
QFrame#scrollLabHeader,
QFrame#scrollLabFooter {
    background: #181b1f;
    border: 1px solid #2b3036;
    border-radius: 10px;
}
QLabel#scrollLabEyebrow {
    color: #b8ff5a;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#scrollLabTitle {
    color: #f7f8f4;
    font-size: 24px;
    font-weight: 800;
}
QLabel#scrollLabDescription {
    color: #9ba3ad;
    font-size: 12px;
}
QLabel#scrollLabStatLabel {
    color: #777f89;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#scrollLabStatValue {
    color: #edf0eb;
    font-family: "Menlo";
    font-size: 13px;
    font-weight: 700;
}
QPushButton#scrollLabReset {
    background: #b8ff5a;
    border: 1px solid #d2ff98;
    border-radius: 7px;
    color: #11150c;
    font-weight: 800;
    padding: 8px 12px;
}
QPushButton#scrollLabReset:hover {
    background: #c8ff82;
}
QPushButton#scrollLabReset:pressed {
    background: #a5ea4d;
}
"""


class InfiniteTextCanvas(QWidget):
    """Paints an unlimited sequence of text rows without storing a document."""

    scrolled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("infiniteTextCanvas")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(520, 360)

        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        fixed_font.setPointSize(12)
        fixed_font.setWeight(QFont.Medium)
        self._font = fixed_font
        self._small_font = QFont(fixed_font)
        self._small_font.setPointSize(10)
        self._small_font.setWeight(QFont.DemiBold)

        self._line_height = 30.0
        self._top_line = 0
        self._line_offset = 0.0
        self._event_count = 0
        self._last_delta = 0.0
        self._last_source = "waiting"
        self._last_phase = "idle"

    @property
    def line_height(self) -> float:
        return self._line_height

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def last_delta(self) -> float:
        return self._last_delta

    @property
    def last_source(self) -> str:
        return self._last_source

    @property
    def last_phase(self) -> str:
        return self._last_phase

    def center_line(self) -> int:
        return self.line_at(self.height() / 2.0)

    def line_at(self, y: float) -> int:
        return self._top_line + floor(
            (self._line_offset + y) / self._line_height)

    def reset_origin(self) -> None:
        """Put virtual row zero beneath the fixed center marker."""
        # Align the marker with the middle of row zero, not merely somewhere
        # inside it. That makes measured travel symmetric in both directions.
        position = self._line_height / 2.0 - self.height() / 2.0
        self._top_line = floor(position / self._line_height)
        self._line_offset = position - self._top_line * self._line_height
        self._event_count = 0
        self._last_delta = 0.0
        self._last_source = "waiting"
        self._last_phase = "idle"
        self.update()
        self.scrolled.emit()

    def scroll_content_by(
        self,
        pixels: float,
        *,
        source: str = "test",
        phase: str = "update",
        count_event: bool = True,
    ) -> None:
        """Advance to later rows for positive pixels and earlier rows for negative."""
        self._advance_content(pixels)
        if count_event:
            self._event_count += 1
        self._last_delta = float(pixels)
        self._last_source = source
        self._last_phase = phase
        self.update()
        self.scrolled.emit()

    def _advance_content(self, pixels: float) -> None:
        total = self._line_offset + float(pixels)
        whole_rows = floor(total / self._line_height)
        self._top_line += whole_rows
        self._line_offset = total - whole_rows * self._line_height

    @staticmethod
    def line_text(line_number: int) -> str:
        pass_number, row = divmod(line_number, len(_TEXT_ROWS))
        if row == 0:
            return (
                f"CALIBRATION PASS {pass_number:+010d}  /  "
                "precision · acceleration · coast · reverse"
            )
        return f"{_TEXT_ROWS[row]}  ·  sample {abs(pass_number) % 97:02d}"

    def wheelEvent(self, event):
        phase_value = event.phase()
        phase_name = getattr(phase_value, "name", str(phase_value))
        phase_name = phase_name.removeprefix("Scroll").lower()

        pixel_y = event.pixelDelta().y()
        if pixel_y:
            content_delta = -float(pixel_y)
            source = "pixel"
        else:
            angle_y = event.angleDelta().y()
            if not angle_y:
                if phase_value == Qt.NoScrollPhase:
                    event.ignore()
                    return
                content_delta = 0.0
                source = "phase"
            else:
                content_delta = -(angle_y / 120.0) * self._line_height * 3.0
                source = "detent"

        self.scroll_content_by(
            content_delta,
            source=source,
            phase=phase_name or "update",
        )
        event.accept()

    def resizeEvent(self, event):
        old_height = event.oldSize().height()
        new_height = event.size().height()
        if old_height >= 0 and old_height != new_height:
            # Preserve the same virtual position under the fixed marker when
            # the window grows or shrinks.
            self._advance_content(-(new_height - old_height) / 2.0)
            self.update()
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Up:
            self.scroll_content_by(-self._line_height, source="key")
        elif key == Qt.Key_Down:
            self.scroll_content_by(self._line_height, source="key")
        elif key == Qt.Key_PageUp:
            self.scroll_content_by(-self.height() * 0.8, source="key")
        elif key == Qt.Key_PageDown:
            self.scroll_content_by(self.height() * 0.8, source="key")
        elif key == Qt.Key_Home:
            self.reset_origin()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.fillRect(self.rect(), QColor("#0d0f12"))

        gutter_width = 112.0
        center_y = self.height() / 2.0
        center_line = self.center_line()
        first_y = -self._line_offset
        visible_rows = ceil(
            (self.height() + self._line_offset) / self._line_height) + 1

        painter.fillRect(
            QRectF(0, 0, gutter_width, self.height()), QColor("#12151a"))
        painter.setPen(QPen(QColor("#262b32"), 1))
        painter.drawLine(int(gutter_width), 0, int(gutter_width), self.height())

        for row in range(visible_rows):
            line_number = self._top_line + row
            y = first_y + row * self._line_height
            row_rect = QRectF(0, y, self.width(), self._line_height)

            if line_number == center_line:
                painter.fillRect(row_rect, QColor("#1b2219"))
            elif line_number % 2:
                painter.fillRect(row_rect, QColor("#101216"))

            if line_number % len(_TEXT_ROWS) == 0:
                painter.fillRect(
                    QRectF(0, y, 4, self._line_height), QColor("#b8ff5a"))

            painter.setFont(self._small_font)
            painter.setPen(QColor("#69727d"))
            painter.drawText(
                QRectF(12, y, gutter_width - 24, self._line_height),
                Qt.AlignRight | Qt.AlignVCenter,
                f"{line_number:+08d}",
            )

            painter.setFont(self._font)
            painter.setPen(
                QColor("#e8ece5")
                if line_number == center_line
                else QColor("#aeb5bd"))
            painter.drawText(
                QRectF(
                    gutter_width + 22,
                    y,
                    max(0.0, self.width() - gutter_width - 44),
                    self._line_height,
                ),
                Qt.AlignLeft | Qt.AlignVCenter,
                self.line_text(line_number),
            )

        marker_pen = QPen(QColor("#b8ff5a"), 1)
        marker_pen.setStyle(Qt.DashLine)
        painter.setPen(marker_pen)
        painter.drawLine(0, int(center_y), self.width(), int(center_y))

        painter.setFont(self._small_font)
        label = "CALIBRATION LINE"
        label_width = 142.0
        label_rect = QRectF(
            self.width() - label_width - 14,
            center_y - 12,
            label_width,
            24,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#b8ff5a"))
        painter.drawRoundedRect(label_rect, 6, 6)
        painter.setPen(QColor("#12150d"))
        painter.drawText(label_rect, Qt.AlignCenter, label)


class ScrollLabWindow(QMainWindow):
    """Non-modal calibration window for the MX Master scroll emulator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scroll Lab — Infinite Text")
        self.setMinimumSize(720, 560)
        self.resize(940, 720)
        self._first_show = True

        root = QWidget()
        root.setObjectName("scrollLabRoot")
        root.setStyleSheet(_SCROLL_LAB_STYLE)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("scrollLabHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 13, 14, 13)
        header_row.setSpacing(16)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        eyebrow = QLabel("SCROLL LAB  /  LIVE TARGET")
        eyebrow.setObjectName("scrollLabEyebrow")
        title = QLabel("Infinite text field")
        title.setObjectName("scrollLabTitle")
        description = QLabel(
            "Keep the pointer over the text, turn the outer ring, and tune "
            "the controls in the main window."
        )
        description.setObjectName("scrollLabDescription")
        title_block.addWidget(eyebrow)
        title_block.addWidget(title)
        title_block.addWidget(description)
        header_row.addLayout(title_block, stretch=1)

        reset = QPushButton("Reset origin")
        reset.setObjectName("scrollLabReset")
        reset.setToolTip("Center row zero and clear the event readout (Home)")
        header_row.addWidget(reset, alignment=Qt.AlignBottom)
        layout.addWidget(header)

        self.canvas = InfiniteTextCanvas()
        self.canvas.setToolTip(
            "Scroll in either direction. Up/Down, Page Up/Down, and Home "
            "are also available."
        )
        layout.addWidget(self.canvas, stretch=1)

        footer = QFrame()
        footer.setObjectName("scrollLabFooter")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(14, 10, 14, 10)
        footer_row.setSpacing(28)

        self._position_value = self._add_stat(footer_row, "CENTER ROW")
        self._delta_value = self._add_stat(footer_row, "LAST Δ")
        self._input_value = self._add_stat(footer_row, "INPUT")
        self._phase_value = self._add_stat(footer_row, "PHASE")
        self._events_value = self._add_stat(footer_row, "EVENTS")
        footer_row.addStretch()
        hint = QLabel("No endpoints · virtual rows")
        hint.setObjectName("scrollLabDescription")
        footer_row.addWidget(hint)
        layout.addWidget(footer)

        reset.clicked.connect(self.canvas.reset_origin)
        self.canvas.scrolled.connect(self._refresh_stats)
        self.canvas.reset_origin()

    @staticmethod
    def _add_stat(row: QHBoxLayout, label_text: str) -> QLabel:
        block = QVBoxLayout()
        block.setSpacing(0)
        label = QLabel(label_text)
        label.setObjectName("scrollLabStatLabel")
        value = QLabel("—")
        value.setObjectName("scrollLabStatValue")
        block.addWidget(label)
        block.addWidget(value)
        row.addLayout(block)
        return value

    def _refresh_stats(self) -> None:
        self._position_value.setText(f"{self.canvas.center_line():+d}")
        self._delta_value.setText(f"{self.canvas.last_delta:+.1f} px")
        self._input_value.setText(self.canvas.last_source)
        self._phase_value.setText(self.canvas.last_phase)
        self._events_value.setText(str(self.canvas.event_count))

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            # The canvas receives its final layout geometry only when this
            # top-level window is first shown.
            self.canvas.reset_origin()
        self.canvas.setFocus(Qt.OtherFocusReason)
