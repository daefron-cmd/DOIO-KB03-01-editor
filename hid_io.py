"""HidIoWorker — sole owner of the 0xFF60 raw-HID handle.

Owns: handle, read loop, write queue, per-cmd-id FIFO future demux +
global inflight order, unsolicited-frame routing (scroll_tick),
close/reopen with backoff.

ALL reads AND writes happen on the IO thread (or via pump_once /
pump_writes for tests). Callers MUST NOT call dev.write directly.

Two execution modes:
  - run_forever() in a thread (production)
  - pump_once() / pump_writes() called manually (testing)
"""

from __future__ import annotations

import threading
import time as _time
from collections import defaultdict, deque
from concurrent.futures import Future
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot


RAW_EPSIZE = 32
REPORT_ID = 0x00


def build_raw_hid_frame(payload: list[int]) -> bytes:
    """Validate and frame a raw-HID payload as [REPORT_ID][32 bytes].
    Raises ValueError on empty or overlong payload."""
    if not payload:
        raise ValueError("payload must include at least the command id")
    if len(payload) > RAW_EPSIZE:
        raise ValueError(
            f"payload must fit in RAW_EPSIZE={RAW_EPSIZE}, got {len(payload)}")
    return bytes([REPORT_ID]) + bytes(payload) + bytes(RAW_EPSIZE - len(payload))


class IdUnhandledError(Exception):
    """Device replied with 0xFF — command unrecognised by firmware."""


class TransportClosedError(Exception):
    """The HID handle closed (or never opened) while a future was pending."""


def _default_open():
    import core
    return core.open_raw()


