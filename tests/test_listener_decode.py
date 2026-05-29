from listener import decode_keyboard_report, decode_consumer_report


def test_keyboard_report_extracts_mods_and_keys():
    # byte0 = modifiers, byte1 reserved, byte2.. = keycodes
    report = [0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]
    mods, keys = decode_keyboard_report(report)
    assert mods == 0x06
    assert keys == [0x04]


def test_keyboard_report_release_is_empty():
    report = [0x00] * 8
    mods, keys = decode_keyboard_report(report)
    assert mods == 0x00 and keys == []


def test_consumer_report_le16_usage(monkeypatch):
    # CONSUMER_USAGE_OFFSET is verified on real hardware (Task 11). The decoder
    # reads a little-endian 16-bit usage at that offset.
    import listener
    listener.CONSUMER_USAGE_OFFSET = 1
    report = [0x00, 0xE9, 0x00, 0x00]  # Vol+ = 0x00E9 LE at offset 1
    assert decode_consumer_report(report) == [0xE9]
