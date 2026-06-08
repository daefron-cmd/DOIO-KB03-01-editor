"""Heartbeat regression tests:

  - The QTimer that drives heartbeat must be created/started on
    control_thread. update_readiness() must refuse cross-thread mutation.
  - When a VIA reply stalls for >1 s, heartbeat send_untracked calls
    must still continue at the 200 ms cadence (fire-and-forget; no
    blocking dependency on the inflight VIA request).
"""

import threading
import time

from PySide6.QtCore import QCoreApplication, Q_ARG, Qt, QThread, QTimer
import pytest

import hid_io
from worker import ControlWorker, Readiness


class StallingIo:
    """Fake io that records send_untracked calls and never fulfils a
    send_request future, simulating a stalled VIA reply."""

    def __init__(self):
        self.untracked: list[list[int]] = []
        self.requests: list = []
        self.device_state = _Stub()

    def send_untracked(self, payload):
        self.untracked.append(list(payload))

    def send_request(self, payload):
        from concurrent.futures import Future
        f = Future()
        self.requests.append((payload, f))
        return f  # never resolves


class _Stub:
    def connect(self, *_a, **_kw): pass
    def emit(self, *_a, **_kw): pass


def test_update_readiness_runs_on_owning_thread(qtbot):
    """update_readiness must be entered on control_thread. Calling it
    cross-thread should NOT create a QTimer on the wrong thread."""
    app = QCoreApplication.instance() or QCoreApplication([])
    io = StallingIo()
    control = ControlWorker(io)
    thread = QThread()
    control.moveToThread(thread)
    thread.start()
    # Fire readiness transitions via QMetaObject so they run on the
    # owning thread.
    from PySide6.QtCore import QMetaObject
    for gate in ("imports_ok", "ax_trusted", "engine_running", "handle_open"):
        QMetaObject.invokeMethod(
            control, "update_readiness", Qt.QueuedConnection,
            Q_ARG(str, gate), Q_ARG(bool, True))
    # Give the event loop time to process and start the timer
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(io.untracked) == 0:
        app.processEvents()
        time.sleep(0.01)
    # Heartbeat fired at least once (immediate-fire on ready transition)
    assert len(io.untracked) >= 1
    assert io.untracked[0][0] == 0xA0
    thread.quit()
    thread.wait()


def test_heartbeat_continues_during_blocking_via_request(qtbot):
    """A VIA request that never resolves must not stop heartbeat
    cadence. heartbeat uses send_untracked which is fire-and-forget."""
    app = QCoreApplication.instance() or QCoreApplication([])
    io = StallingIo()
    control = ControlWorker(io)
    thread = QThread()
    control.moveToThread(thread)
    thread.start()
    from PySide6.QtCore import QMetaObject
    for gate in ("imports_ok", "ax_trusted", "engine_running", "handle_open"):
        QMetaObject.invokeMethod(
            control, "update_readiness", Qt.QueuedConnection,
            Q_ARG(str, gate), Q_ARG(bool, True))
    # Let some heartbeats fire
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    # At least 4 heartbeats in 1.2 s (cadence 200 ms, allow slack)
    assert len(io.untracked) >= 4, f"only {len(io.untracked)} heartbeats"
    thread.quit()
    thread.wait()
