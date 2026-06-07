"""Host-side inferred QMK layer state.

This is intentionally conservative: it never queries or writes firmware state.
It only interprets the already-read keymap snapshot plus physical matrix
press/release events from VIA switch_matrix_state.
"""

from catalog import KC_TRNS, TO, MO, DF, TG
from model import Snapshot

LAYER_RANGE_START = 0x5200
LAYER_RANGE_END = 0x52FF


class InferredLayerState:
    def __init__(self, layer_count: int = 4):
        self.layer_count = layer_count
        self.default_mask = 1
        self.layer_mask = 0
        self._held: dict[int, tuple[str, int]] = {}

    @property
    def effective_mask(self) -> int:
        return self.default_mask | self.layer_mask

    @property
    def highest(self) -> int:
        mask = self.effective_mask
        for layer in reversed(range(self.layer_count)):
            if mask & (1 << layer):
                return layer
        return 0

    def reset(self) -> None:
        self.default_mask = 1
        self.layer_mask = 0
        self._held.clear()

    def resolve_key(self, snapshot: Snapshot, col: int) -> int:
        """Resolve a matrix column through active layers, honoring KC_TRNS."""
        for layer in reversed(range(min(self.layer_count, len(snapshot.keymap)))):
            if self.effective_mask & (1 << layer):
                code = snapshot.keymap[layer][col]
                if code != KC_TRNS:
                    return code
        return snapshot.keymap[0][col]

    def press(self, snapshot: Snapshot, col: int) -> int:
        """Apply a key press to the inferred layer model; return resolved code."""
        code = self.resolve_key(snapshot, col)
        if not (LAYER_RANGE_START <= code <= LAYER_RANGE_END):
            return code

        op = code & 0xE0
        target = code & 0x1F
        if target >= self.layer_count:
            return code

        if op == TO:
            self.layer_mask = 1 << target
        elif op == MO:
            self.layer_mask |= 1 << target
            self._held[col] = ("MO", target)
        elif op == TG:
            self.layer_mask ^= 1 << target
        elif op == DF:
            self.default_mask = 1 << target
        return code

    def release(self, col: int) -> None:
        action = self._held.pop(col, None)
        if action is None:
            return
        kind, target = action
        if kind == "MO":
            self.layer_mask &= ~(1 << target)
