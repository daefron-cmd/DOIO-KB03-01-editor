from model import Snapshot, key_id, enc_id
from catalog import resolve_controls, KC_A, mod, SHIFT, ALT, MO, layer


def _snap(keymap, encoders=None):
    enc = encoders or [[[0, 0] for _ in range(2)] for _ in range(4)]
    return Snapshot(keymap=keymap, encoders=enc,
                    brightness=0, effect=0, speed=0, hue=0, sat=0)


def test_unique_keyboard_match():
    # layer 0 col 1 = KC_A; pressing 'a' (base 0x04, no mods) → that one key.
    km = [[0, KC_A, 0, 0, 0]] + [[0] * 5 for _ in range(3)]
    snap = _snap(km)
    assert resolve_controls(snap, "keyboard", 0x00, [KC_A]) == [key_id(1)]


def test_flash_all_on_ambiguity():
    # KC_A on both col 0 and col 3 (even on different layers) → both flash.
    km = [[KC_A, 0, 0, 0, 0], [0, 0, 0, KC_A, 0]] + [[0] * 5 for _ in range(2)]
    snap = _snap(km)
    got = resolve_controls(snap, "keyboard", 0x00, [KC_A])
    assert set(got) == {key_id(0), key_id(3)}


def test_non_emitting_keycode_returns_empty():
    # MO(1) is mapped but never appears in a HID report → empty.
    km = [[layer(MO, 1), 0, 0, 0, 0]] + [[0] * 5 for _ in range(3)]
    snap = _snap(km)
    assert resolve_controls(snap, "keyboard", 0x00, []) == []


def test_left_shift_alt_match():
    code = mod(KC_A, SHIFT, ALT)  # left Shift+Alt + A → 0x0604
    km = [[code, 0, 0, 0, 0]] + [[0] * 5 for _ in range(3)]
    snap = _snap(km)
    # report mod byte 0x06 = LShift|LAlt, base KC_A → matches.
    # NOTE: this passes even under the naive (report<<8)|base fold because
    # left Shift+Alt equals the QMK field by coincidence — see the guard below.
    assert resolve_controls(snap, "keyboard", 0x06, [KC_A]) == [key_id(0)]


def test_right_side_fold_guards_naive_bug():
    code = mod(KC_A, ALT, right=True)          # 0x1404
    km = [[code, 0, 0, 0, 0]] + [[0] * 5 for _ in range(3)]
    snap = _snap(km)
    # report 0x40 = Right Alt; the naive (0x40<<8)|0x04 = 0x4004 would NOT
    # match 0x1404 — only the correct fold (high nibble | 0x10) matches.
    assert resolve_controls(snap, "keyboard", 0x40, [KC_A]) == [key_id(0)]


def test_consumer_media_match():
    # encoder 0 dir 1 mapped to KC_AUDIO_VOL_UP (0x00A9); consumer report
    # carries usage 0xE9, which bridges to 0x00A9.
    enc = [[[0, 0x00A9], [0, 0]]] + [[[0, 0], [0, 0]] for _ in range(3)]
    snap = _snap([[0] * 5 for _ in range(4)], encoders=enc)
    assert resolve_controls(snap, "consumer", 0x00, [0xE9]) == [enc_id(0, 1)]
