from scroll import Phase, ScrollConfig, ScrollState


def test_scrollstate_defaults():
    s = ScrollState()
    assert s.velocity == 0.0
    assert s.accumulator == 0.0
    assert s.last_tick_ms == 0
    assert s.last_emit_ms == 0
    assert s.phase == Phase.IDLE


def test_scrollconfig_defaults():
    c = ScrollConfig()
    assert c.impulse_per_detent == 100.0
    assert c.tau_ms == 400
    assert c.slow_threshold == 200.0
    assert c.fast_threshold == 1500.0
    assert c.max_gain == 6.0
    assert c.active_window_ms == 80
    assert c.coast_threshold == 300.0
    assert c.cutoff_v == 40.0
    assert c.v_max == 2500.0
    assert c.invert is False
