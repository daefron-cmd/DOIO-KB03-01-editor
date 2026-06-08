from worker import Readiness


def test_readiness_default_is_not_ready():
    r = Readiness()
    assert not r.is_ready()


def test_readiness_all_four_gates_required():
    r = Readiness()
    r.handle_open = True
    assert not r.is_ready()
    r.imports_ok = True
    assert not r.is_ready()
    r.ax_trusted = True
    assert not r.is_ready()
    r.engine_running = True
    assert r.is_ready()


def test_readiness_loses_state_when_any_gate_drops():
    r = Readiness(handle_open=True, imports_ok=True,
                  ax_trusted=True, engine_running=True)
    assert r.is_ready()
    r.handle_open = False
    assert not r.is_ready()
