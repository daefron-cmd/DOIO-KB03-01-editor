"""Neutral data types shared by core, catalog and ui. No Qt, no hardware."""

from dataclasses import dataclass

# control_id is a neutral structural position, never a core-owned type.
ControlId = tuple


def key_id(col: int) -> ControlId:
    return ("key", col)


def enc_id(enc: int, direction: int) -> ControlId:
    return ("encoder", enc, direction)


@dataclass
class Snapshot:
    keymap: list[list[int]]            # [layer][col] -> 16-bit keycode
    encoders: list[list[list[int]]]    # [layer][enc][dir] -> 16-bit keycode
    brightness: int
    effect: int
    speed: int
    hue: int
    sat: int


@dataclass(frozen=True)
class LightingState:
    brightness: int
    effect: int
    speed: int
    hue: int
    sat: int

    @classmethod
    def from_snapshot(cls, snap: Snapshot) -> "LightingState":
        return cls(
            brightness=snap.brightness,
            effect=snap.effect,
            speed=snap.speed,
            hue=snap.hue,
            sat=snap.sat,
        )
