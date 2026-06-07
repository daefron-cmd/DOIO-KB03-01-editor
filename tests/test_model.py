from model import LightingState, Snapshot, key_id, enc_id


def test_control_id_helpers_are_neutral_tuples():
    assert key_id(2) == ("key", 2)
    assert enc_id(0, 1) == ("encoder", 0, 1)


def test_snapshot_holds_layered_data():
    snap = Snapshot(
        keymap=[[0] * 5 for _ in range(4)],
        encoders=[[[0, 0] for _ in range(2)] for _ in range(4)],
        brightness=200, effect=4, speed=128, hue=170, sat=255,
    )
    assert snap.keymap[1][2] == 0
    assert snap.encoders[0][1][0] == 0
    assert snap.brightness == 200


def test_lighting_state_from_snapshot():
    snap = Snapshot(
        keymap=[[0] * 5 for _ in range(4)],
        encoders=[[[0, 0] for _ in range(2)] for _ in range(4)],
        brightness=180, effect=2, speed=64, hue=120, sat=220,
    )
    assert LightingState.from_snapshot(snap) == LightingState(
        brightness=180, effect=2, speed=64, hue=120, sat=220)
