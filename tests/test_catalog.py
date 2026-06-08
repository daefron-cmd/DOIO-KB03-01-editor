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
    # Apple-convention display: Control, Option, Shift, Command (stacked, no
    # separator); 'R' prefix only when the right-side bit is set.
    assert decode(mod(KC_8, SHIFT, ALT)) == "⌥⇧+KC_8"
    assert decode(mod(KC_8, ALT, right=True)) == "R⌥+KC_8"
    assert decode(layer(MO, 1)) == "MO(1)"
    assert decode(0x002F) == "KC_LBRC"


from catalog import (
    CATALOG, render, reverse_index,
    _BASE_CATALOG, _apply_layout, LAYOUTS, ACTIVE_LAYOUT,
    KC_LBRC, KC_SCLN, KC_QUOTE,
)


def test_catalog_keycodes_are_unique():
    seen = {}
    for cat, label, code in CATALOG:
        assert code not in seen, f"dup {code:#06x}: {label} vs {seen[code]}"
        seen[code] = label


def test_active_layout_overrides_base_entry():
    # NO-Mac is active; KC_LBRC (0x002F) is overridden from US-Mac '[' in
    # 'symbols' to 'å' in 'letters'. Category, name, and label all change;
    # the QMK code stays in parens.
    entries = [e for e in CATALOG if e[2] == KC_LBRC]
    assert entries == [("letters", "å  (KC_LBRC)", KC_LBRC)]
    # The US-Mac base entry that was there is gone (replaced, not duplicated).
    assert ("symbols", "[  (KC_LBRC)", KC_LBRC) not in CATALOG


def test_active_layout_appends_new_entries():
    # NO-Mac Option-combos aren't in the base — they're appended.
    assert ("symbols", "[  (⌥+KC_8)", mod(KC_8, ALT)) in CATALOG
    assert ("symbols", "{  (⌥⇧+KC_8)", mod(KC_8, SHIFT, ALT)) in CATALOG


def test_empty_layout_keeps_base_us_mac_labels():
    # With no overrides, the base catalog labels survive verbatim — proving
    # that the base IS US-Mac and layouts are pure deltas.
    catalog = _apply_layout(_BASE_CATALOG, ())
    assert catalog == _BASE_CATALOG
    by_code = {c: (cat, label) for cat, label, c in catalog}
    assert by_code[KC_LBRC] == ("symbols", "[  (KC_LBRC)")
    assert by_code[KC_SCLN] == ("symbols", ";  (KC_SCLN)")
    assert by_code[KC_QUOTE] == ("symbols", "'  (KC_QUOTE)")


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


def test_mouse_wheel_keycodes_present():
    # QMK basic-keycode IDs for the four wheel directions.
    assert KEYCODES[0x00D9] == "KC_MS_WH_UP"
    assert KEYCODES[0x00DA] == "KC_MS_WH_DOWN"
    assert KEYCODES[0x00DB] == "KC_MS_WH_LEFT"
    assert KEYCODES[0x00DC] == "KC_MS_WH_RIGHT"
    mouse = {code for cat, _, code in CATALOG if cat == "mouse"}
    assert {0x00D9, 0x00DA, 0x00DB, 0x00DC} <= mouse


from catalog import CONSUMER_USAGE


def test_consumer_usage_bridges_to_qmk_keycodes():
    assert CONSUMER_USAGE[0xE9] == 0x00A9   # Vol+  -> KC_AUDIO_VOL_UP
    assert CONSUMER_USAGE[0xEA] == 0x00AA   # Vol-  -> KC_AUDIO_VOL_DOWN
    assert CONSUMER_USAGE[0xE2] == 0x00A8   # Mute  -> KC_AUDIO_MUTE
    assert CONSUMER_USAGE[0xB5] == 0x00AB   # Next  -> KC_MEDIA_NEXT_TRACK
    assert CONSUMER_USAGE[0xB6] == 0x00AC   # Prev  -> KC_MEDIA_PREV_TRACK
    assert CONSUMER_USAGE[0xB7] == 0x00AD   # Stop  -> KC_MEDIA_STOP
    assert CONSUMER_USAGE[0xCD] == 0x00AE   # Play  -> KC_MEDIA_PLAY_PAUSE
