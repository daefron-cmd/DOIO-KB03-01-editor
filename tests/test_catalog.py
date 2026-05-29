from catalog import (
    KEYCODES, decode, mod, layer,
    SHIFT, ALT, MO,
    KC_8, KC_9,
)


def test_known_encode_values():
    # KC_8 HID usage is 0x25 (KC_1..KC_9 = 0x1E..0x26; 0x1F is KC_2).
    assert KC_8 == 0x25
    assert mod(KC_8, SHIFT, ALT) == 0x0625   # Norwegian Mac '{'
    assert layer(MO, 1) == 0x5221
    assert KEYCODES[0x002F] == "KC_LBRC"      # Norwegian 'å'


def test_right_side_mod_fold_is_distinct():
    # Right Alt encodes as 0x04 | 0x10 = 0x14 in the keycode mod field.
    assert mod(KC_8, ALT, right=True) == 0x1425
    assert mod(KC_8, ALT, right=True) != mod(KC_8, ALT)  # left != right


def test_decode_roundtrips_modded_value():
    assert decode(mod(KC_8, SHIFT, ALT)) == "LShift+LAlt+KC_8"
    assert decode(layer(MO, 1)) == "MO(1)"
    assert decode(0x002F) == "KC_LBRC"


from catalog import CATALOG, render, reverse_index


def test_catalog_keycodes_are_unique():
    seen = {}
    for cat, label, code in CATALOG:
        assert code not in seen, f"dup {code:#06x}: {label} vs {seen[code]}"
        seen[code] = label


def test_render_prefers_friendly_label_then_falls_back():
    # 'å' is in the catalog → friendly label with the QMK name.
    assert render(0x002F) == "å  (KC_LBRC)"
    # An arbitrary non-catalog int falls back to structural decode().
    assert render(0x7821) == "RGB_MOD"  # only if not added as a catalog entry
    assert render(0x1234) == decode(0x1234)


def test_basic_special_present():
    codes = {code for _, _, code in CATALOG}
    assert 0x0000 in codes  # KC_NO
    assert 0x0001 in codes  # KC_TRANSPARENT
