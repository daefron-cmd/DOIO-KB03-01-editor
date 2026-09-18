import pytest

import scroll
from scroll import Phase, QtScrollEngine, ScrollConfig
from worker import ControlWorker


@pytest.fixture
def engine(qtbot, monkeypatch):
    monkeypatch.setattr(scroll, "make_cgevent_post", lambda: lambda *args: None)
    wrapper = QtScrollEngine(ScrollConfig(impulse_per_detent=500))
    wrapper.start_real()
    yield wrapper
    wrapper.stop()


def test_scroll_timer_is_stopped_while_idle(engine):
    assert engine.engine.state.phase == Phase.IDLE
    assert not engine._timer.isActive()


def test_scroll_timer_runs_through_momentum_then_stops(engine, qtbot):
    clock = [1000]
    engine.engine._now = lambda: clock[0]
    engine.on_scroll_tick(1, 1000)
    assert engine._timer.isActive()
    clock[0] += 100
    qtbot.waitUntil(lambda: engine.engine.state.phase == Phase.MOMENTUM)
    assert engine._timer.isActive()
    engine.engine.state.velocity = 1
    clock[0] += 8
    qtbot.waitUntil(lambda: engine.engine.state.phase == Phase.IDLE)
    assert not engine._timer.isActive()
    engine.on_scroll_tick(1, 2000)
    assert engine._timer.isActive()


def test_reverse_brake_stops_timer(engine):
    engine.engine.config.brake_on_reverse = True
    engine.on_scroll_tick(1, 0)
    engine.engine.enter_momentum(0)
    engine.on_scroll_tick(-1, 1)
    assert engine.engine.state.phase == Phase.IDLE
    assert not engine._timer.isActive()


def test_idle_engine_keeps_heartbeat_readiness(qtbot, monkeypatch):
    monkeypatch.setattr(scroll, "make_cgevent_post", lambda: lambda *args: None)

    class Io:
        def __init__(self):
            self.heartbeats = []

        def send_untracked(self, payload):
            self.heartbeats.append(payload)

    io = Io()
    control = ControlWorker(io)
    wrapper = QtScrollEngine()
    wrapper.started.connect(control.on_engine_started)
    wrapper.stopped.connect(control.on_engine_stopped)
    for gate in ("imports_ok", "ax_trusted", "handle_open"):
        control.update_readiness(gate, True)
    wrapper.start_real()
    try:
        assert not wrapper._timer.isActive()
        qtbot.waitUntil(lambda: len(io.heartbeats) >= 2)
        assert control._readiness.is_ready()
    finally:
        wrapper.stop()
