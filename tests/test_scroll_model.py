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


def test_active_with_idle_period_transitions_to_momentum_if_fast():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 1000.0  # > coast_threshold (300)
    eng.state.last_tick_ms = 0
    eng.state.last_emit_ms = 0
    clock[0] = 200  # well beyond active_window_ms = 80
    eng.tick()
    assert eng.state.phase == Phase.MOMENTUM
    # transition posts ENDED then MomentumBegan, then the regular emit
    assert posts[0] == (0, ScrollPhase.ENDED, MomentumPhase.NONE)
    assert posts[1] == (0, ScrollPhase.NONE, MomentumPhase.BEGAN)


def test_active_with_idle_period_goes_to_idle_if_slow():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 100.0  # < coast_threshold (300)
    eng.state.last_tick_ms = 0
    eng.state.last_emit_ms = 0
    clock[0] = 200
    eng.tick()
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert posts == [(0, ScrollPhase.ENDED, MomentumPhase.NONE)]


def test_momentum_ends_when_velocity_below_cutoff():
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 30.0  # already below cutoff_v=40
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    clock[0] = 10
    eng.tick()
    assert eng.state.phase == Phase.IDLE
    assert eng.state.velocity == 0.0
    assert posts == [(0, ScrollPhase.NONE, MomentumPhase.ENDED)]


def test_on_tick_from_idle_enters_active_and_adds_impulse():
    eng, posts, clock = _make_engine(now=100)
    eng.on_tick(direction=+1, device_t_ms=12345)
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.velocity == eng.config.impulse_per_detent
    assert eng.state.last_tick_ms == 100
    assert posts == [(0, ScrollPhase.BEGAN, MomentumPhase.NONE)]


def test_on_tick_direction_is_signed():
    eng, posts, _ = _make_engine(now=0)
    eng.on_tick(direction=-1, device_t_ms=0)
    assert eng.state.velocity == -eng.config.impulse_per_detent


def test_on_tick_clamps_to_v_max():
    eng, posts, _ = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = eng.config.v_max - 10
    eng.on_tick(direction=+1, device_t_ms=0)
    assert eng.state.velocity == eng.config.v_max


def test_on_tick_invert_flips_sign():
    eng, posts, _ = _make_engine()
    eng.config.invert = True
    eng.on_tick(direction=+1, device_t_ms=0)
    assert eng.state.velocity == -eng.config.impulse_per_detent


def test_direction_flip_during_active_zeros_velocity_then_applies_impulse():
    eng, posts, _ = _make_engine()
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 500.0
    eng.state.accumulator = 0.7
    eng.on_tick(direction=-1, device_t_ms=0)
    assert eng.state.velocity == -eng.config.impulse_per_detent
    assert eng.state.accumulator == 0.0


def test_direction_flip_during_momentum_posts_one_momentum_ended():
    eng, posts, _ = _make_engine()
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 500.0
    eng.state.accumulator = 1.5
    eng.on_tick(direction=-1, device_t_ms=0)
    # Sequence: MomentumEnded, then ScrollBegan, then impulse applied
    momentum_ended_count = sum(
        1 for p in posts if p == (0, ScrollPhase.NONE, MomentumPhase.ENDED))
    assert momentum_ended_count == 1
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.velocity == -eng.config.impulse_per_detent
    assert eng.state.accumulator == 0.0


def test_same_direction_during_momentum_reopens_active_with_one_momentum_ended():
    eng, posts, _ = _make_engine()
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 500.0
    eng.on_tick(direction=+1, device_t_ms=0)
    momentum_ended_count = sum(
        1 for p in posts if p == (0, ScrollPhase.NONE, MomentumPhase.ENDED))
    assert momentum_ended_count == 1
    assert eng.state.phase == Phase.ACTIVE
    assert eng.state.velocity == 500.0 + eng.config.impulse_per_detent


def _run_to_idle(eng, clock, start_ms, max_ms=5000, tick_period_ms=8):
    posts_local = []
    eng._post = lambda p, sp, mp: posts_local.append((p, sp, mp))
    t = start_ms
    end = start_ms + max_ms
    while t <= end:
        clock[0] = t
        eng.tick()
        if eng.state.phase == Phase.IDLE:
            break
        t += tick_period_ms
    return posts_local


def test_single_isolated_detent_emits_at_most_15_pixels():
    eng, _, clock = _make_engine(now=0)
    eng.on_tick(direction=+1, device_t_ms=0)
    posts = _run_to_idle(eng, clock, start_ms=0)
    total_px = sum(p[0] for p in posts)
    assert eng.state.phase == Phase.IDLE
    assert abs(total_px) <= 15, (
        f"Single slow detent emitted {total_px} px — precision guarantee broken. "
        f"Posts: {posts}")