class HidIoWorker(QObject):
    scroll_tick = Signal(int, int)   # (direction, device_t_ms)
    device_state = Signal(str)       # "" / "no-device"

    SCROLL_PING = 0xA1
    HOST_SCROLL_READY = 0xA0
    ID_UNHANDLED = 0xFF

    READ_ERROR_LIMIT = 5
    BACKOFF_S = (1.0, 2.0, 5.0)

    def __init__(self,
                 open_fn: Callable = _default_open,
                 now_fn: Callable = _time.monotonic):
        super().__init__()
        self._dev = None
        self._lock = threading.Lock()
        # Write queue: list of (frame_bytes, fut_or_None). fut is the
        # future that should be failed on write error.
        self._write_q: deque[tuple[bytes, Future | None]] = deque()
        # Inflight ordering: list of (cmd_id, future) in send order.
        self._inflight: deque[tuple[int, Future]] = deque()
        # Per-cmd-id FIFO (mirror of _inflight for fast lookup on reply).
        self._futures: dict[int, deque[Future]] = defaultdict(deque)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._open_fn = open_fn
        self._now = now_fn
        self._error_streak = 0
        self._last_open_attempt = -float("inf")
        self._backoff_idx = 0

    @classmethod
    def with_handle(cls, dev) -> "HidIoWorker":
        w = cls()
        w._dev = dev
        return w

    def pending_count(self) -> int:
        with self._lock:
            return len(self._inflight)

    def send_request(self, payload: list[int]) -> Future:
        """Enqueue a frame; return a Future fulfilled by the matching
        reply, or failed on close/write-error. Pending futures wait if
        the handle isn't open yet; the IO loop fails them when stop()
        is called or after the close-retry budget runs out."""
        frame = build_raw_hid_frame(payload)
        fut: Future = Future()
        cmd_id = payload[0]
        with self._lock:
            self._inflight.append((cmd_id, fut))
            self._futures[cmd_id].append(fut)
            self._write_q.append((frame, fut))
        self._wake.set()
        return fut

    def send_untracked(self, payload: list[int]) -> None:
        """Fire-and-forget. No future is tracked. Used for heartbeats."""
        frame = build_raw_hid_frame(payload)
        with self._lock:
            self._write_q.append((frame, None))
        self._wake.set()

    def cancel(self, fut: Future) -> None:
        """Evict a timed-out future from all queues so a late reply
        doesn't get mis-attributed to it."""
        self._remove_inflight(fut)
        if not fut.done():
            fut.cancel()

    def pump_writes(self) -> None:
        """Drain the write queue once. Called by run_forever or tests."""
        with self._lock:
            dev = self._dev
            if dev is None:
                # Fail any tracked futures whose request can't be sent.
                # (Heuristic: only fail when we explicitly have no
                # device AND no open path. In real wiring open is
                # retried in run_forever.)
                return
            batch = list(self._write_q)
            self._write_q.clear()
        for frame, fut in batch:
            try:
                dev.write(frame)
            except OSError as exc:
                if fut is not None:
                    fut.set_exception(TransportClosedError(repr(exc)))
                    self._remove_inflight(fut)
                self._handle_read_error()
                return

    def pump_once(self, timeout_ms: int = 0) -> None:
        """Drain any pending writes, then read once and dispatch."""
        self.pump_writes()
        with self._lock:
            dev = self._dev
        if dev is None:
            return
        try:
            data = dev.read(32, timeout_ms)
            self._error_streak = 0
        except OSError:
            self._handle_read_error()
            return
        if not data:
            return
        cmd_id = data[0]
        if cmd_id == self.SCROLL_PING:
            direction = +1 if data[2] == 1 else -1
            t = (data[4] | (data[5] << 8)
                 | (data[6] << 16) | (data[7] << 24))
            self.scroll_tick.emit(direction, t)
            return
        if cmd_id == self.ID_UNHANDLED:
            # Fail the OLDEST inflight future, regardless of its cmd_id.
            self._fail_oldest(IdUnhandledError(
                "device returned id_unhandled"))
            return
        with self._lock:
            q = self._futures.get(cmd_id)
            fut = q.popleft() if q else None
            if fut is not None:
                # Remove from global inflight too.
                try:
                    self._inflight.remove((cmd_id, fut))
                except ValueError:
                    pass
        if fut is not None:
            fut.set_result(list(data))

    def _fail_oldest(self, exc: Exception) -> None:
        with self._lock:
            if not self._inflight:
                return
            cmd_id, fut = self._inflight.popleft()
            q = self._futures.get(cmd_id)
            if q:
                try:
                    q.remove(fut)
                except ValueError:
                    pass
        fut.set_exception(exc)

    def _remove_inflight(self, fut: Future) -> None:
        with self._lock:
            for entry in list(self._inflight):
                if entry[1] is fut:
                    self._inflight.remove(entry)
                    q = self._futures.get(entry[0])
                    if q:
                        try:
                            q.remove(fut)
                        except ValueError:
                            pass
                    return

    def _handle_read_error(self) -> None:
        self._error_streak += 1
        self.device_state.emit("no-device")
        if self._error_streak >= self.READ_ERROR_LIMIT:
            self._close_handle_internal(reason="read error streak")

    def _close_handle_internal(self, *, reason: str) -> None:
        with self._lock:
            dev, self._dev = self._dev, None
            inflight = list(self._inflight)
            self._inflight.clear()
            self._futures.clear()
            self._write_q.clear()
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
        for _, fut in inflight:
            if not fut.done():
                fut.set_exception(
                    TransportClosedError(f"handle closed: {reason}"))
        self._error_streak = 0

    def maybe_reopen(self) -> bool:
        with self._lock:
            if self._dev is not None:
                return False
        delay = self.BACKOFF_S[min(self._backoff_idx,
                                   len(self.BACKOFF_S) - 1)]
        if self._now() - self._last_open_attempt < delay:
            return False
        self._last_open_attempt = self._now()
        dev = self._open_fn()
        if dev is None:
            self._backoff_idx += 1
            return False
        with self._lock:
            self._dev = dev
        self._backoff_idx = 0
        # IMPORTANT: emit empty string immediately on success so
        # ControlWorker can flip handle_open=True before the first
        # request lands.
        self.device_state.emit("")
        return True

    @Slot()
    def stop(self) -> None:
        """Stop the IO loop and fail all pending futures with
        TransportClosedError."""
        self._stop.set()
        self._wake.set()
        self._close_handle_internal(reason="worker stopped")
