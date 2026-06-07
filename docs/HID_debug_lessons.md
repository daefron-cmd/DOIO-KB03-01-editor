# HID Debug Lessons

## VIA `switch_matrix_state` Response Has an Offset Byte

**Failure mode:** a raw-HID/VIA fallback appears to be available, but physical
key presses never show up. Media/consumer HID reports may still work, making the
bug look like a keyboard permission or event-routing issue.

For QMK/VIA `id_get_keyboard_value` + `id_switch_matrix_state`, request an
explicit offset and parse the matrix rows after that offset byte:

```text
request:  02 03 00
response: 02 03 00 <row0> ...
          |  |  |   |
          |  |  |   first matrix row byte
          |  |  offset
          |  value id: switch_matrix_state
          command id: get_keyboard_value
```

Do **not** read `response[2]` as the row. That byte is the offset and is usually
`0x00`, which makes the fallback look alive while always reporting no pressed
columns.

Correct shape:

```python
r = cmd(dev, GET_KEYBOARD_VALUE, SWITCH_MATRIX_STATE, 0x00, timeout=100)
if r[0] == GET_KEYBOARD_VALUE and r[1] == SWITCH_MATRIX_STATE and len(r) >= 4:
    row0 = r[3]
```

Expected values for a 1-row, 5-column board:

```text
no key:  02 03 00 00 ...
col 0:   02 03 00 01 ...
col 1:   02 03 00 02 ...
col 2:   02 03 00 04 ...
col 3:   02 03 00 08 ...
col 4:   02 03 00 10 ...
```

Also remember: normal keyboard HID access and consumer/media HID access are
separate paths on composite USB devices. If media reports work but keyboard
reports fail, inspect the interfaces separately before assuming app-level
shortcut interception.
