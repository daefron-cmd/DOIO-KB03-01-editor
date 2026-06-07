from catalog import KC_A, KC_TRNS, TO, MO, layer
from inferred_layer import InferredLayerState
from model import Snapshot


def _snap(keymap):
    return Snapshot(
        keymap=keymap,
        encoders=[[[0, 0] for _ in range(2)] for _ in range(4)],
        brightness=0,
        effect=0,
        speed=0,
        hue=0,
        sat=0,
    )


def test_stock_doio_to_cycle_is_inferred_from_col_3():
    snap = _snap([
        [0, 0, 0, layer(TO, 1), 0],
        [0, 0, 0, layer(TO, 2), 0],
        [0, 0, 0, layer(TO, 3), 0],
        [0, 0, 0, layer(TO, 0), 0],
    ])
    state = InferredLayerState(layer_count=4)

    for expected in (1, 2, 3, 0):
        state.press(snap, 3)
        assert state.highest == expected


def test_resolve_key_falls_through_transparent_layers():
    snap = _snap([
        [KC_A, 0, 0, 0, 0],
        [KC_TRNS, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
    ])
    state = InferredLayerState(layer_count=4)
    state.layer_mask = 1 << 1

    assert state.resolve_key(snap, 0) == KC_A


def test_momentary_layer_is_released():
    snap = _snap([
        [0, layer(MO, 2), 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
    ])
    state = InferredLayerState(layer_count=4)

    state.press(snap, 1)
    assert state.highest == 2
    state.release(1)
    assert state.highest == 0