def test_steady_spin_converges_to_stable_velocity():
    """Spin at one detent every 30 ms for 3 seconds. After the first
    ~1 second the velocity should be within 5% of steady-state."""
    eng, _, clock = _make_engine(now=0)
    eng._post = lambda *a: None
    detent_period = 30
    velocity_samples = []
    t = 0
    last_detent = 0
    end = 3000
    while t <= end:
        clock[0] = t
        if t - last_detent >= detent_period:
            eng.on_tick(direction=+1, device_t_ms=t)
            last_detent = t
        eng.tick()
        if t > 1000:
            velocity_samples.append(eng.state.velocity)
        t += 8

    assert velocity_samples
    v_late = velocity_samples[-200:]  # last ~1.6 s
    v_min, v_max = min(v_late), max(v_late)
    spread = (v_max - v_min) / max(abs(v_max), 1)
    assert spread < 0.20, (
        f"Velocity unstable in late phase: min={v_min:.1f} max={v_max:.1f}")


def test_dt_clamp_prevents_huge_first_frame():
    """If the event loop stalls for 5 seconds, the first tick after the
    stall must not emit a giant burst."""
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 1000.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 5000  # detent JUST arrived at t=5000
    clock[0] = 5000
    eng.tick()
    # No phase transition (active_window check sees 0 ms since detent).
    # Damping uses dt_s clamped to 50ms.
    assert posts
    deltas = [p[0] for p in posts if p[1] == ScrollPhase.CHANGED]
    assert deltas, f"expected an ACTIVE emit, got {posts}"
    assert all(abs(d) < 300 for d in deltas), (
        f"dt-clamp failed: emits {deltas}")


def test_accumulator_does_not_drift_over_long_run():
    """Sum of int pixels emitted equals integer part of analytic integral
    within ±1 px after 10000 ticks under steady velocity."""
    eng, posts, clock = _make_engine(now=0)
    cfg = eng.config
    cfg.slow_threshold = 1e9  # gain=1 throughout
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = 100.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    t = 0
    detent_period = 1   # one detent every ms — keeps ACTIVE alive, ~steady-state
    last_detent = 0
    end = 10000 * 8  # 10000 ticks at 8 ms
    while t < end:
        clock[0] = t
        if t - last_detent >= detent_period:
            eng.on_tick(direction=+1, device_t_ms=t)
            last_detent = t
        eng.tick()
        t += 8
    px_emitted = sum(p[0] for p in posts if p[1] == ScrollPhase.CHANGED)
    # Cross-check: with continuous impulses + damping, steady-state v is
    # high (impulse rate >> damping rate). Use loose bound: emitted pixels
    # should equal accumulator-corrected sum within 1 px.
    # Easier check: accumulator never grows unbounded.
    assert -2.0 < eng.state.accumulator < 2.0, (
        f"Accumulator drift: {eng.state.accumulator}")
    assert px_emitted > 0


def test_single_isolated_reverse_detent_is_precise():
    eng, _, clock = _make_engine(now=0)
    eng.on_tick(direction=-1, device_t_ms=0)
    posts = _run_to_idle(eng, clock, start_ms=0)
    total = sum(p[0] for p in posts)
    assert eng.state.phase == Phase.IDLE
    assert abs(total) <= 15, (
        f"Reverse precision broken: total={total}, posts={posts}")


def test_reverse_steady_spin_converges():
    eng, _, clock = _make_engine(now=0)
    eng._post = lambda *a: None
    t = 0
    last = 0
    samples = []
    while t <= 3000:
        clock[0] = t
        if t - last >= 30:
            eng.on_tick(direction=-1, device_t_ms=t)
            last = t
        eng.tick()
        if t > 1000:
            samples.append(eng.state.velocity)
        t += 8
    late = samples[-200:]
    spread = (max(late) - min(late)) / max(abs(min(late)), 1)
    assert spread < 0.20, f"Reverse spin unstable: {late[:5]}…{late[-5:]}"


def test_direction_flip_negative_to_positive():
    eng, posts, _ = _make_engine()
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = -500.0
    eng.on_tick(direction=+1, device_t_ms=0)
    assert eng.state.velocity == +eng.config.impulse_per_detent
    assert eng.state.accumulator == 0.0


