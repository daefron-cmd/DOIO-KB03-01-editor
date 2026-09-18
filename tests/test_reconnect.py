from concurrent.futures import Future

import core
from listener import Listener
from worker import ControlWorker


class EchoIo:
    def __init__(self):
        self.requests = []

    def send_request(self, payload):
        self.requests.append(payload)
        future = Future()
        future.set_result(payload + [0] * (32 - len(payload)))
        return future


def test_successful_open_notifies_ui_and_reloads_snapshot(qtbot):
    control = ControlWorker(EchoIo())
    states, snapshots = [], []
    control.device_state.connect(states.append)
    control.snapshot_ready.connect(snapshots.append)
    control.start()
    try:
        assert not control._io.requests
        control._on_device_state("")
        assert states[-1] == ""
        assert len(snapshots) == 1
        assert control._matrix_timer.isActive()
        control._on_device_state("no-device")
        assert not control._matrix_timer.isActive()
        control._on_device_state("")
        assert len(snapshots) == 2
    finally:
        control._matrix_timer.stop()


def test_disconnect_releases_held_matrix_keys_and_clears_status(qtbot):
    control = ControlWorker(EchoIo())
    control._on_device_state("")
    control._pressed_cols = {1}
    control._matrix_state = "available"
    released = []
    control.matrix_release.connect(released.append)
    control._on_device_state("no-device")
    assert released == [("key", 1)]
    assert not control._pressed_cols
    assert control._matrix_state == ""
    control._matrix_timer.stop()


class FakeInput:
    def __init__(self):
        self.closed = False
        self.fail_read = False

    def open_path(self, path):
        pass

    def set_nonblocking(self, flag):
        pass

    def read(self, size):
        if self.fail_read:
            raise OSError("unplugged")
        return []

    def close(self):
        self.closed = True


def test_absent_device_is_not_reported_as_permission_denial(monkeypatch):
    monkeypatch.setattr("listener.hid.enumerate", lambda *_: [])
    listener = Listener()
    states = []
    listener.permission_state.connect(states.append)
    listener._open()
    assert states == [""]


def test_listener_recovers_after_unplug_and_replug(monkeypatch):
    devices = [dict(path=b"keyboard", usage_page=1, usage=6)]
    handles = []
    monkeypatch.setattr("listener.hid.enumerate", lambda *_: devices)

    def make_handle():
        handle = FakeInput()
        handles.append(handle)
        return handle

    monkeypatch.setattr("listener.hid.device", make_handle)
    listener = Listener()
    listener._open()
    handles[0].fail_read = True
    listener._poll_once()
    assert handles[0].closed
    listener._open()
    assert len(handles) == 2
    listener._poll_once()
    listener._close_all()
    assert handles[1].closed


def test_listener_retries_permission_without_reopening_consumer(monkeypatch):
    devices = [
        dict(path=b"keyboard", usage_page=1, usage=6),
        dict(path=b"consumer", usage_page=1, usage=2),
    ]
    monkeypatch.setattr("listener.hid.enumerate", lambda *_: devices)
    allowed = [False]
    handles = []

    class PermissionInput(FakeInput):
        def open_path(self, path):
            if path == b"keyboard" and not allowed[0]:
                raise OSError("permission denied")

    def make_handle():
        handle = PermissionInput()
        handles.append(handle)
        return handle

    monkeypatch.setattr("listener.hid.device", make_handle)
    listener = Listener()
    states = []
    listener.permission_state.connect(states.append)
    listener._open()
    assert states[-1] == "input-monitoring-denied"
    assert handles[0].closed
    allowed[0] = True
    listener._open()
    assert states[-1] == ""
    assert len(handles) == 3
    listener._close_all()


def test_control_stops_polling_after_disconnect(qtbot):
    io = EchoIo()
    control = ControlWorker(io)
    control.start()
    try:
        control._poll_matrix()
        assert core.build_pressed_cols() not in io.requests
    finally:
        control._matrix_timer.stop()
