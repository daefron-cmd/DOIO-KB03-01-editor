import json

from scroll import ScrollConfig, load_config, save_config


def test_load_missing_file_returns_defaults(tmp_path):
    c = load_config(tmp_path / "scroll.json")
    assert c == ScrollConfig()


def test_load_malformed_file_returns_defaults(tmp_path):
    p = tmp_path / "scroll.json"
    p.write_text("{not json")
    c = load_config(p)
    assert c == ScrollConfig()


def test_load_partial_file_merges_with_defaults(tmp_path):
    p = tmp_path / "scroll.json"
    p.write_text(json.dumps({
        "tau_ms": 800,
        "invert": True,
        "brake_on_reverse": True,
    }))
    c = load_config(p)
    assert c.tau_ms == 800
    assert c.invert is True
    assert c.brake_on_reverse is True
    assert c.impulse_per_detent == ScrollConfig().impulse_per_detent


def test_load_clamps_out_of_range_values(tmp_path):
    p = tmp_path / "scroll.json"
    p.write_text(json.dumps({
        "impulse_per_detent": 100000,
        "tau_ms": -50,
        "max_gain": 9999,
        "cutoff_v": -1,
    }))
    c = load_config(p)
    assert c.impulse_per_detent <= 500
    assert c.tau_ms >= 50
    assert c.max_gain <= 12
    assert c.cutoff_v >= 5


def test_load_rejects_invalid_threshold_ordering(tmp_path):
    p = tmp_path / "scroll.json"
    # coast_threshold < cutoff_v is invalid — must be clamped/raised.
    p.write_text(json.dumps({"coast_threshold": 10, "cutoff_v": 50}))
    c = load_config(p)
    assert c.coast_threshold >= c.cutoff_v


def test_save_and_reload_roundtrip(tmp_path):
    p = tmp_path / "scroll.json"
    c = ScrollConfig(tau_ms=600, invert=True, brake_on_reverse=True)
    save_config(c, p)
    loaded = load_config(p)
    assert loaded == c
