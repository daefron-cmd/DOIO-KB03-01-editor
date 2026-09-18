import pytest

import core
from listener import Listener
from model import Snapshot
from ui import MainWindow
from worker import ControlWorker


class RecordingControl(ControlWorker):
    def __init__(self):
        super().__init__(None)
        self.commands = []

    def _request(self, payload):
        self.commands.append(payload)
        return payload + [0] * (32 - len(payload))

    def save(self):
        self.commands.append(core.build_light_save())


@pytest.fixture
def window(qtbot):
    control = RecordingControl()
    w = MainWindow(control, Listener())
    qtbot.addWidget(w)
    w._on_snapshot(
        Snapshot(
            keymap=[[0] * 5 for _ in range(4)],
            encoders=[[[0, 0], [0, 0]] for _ in range(4)],
            brightness=80,
            effect=0,
            speed=100,
            hue=0,
            sat=255,
        )
    )
    return w


def test_save_flushes_pending_lighting_before_persisting(window):
    window._sliders[core.LIGHT_BRIGHTNESS].setValue(100)
    window._save_lighting()
    assert window._control.commands == [
        core.build_light_set_scalar(core.LIGHT_BRIGHTNESS, 100),
        core.build_light_save(),
    ]
    assert not window._pending


def test_save_ack_only_marks_requested_state_saved(window):
    window._sliders[core.LIGHT_BRIGHTNESS].setValue(100)
    window._flush_sliders()
    window._save_lighting()
    window._sliders[core.LIGHT_BRIGHTNESS].setValue(120)
    window._on_lighting_saved(True)
    assert window._saved_lighting.brightness == 100
    assert window._lighting.brightness == 120
    assert window._save_lighting_btn.isEnabled()


def test_revert_discards_pending_slider_values(window):
    window._sliders[core.LIGHT_BRIGHTNESS].setValue(100)
    window._revert_lighting()
    window._flush_sliders()
    assert (
        core.build_light_set_scalar(core.LIGHT_BRIGHTNESS, 100)
        not in window._control.commands
    )
    assert window._lighting == window._saved_lighting
