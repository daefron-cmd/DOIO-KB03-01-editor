from worker import Readiness


class _Stub:
    def connect(self, *_a, **_kw): pass
    def emit(self, *_a, **_kw): pass


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


def test_update_readiness_rejects_unknown_gate():
    from worker import ControlWorker, Readiness

    class DummyIo:
        device_state = _Stub()
    io = DummyIo()
    control = ControlWorker(io)
    import pytest
    with pytest.raises(ValueError, match="unknown readiness gate"):
        control.update_readiness("not_a_real_gate", True)


def test_update_readiness_rejects_method_name_as_gate():
    """`hasattr` would pass for "is_ready" (a method on Readiness).
    Whitelisting field names prevents clobbering the method via setattr."""
    from worker import ControlWorker

    class DummyIo:
        device_state = _Stub()
    io = DummyIo()
    control = ControlWorker(io)
    import pytest
    with pytest.raises(ValueError, match="unknown readiness gate"):
        control.update_readiness("is_ready", True)
    # is_ready still callable and not clobbered
    assert callable(control._readiness.is_ready)
    assert control._readiness.is_ready() is False
