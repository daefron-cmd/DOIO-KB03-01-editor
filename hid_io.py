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
from concurrent.futures import Future, InvalidStateError
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
            f"payload must fit in RAW_EPSIZE={RAW_EPSIZE}, got {len(payload)}"
        )
    return bytes([REPORT_ID]) + bytes(payload) + bytes(RAW_EPSIZE - len(payload))


class IdUnhandledError(Exception):
    """Device replied with 0xFF — command unrecognised by firmware."""


class TransportClosedError(Exception):
    """The HID handle closed (or never opened) while a future was pending."""


def _default_open():
    import core

    return core.open_raw()


class HidIoWorker(QObject):
    scroll_tick = Signal(int, int)  # (direction, device_t_ms)
    device_state = Signal(str)  # "" / "no-device"

    SCROLL_PING = 0xA1
    HOST_SCROLL_READY = 0xA0
    ID_UNHANDLED = 0xFF

    READ_ERROR_LIMIT = 5
    BACKOFF_S = (1.0, 2.0, 5.0)

    def __init__(
        self, open_fn: Callable = _default_open, now_fn: Callable = _time.monotonic
    ):
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
        self._echoes: dict[Future, bytes] = {}
        self._sent: set[Future] = set()
        self._reset_requested = threading.Event()
        self._running = threading.Event()
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
        """Enqueue a request. Offline requests wait for open or cancellation."""
        frame = build_raw_hid_frame(payload)
        fut: Future = Future()
        cmd_id = payload[0]
        with self._lock:
            if self._stop.is_set() or self._reset_requested.is_set():
                fut.set_exception(TransportClosedError("transport is closing"))
                return fut
            self._inflight.append((cmd_id, fut))
            self._futures[cmd_id].append(fut)
            # VIA echoes the address on reads and the value on writes.
            echo_len = {0x02: 3, 0x04: 4, 0x14: 4, 0x08: 3, 0x11: 1}.get(
                cmd_id, len(payload)
            )
            self._echoes[fut] = bytes(payload[:echo_len])
            self._write_q.append((frame, fut))
        self._wake.set()
        return fut

    def send_untracked(self, payload: list[int]) -> None:
        """Fire-and-forget. No future is tracked. Used for heartbeats."""
        frame = build_raw_hid_frame(payload)
        with self._lock:
            if (
                self._dev is None
                or self._stop.is_set()
                or self._reset_requested.is_set()
            ):
                return
            # Only the most recent unsent heartbeat is useful.
            self._write_q = deque(
                (queued, fut)
                for queued, fut in self._write_q
                if fut is not None or queued[1] != payload[0]
            )
            self._write_q.append((frame, None))
        self._wake.set()

    def cancel(self, fut: Future) -> None:
        """Drop unsent work; reset the stream if a sent request timed out.

        VIA has no transaction IDs. Removing a sent future alone would let
        its late reply complete a newer request, even for the same address.
        Closing and draining the handle is performed by the IO thread.
        """
        with self._lock:
            if fut.done():
                return
            if fut in self._sent:
                self._reset_requested.set()
            self._remove_inflight_locked(fut)
            self._write_q = deque(
                (frame, queued) for frame, queued in self._write_q if queued is not fut
            )
            fut.cancel()
        self._wake.set()

    def pump_writes(self) -> None:
        """Drain the write queue once. Called by run_forever or tests."""
        if self._reset_requested.is_set():
            self._close_handle_internal(reason="request timed out")
            return
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
        for i, (frame, fut) in enumerate(batch):
            with self._lock:
                if self._reset_requested.is_set() or self._stop.is_set():
                    break
                if fut is not None:
                    if fut.done():
                        self._remove_inflight_locked(fut)
                        continue
                    self._sent.add(fut)
            try:
                dev.write(frame)
            except OSError as exc:
                if fut is not None:
                    self._finish(fut, error=TransportClosedError(repr(exc)))
                    self._remove_inflight(fut)
                # Fail ALL subsequent futures in the batch — they will never
                # be written, so leave them pending would cause them to sit
                # in _inflight until the caller's 1-second cancel timeout.
                for _, remaining_fut in batch[i + 1 :]:
                    if remaining_fut is not None:
                        self._finish(
                            remaining_fut, error=TransportClosedError(repr(exc))
                        )
                        self._remove_inflight(remaining_fut)
                self._handle_read_error()
                return
        if self._reset_requested.is_set():
            self._close_handle_internal(reason="request timed out")

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
        if len(data) != RAW_EPSIZE or self._reset_requested.is_set():
            return
        cmd_id = data[0]
        if cmd_id == self.SCROLL_PING:
            direction = +1 if data[2] == 1 else -1
            t = data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24)
            self.scroll_tick.emit(direction, t)
            return
        if cmd_id == self.ID_UNHANDLED:
            # Fail the OLDEST inflight future, regardless of its cmd_id.
            self._fail_oldest(IdUnhandledError("device returned id_unhandled"))
            return
        with self._lock:
            q = self._futures.get(cmd_id)
            fut = q[0] if q else None
            if fut is not None:
                echo = self._echoes[fut]
                if (
                    fut not in self._sent
                    or self._reset_requested.is_set()
                    or bytes(data[: len(echo)]) != echo
                ):
                    return
                self._remove_inflight_locked(fut)
                self._finish(fut, result=list(data))

    def _fail_oldest(self, exc: Exception) -> None:
        with self._lock:
            if not self._inflight:
                return
            _, fut = self._inflight[0]
            if fut not in self._sent or self._reset_requested.is_set():
                return
            self._remove_inflight_locked(fut)
            self._finish(fut, error=exc)

    @staticmethod
    def _finish(fut: Future, *, result=None, error=None) -> None:
        try:
            if error is not None:
                fut.set_exception(error)
            else:
                fut.set_result(result)
        except InvalidStateError:
            # Cancellation can race with a native HID read/write completing.
            pass

    def _remove_inflight(self, fut: Future) -> None:
        with self._lock:
            self._remove_inflight_locked(fut)

    def _remove_inflight_locked(self, fut: Future) -> None:
        self._echoes.pop(fut, None)
        self._sent.discard(fut)
        for entry in list(self._inflight):
            if entry[1] is fut:
                self._inflight.remove(entry)
                q = self._futures.get(entry[0])
                if q:
                    q.remove(fut)
                return

    def _handle_read_error(self) -> None:
        # Single transient errors must NOT drop the readiness gate; only a
        # streak that triggers close should emit "no-device". A successful
        # read in pump_once resets _error_streak silently.
        self._error_streak += 1
        if self._error_streak >= self.READ_ERROR_LIMIT:
            self._close_handle_internal(reason="read error streak")

    def _close_handle_internal(self, *, reason: str) -> None:
        with self._lock:
            dev, self._dev = self._dev, None
            inflight = list(self._inflight)
            self._inflight.clear()
            self._futures.clear()
            self._echoes.clear()
            self._sent.clear()
            self._write_q.clear()
            self._reset_requested.clear()
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
            self.device_state.emit("no-device")
        for _, fut in inflight:
            self._finish(fut, error=TransportClosedError(f"handle closed: {reason}"))
        self._error_streak = 0

    def maybe_reopen(self) -> bool:
        with self._lock:
            if self._dev is not None:
                return False
        delay = self.BACKOFF_S[
            max(0, min(self._backoff_idx - 1, len(self.BACKOFF_S) - 1))
        ]
        if self._now() - self._last_open_attempt < delay:
            return False
        self._last_open_attempt = self._now()
        dev = None
        try:
            dev = self._open_fn()
            if dev is not None:
                # VIA processes requests in order. Its protocol-version reply
                # is a barrier: earlier replies have been consumed before any
                # new application request is admitted. A quiet read alone
                # cannot establish that boundary after a timeout.
                dev.write(build_raw_hid_frame([0x01]))
                for _ in range(50):
                    if self._stop.is_set():
                        raise OSError("stopped while opening")
                    reply = dev.read(RAW_EPSIZE, 20)
                    if len(reply) == RAW_EPSIZE and reply[0] == 0x01:
                        break
                else:
                    raise OSError("VIA synchronization timed out")
        except OSError:
            # A temporarily busy or unavailable HID interface is a normal
            # reconnect condition. Keep the worker loop alive so the next
            # backoff slot can acquire it.
            if dev is not None:
                try:
                    dev.close()
                except OSError:
                    pass
            self._backoff_idx += 1
            return False
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
    def run_forever(self) -> None:
        """Production loop. Run on a QThread.started signal."""
        self._running.set()
        try:
            self._run_loop()
        finally:
            self._close_handle_internal(reason="worker stopped")
            self._running.clear()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                have_dev = self._dev is not None
            if not have_dev:
                self.maybe_reopen()
                with self._lock:
                    have_dev = self._dev is not None
                if not have_dev:
                    # Sleep up to 200 ms or until something is enqueued
                    # or stop is signalled.
                    self._wake.wait(timeout=0.2)
                    self._wake.clear()
                    continue
            self.pump_once(timeout_ms=20)
            # If new writes were enqueued, the wake event lets us drain
            # them on the next iteration without blocking on read.
            self._wake.clear()

    @Slot()
    def stop(self) -> None:
        """Stop the IO loop and fail all pending futures with
        TransportClosedError."""
        self._stop.set()
        self._wake.set()
        if not self._running.is_set():
            self._close_handle_internal(reason="worker stopped")