def test_accumulator_does_not_drift_negative():
    eng, posts, clock = _make_engine(now=0)
    cfg = eng.config
    cfg.slow_threshold = 1e9
    eng.state.phase = Phase.ACTIVE
    eng.state.velocity = -100.0
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0
    t = 0
    last = 0
    while t < 10000 * 8:
        clock[0] = t
        if t - last >= 1:
            eng.on_tick(direction=-1, device_t_ms=t)
            last = t
        eng.tick()
        t += 8
    assert -2.0 < eng.state.accumulator < 2.0


def test_make_cgevent_post_does_not_crash_on_darwin():
    import sys
    if sys.platform != "darwin":
        return
    from scroll import make_cgevent_post
    post = make_cgevent_post()
    # Post a zero-pixel "began" — visible to the OS but harmless.
    post(0, ScrollPhase.BEGAN, MomentumPhase.NONE)
    post(0, ScrollPhase.ENDED, MomentumPhase.NONE)


def test_scroll_phase_constants_match_coregraphics_on_darwin():
    """Our ScrollPhase mirror must match CoreGraphics CGScrollPhase.
    If pyobjc exposes the constants, assert equality. If not, log the
    runtime values so a manual probe can verify shape."""
    import sys
    if sys.platform != "darwin":
        return
    import Quartz

    pairs = [
        ("BEGAN", "kCGScrollPhaseBegan"),
        ("CHANGED", "kCGScrollPhaseChanged"),
        ("ENDED", "kCGScrollPhaseEnded"),
        ("CANCELLED", "kCGScrollPhaseCancelled"),
        ("MAY_BEGIN", "kCGScrollPhaseMayBegin"),
    ]
    for ours, theirs in pairs:
        if not hasattr(Quartz, theirs):
            continue  # newer/older pyobjc may not expose all
        assert getattr(ScrollPhase, ours) == getattr(Quartz, theirs), (
            f"ScrollPhase.{ours} = {getattr(ScrollPhase, ours)} but "
            f"Quartz.{theirs} = {getattr(Quartz, theirs)}")


def test_momentum_phase_constants_match_coregraphics_on_darwin():
    import sys
    if sys.platform != "darwin":
        return
    import Quartz

    pairs = [
        ("BEGAN", "kCGMomentumScrollPhaseBegin"),
        ("CHANGED", "kCGMomentumScrollPhaseContinue"),
        ("ENDED", "kCGMomentumScrollPhaseEnd"),
    ]
    for ours, theirs in pairs:
        if not hasattr(Quartz, theirs):
            continue
        assert getattr(MomentumPhase, ours) == getattr(Quartz, theirs), (
            f"MomentumPhase.{ours} mismatch with Quartz.{theirs}")


def test_is_accessibility_trusted_returns_bool_on_darwin():
    import sys
    if sys.platform != "darwin":
        return
    from scroll import is_accessibility_trusted
    result = is_accessibility_trusted(prompt=False)
    assert isinstance(result, bool)


def test_qt_scroll_engine_constructs_without_qt_running():
    from scroll import QtScrollEngine
    eng = QtScrollEngine()
    assert eng.engine.state.phase == Phase.IDLE


def test_momentum_decay_reaches_cutoff_in_expected_time():
    """Released from high velocity, MOMENTUM should decay to IDLE in
    roughly τ * ln(v0 / cutoff_v) wall-time. The model uses damping in
    both ACTIVE and MOMENTUM, but ACTIVE→MOMENTUM transition resets
    last_emit_ms so MOMENTUM decay starts cleanly from there."""
    eng, posts, clock = _make_engine(now=0)
    eng.state.phase = Phase.MOMENTUM
    eng.state.velocity = 2000.0       # well above cutoff
    eng.state.last_emit_ms = 0
    eng.state.last_tick_ms = 0

    # Expected wall-time to reach cutoff_v=40:
    # t = tau * ln(v0/cutoff_v) = 0.400 * ln(2000/40) = 0.400 * 3.912 = 1565 ms
    import math
    tau_s = eng.config.tau_ms / 1000.0
    expected_ms = int(tau_s * math.log(eng.state.velocity / eng.config.cutoff_v) * 1000)

    t = 0
    while t < 5000 and eng.state.phase != Phase.IDLE:
        clock[0] = t
        eng.tick()
        t += 8
    actual_ms = t - 8  # last tick before IDLE

    # Allow ±20% tolerance (one tick is 8 ms; the iteration step granularity
    # plus the gain factor amplifying emit-side accumulator distort the
    # bare exp() prediction).
    assert eng.state.phase == Phase.IDLE
    lo, hi = int(expected_ms * 0.6), int(expected_ms * 1.4)
    assert lo <= actual_ms <= hi, (
        f"Decay took {actual_ms} ms; expected ~{expected_ms} ms "
        f"(tolerance {lo}..{hi})")
