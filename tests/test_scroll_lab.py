from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton

from scroll import ScrollConfig
from scroll_lab import InfiniteTextCanvas, ScrollLabWindow
from ui import ScrollFeelPanel


def test_virtual_canvas_scrolls_indefinitely_in_both_directions(qtbot):
    canvas = InfiniteTextCanvas()
    canvas.resize(700, 480)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.reset_origin()

    assert canvas.center_line() == 0

    canvas.scroll_content_by(canvas.line_height * 1_000_000)
    assert canvas.center_line() == 1_000_000

    canvas.scroll_content_by(canvas.line_height * -2_000_000)
    assert canvas.center_line() == -1_000_000


def test_virtual_canvas_keeps_subpixel_scroll_remainder(qtbot):
    canvas = InfiniteTextCanvas()
    canvas.resize(700, 480)
    qtbot.addWidget(canvas)
    canvas.reset_origin()

    canvas.scroll_content_by(canvas.line_height / 2.0 - 0.25)
    assert canvas.center_line() == 0

    canvas.scroll_content_by(0.5)
    assert canvas.center_line() == 1
    assert canvas.last_delta == 0.5


def test_virtual_canvas_handles_pixel_and_zero_delta_phase_events(qtbot):
    canvas = InfiniteTextCanvas()
    canvas.resize(700, 480)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.reset_origin()

    update = QWheelEvent(
        QPointF(20, 20),
        QPointF(20, 20),
        QPoint(0, -15),
        QPoint(),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(canvas, update)
    assert canvas.last_delta == 15.0
    assert canvas.last_source == "pixel"
    assert canvas.last_phase == "update"

    end = QWheelEvent(
        QPointF(20, 20),
        QPointF(20, 20),
        QPoint(),
        QPoint(),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollEnd,
        False,
    )
    QApplication.sendEvent(canvas, end)
    assert canvas.last_delta == 0.0
    assert canvas.last_source == "phase"
    assert canvas.last_phase == "end"


def test_virtual_text_exists_for_large_signed_row_numbers():
    positive = InfiniteTextCanvas.line_text(10**15)
    negative = InfiniteTextCanvas.line_text(-(10**15))

    assert "CALIBRATION PASS" in positive or "sample" in positive
    assert "CALIBRATION PASS" in negative or "sample" in negative
    assert positive != negative


def test_scroll_lab_reset_centers_origin_and_clears_readout(qtbot):
    window = ScrollLabWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.canvas.center_line() == 0
    window.canvas.scroll_content_by(245.0, source="pixel", phase="update")
    assert window.canvas.event_count == 1

    window.canvas.reset_origin()

    assert window.canvas.center_line() == 0
    assert window.canvas.event_count == 0
    assert window._position_value.text() == "+0"
    assert window._events_value.text() == "0"


def test_scroll_feel_panel_opens_non_modal_scroll_lab(qtbot, tmp_path):
    panel = ScrollFeelPanel(
        ScrollConfig(),
        tmp_path / "scroll.json",
        scroll_engine=None,
        ax_trusted=True,
        imports_ok=True,
    )
    qtbot.addWidget(panel)
    panel.show()

    button = panel.findChild(QPushButton, "scrollLabButton")
    assert button is not None
    qtbot.mouseClick(button, Qt.LeftButton)

    assert panel._scroll_lab_window is not None
    assert panel._scroll_lab_window.isVisible()
    assert panel._scroll_lab_window.isModal() is False
