import core


class FakeHID:
    def __init__(self, replies=None):
        self.writes = []
        self._replies = list(replies or [])

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, length, timeout=0):
        return self._replies.pop(0) if self._replies else [0] * length


def test_set_key_frame():
    dev = FakeHID()
    core.set_key(dev, layer=1, col=2, keycode=0x0625)
    # report-id 0x00, then [SET_KEYCODE, layer, row=0, col, hi, lo] padded to 32
    body = dev.writes[0]
    assert body[0] == 0x00
    assert body[1] == core.DYNAMIC_KEYMAP_SET_KEYCODE
    assert body[2] == 1 and body[3] == 0 and body[4] == 2
    assert body[5] == 0x06 and body[6] == 0x25
    assert len(body) == 33  # 0x00 + 32-byte body


def test_set_encoder_frame():
    dev = FakeHID()
    core.set_encoder(dev, layer=0, enc=1, direction=1, keycode=0x00A9)
    body = dev.writes[0]
    assert body[1] == core.DYNAMIC_KEYMAP_SET_ENCODER
    assert body[2] == 0 and body[3] == 1 and body[4] == 1
    assert body[5] == 0x00 and body[6] == 0xA9


def test_set_color_sends_both_channels_in_one_command():
    dev = FakeHID()
    core.set_color(dev, hue=170, sat=255)
    body = dev.writes[0]
    assert body[1] == core.CUSTOM_SET_VALUE
    assert body[2] == core.RGB_MATRIX_CHANNEL
    assert body[3] == core.LIGHT_COLOR
    assert body[4] == 170 and body[5] == 255


def test_pressed_cols_reads_switch_matrix_state():
    dev = FakeHID(replies=[[
        core.GET_KEYBOARD_VALUE, core.SWITCH_MATRIX_STATE, 0x00, 0b10101]])
    assert core.pressed_cols(dev) == [0, 2, 4]
    body = dev.writes[0]
    assert body[1] == core.GET_KEYBOARD_VALUE
    assert body[2] == core.SWITCH_MATRIX_STATE
    assert body[3] == 0x00  # switch_matrix_state offset


def test_pressed_cols_returns_none_when_switch_matrix_state_unhandled():
    dev = FakeHID(replies=[[0xFF] + [0] * 31])
    assert core.pressed_cols(dev) is None
