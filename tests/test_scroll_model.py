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


from scroll import ScrollEngine, ScrollPhase, MomentumPhase


def test_engine_initial_state_is_idle():
    posts = []
    eng = ScrollEngine(now_fn=lambda: 0, post_scroll=lambda *a: posts.append(a))
    assert eng.state.phase == Phase.IDLE
    assert posts == []


def _make_engine(config=None, now=0):
    posts = []
    clock = [now]
    eng = ScrollEngine(
        now_fn=lambda: clock[0],
        post_scroll=lambda p, sp, mp: posts.append((p, sp, mp)),
        config=config,
    )
    return eng, posts, clock


def test_enter_active_resets_baselines_and_posts_began():
    eng, posts, clock = _make_engine(now=100)
    eng.state.velocity = 50.0
    eng.state.accumulator = 0.7
    eng.enter_active(now_ms=100)
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.last_tick_ms == 100
    assert eng.state.last_emit_ms == 100
    assert eng.state.accumulator == 0.0
    assert eng.state.velocity == 50.0  # NOT cleared (impulse preserved)
    assert posts == [(0, ScrollPhase.BEGAN, MomentumPhase.NONE)]


def test_enter_momentum_posts_ended_then_began():
    eng, posts, clock = _make_engine(now=200)
    eng.state.velocity = 1000.0
    eng.state.phase = Phase.ACTIVE
    eng.enter_momentum(now_ms=200)
    assert eng.state.phase == Phase.MOMENTUM
    assert eng.state.last_tick_ms == 200
    assert eng.state.last_emit_ms == 200
    assert posts == [
        (0, ScrollPhase.ENDED, MomentumPhase.NONE),
        (0, ScrollPhase.NONE,  MomentumPhase.BEGAN),
    ]


def test_enter_idle_clears_velocity_and_accumulator():
    eng, posts, _ = _make_engine()
    eng.state.velocity = 123.0
    eng.state.accumulator = 4.5
    eng.state.phase = Phase.ACTIVE
    eng.enter_idle(post_ended=True)
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert eng.state.accumulator == 0.0
    assert posts == [(0, ScrollPhase.ENDED, MomentumPhase.NONE)]


def test_enter_idle_without_post_ended_emits_nothing():
    eng, posts, _ = _make_engine()
    eng.enter_idle(post_ended=False)
    assert posts == []
    assert eng.state.phase == Phase.IDLE


def test_enter_idle_from_momentum_posts_one_momentum_ended():
    eng, posts, _ = _make_engine()
    eng.state.velocity = 800.0
    eng.state.accumulator = 1.1
    eng.state.phase = Phase.MOMENTUM
    eng.enter_idle_from_momentum()
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert eng.state.accumulator == 0.0
    assert posts == [(0, ScrollPhase.NONE, MomentumPhase.ENDED)]


import math


def test_tick_in_idle_does_nothing():
    eng, posts, _ = _make_engine()
    eng.tick()
    assert posts == []


def test_tick_in_active_emits_pixels_and_damps_velocity():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 1000.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    clock[0] = 10  # 10 ms tick
    eng.tick()
    expected_v_after_damp = 1000.0 * math.exp(-0.010 / 0.400)
    assert abs(eng.state.velocity - expected_v_after_damp) < 0.5
    # gain at 1000 with defaults (slow=200, fast=1500, max=6):
    # t = (1000-200)/(1500-200) = 0.615 → gain ≈ 1 + 0.615*5 ≈ 4.08
    # pixels_f ≈ 1000 * 4.08 * 0.010 ≈ 40.8
    assert posts
    assert posts[0][1] == ScrollPhase.CHANGED
    assert posts[0][2] == MomentumPhase.NONE
    assert 30 <= posts[0][0] <= 50


def test_tick_in_momentum_uses_momentum_phase():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 500.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    clock[0] = 10
    eng.tick()
    assert posts
    assert posts[0][1] == ScrollPhase.NONE
    assert posts[0][2] == MomentumPhase.CHANGED


def test_tick_accumulator_carries_fractional_pixels():
    eng, posts, clock = _make_engine(now=0)
    # craft a velocity that produces ~3.5 px per tick at gain=1
    cfg = eng.config
    cfg.slow_threshold = 1e9  # force gain=1
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 350.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    # tick at 10 ms → output ≈ 350 * 0.010 ≈ 3.5 px → int 3, acc 0.5 (before damp drift)
    clock[0] = 10
    eng.tick()
    assert posts[0][0] == 3
    assert 0.3 < eng.state.accumulator < 0.6
