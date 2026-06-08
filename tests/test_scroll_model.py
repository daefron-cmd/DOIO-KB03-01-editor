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


from scroll import magspeed_gain


def test_gain_below_slow_is_one():
    c = ScrollConfig()
    assert magspeed_gain(0.0, c) == 1.0
    assert magspeed_gain(c.slow_threshold, c) == 1.0


def test_gain_above_fast_is_max():
    c = ScrollConfig()
    assert magspeed_gain(c.fast_threshold, c) == c.max_gain
    assert magspeed_gain(c.fast_threshold + 1000, c) == c.max_gain


def test_gain_midpoint_is_linear():
    c = ScrollConfig(slow_threshold=200, fast_threshold=1200, max_gain=11)
    mid = (200 + 1200) / 2
    assert magspeed_gain(mid, c) == 6.0  # halfway: 1 + 0.5 * 10
