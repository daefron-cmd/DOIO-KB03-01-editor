import pytest

from hid_io import (
    HidIoWorker,
    IdUnhandledError,
    TransportClosedError,
    RAW_EPSIZE,
    build_raw_hid_frame,
)


class FakeHID:
    """Single-handle fake: writes captured to a list; reads pop from a
    deque. read() returns [] on empty (simulates timeout)."""

    def __init__(self):
        self.writes: list[bytes] = []
        self._replies: list[list[int]] = []
        self._closed = False

    def write(self, data):
        if self._closed:
            raise OSError("closed")
        self.writes.append(bytes(data))
        if data[1] == 0x01:
            self.queue_reply([0x01, 0, 12])
        return len(data)

    def read(self, n, timeout=0):
        if self._closed:
            raise OSError("closed")
        if self._replies:
            return self._replies.pop(0)
        return []

    def queue_reply(self, reply: list[int]):
        padded = list(reply) + [0] * max(0, 32 - len(reply))
        self._replies.append(padded[:32])

    def close(self):
        self._closed = True


# --- frame builder validation ---


def test_build_raw_hid_frame_is_report_id_plus_32_bytes():
    frame = build_raw_hid_frame([0xA0, 0x01])
    assert len(frame) == 1 + RAW_EPSIZE
    assert frame[0] == 0x00  # report id
    assert frame[1] == 0xA0  # cmd id
    assert frame[2] == 0x01  # version
    assert frame[3:] == bytes(RAW_EPSIZE - 2)  # zero-padded


def test_build_raw_hid_frame_rejects_empty_payload():
    with pytest.raises(ValueError):
        build_raw_hid_frame([])


def test_build_raw_hid_frame_rejects_over_32_bytes():
    with pytest.raises(ValueError):
        build_raw_hid_frame([0xA0] + [0] * 32)


# --- write enqueue + IO-thread drain ---


def test_send_request_enqueues_and_drains_on_pump():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0, 0, 2])
    # Nothing written yet — caller doesn't touch dev.
    # Actually: with_handle bypasses the queue for tests; tighten to
    # require explicit pump_writes.
    worker.pump_writes()
    assert len(dev.writes) == 1
    dev.queue_reply([0x04, 0, 0, 2, 0x06, 0x25])
    worker.pump_once()
    assert fut.done()
    assert fut.result(timeout=0.1)[0] == 0x04


def test_send_untracked_writes_but_creates_no_future():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    worker.send_untracked([0xA0, 0x01])
    worker.pump_writes()
    assert len(dev.writes) == 1
    assert worker.pending_count() == 0


def test_send_request_without_device_stays_pending_until_close():
    worker = HidIoWorker(open_fn=lambda: None)
    fut = worker.send_request([0x04])
    assert not fut.done()  # waits for handle
    worker.stop()  # close: fails all pending
    with pytest.raises(TransportClosedError):
        fut.result(timeout=0.1)


def test_two_concurrent_requests_resolve_in_fifo_order():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    f1 = worker.send_request([0x04, 0, 0, 1])
    f2 = worker.send_request([0x04, 0, 0, 2])
    worker.pump_writes()
    dev.queue_reply([0x04, 0, 0, 1, 0xAA, 0xAA])
    dev.queue_reply([0x04, 0, 0, 2, 0xBB, 0xBB])
    worker.pump_once()
    worker.pump_once()
    r1 = f1.result(timeout=0.1)
    r2 = f2.result(timeout=0.1)
    assert r1[4:6] == [0xAA, 0xAA]
    assert r2[4:6] == [0xBB, 0xBB]


def test_id_unhandled_raises_on_request_future():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x99])  # made-up unhandled command
    worker.pump_writes()
    dev.queue_reply([0xFF])
    worker.pump_once()
    with pytest.raises(IdUnhandledError):
        fut.result(timeout=0.1)


def test_scroll_ping_emits_signal_no_future_side_effect():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    received = []
    worker.scroll_tick.connect(lambda d, t: received.append((d, t)))
    # 0xA1, version=1, dir=1 (CW=down), flags=0, timestamp=0x04030201
    dev.queue_reply([0xA1, 0x01, 0x01, 0x00, 0x01, 0x02, 0x03, 0x04])
    worker.pump_once()
    assert received == [(+1, 0x04030201)]
    assert worker.pending_count() == 0


def test_scroll_ping_direction_zero_means_up():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    received = []
    worker.scroll_tick.connect(lambda d, t: received.append((d, t)))
    dev.queue_reply([0xA1, 0x01, 0x00, 0x00, 0, 0, 0, 0])
    worker.pump_once()
    assert received == [(-1, 0)]


def test_read_error_streak_closes_handle_and_fails_pending():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0])
    worker.pump_writes()

    # Force read errors
    def bad_read(*a, **kw):
        raise OSError("boom")

    dev.read = bad_read
    states = []
    worker.device_state.connect(lambda s: states.append(s))
    for _ in range(5):
        worker.pump_once()
    assert states.count("no-device") >= 1
    assert worker._dev is None
    # Pending future failed with TransportClosedError
    with pytest.raises(TransportClosedError):
        fut.result(timeout=0.1)


def test_transient_read_error_does_not_emit_no_device():
    """A single OSError followed by a successful read must NOT flip the
    handle_open readiness gate. Only a streak that closes the handle
    should emit 'no-device'."""
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    states = []
    worker.device_state.connect(lambda s: states.append(s))

    # One transient read error
    original_read = dev.read
    call_count = [0]

    def flaky_read(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise OSError("transient")
        return original_read(*a, **kw)

    dev.read = flaky_read

    worker.pump_once()  # error #1 — streak 1
    worker.pump_once()  # success — streak resets to 0

    assert states == [], f"transient error spuriously emitted device_state: {states}"
    assert worker._dev is dev  # not closed
    assert worker._error_streak == 0


def test_write_error_fails_associated_future():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0])
    dev.close()  # closing makes write raise
    worker.pump_writes()
    with pytest.raises(TransportClosedError):
        fut.result(timeout=0.1)


def test_close_handle_fails_all_pending_futures():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    f1 = worker.send_request([0x04, 0])
    f2 = worker.send_request([0x05, 0])
    f3 = worker.send_request([0x14, 0])
    worker._close_handle_internal(reason="test")
    for f in (f1, f2, f3):
        with pytest.raises(TransportClosedError):
            f.result(timeout=0.1)


def test_id_unhandled_fails_oldest_global_inflight():
    """0xFF must fail the OLDEST inflight future regardless of its
    command id (NOT 'first queue found in a dict iteration')."""
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    first = worker.send_request([0x04, 0])  # cmd 0x04 first
    second = worker.send_request([0x05, 0])  # cmd 0x05 second
    worker.pump_writes()
    dev.queue_reply([0xFF])
    worker.pump_once()
    with pytest.raises(IdUnhandledError):
        first.result(timeout=0.1)
    assert not second.done()


def test_id_unhandled_ordering_with_dict_insertion_race():
    """Insert a new cmd_id between send and reply; 0xFF must still
    fail the OLDEST not the new one."""
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    a = worker.send_request([0x04, 0])
    b = worker.send_request([0x99, 0])  # never-before-seen cmd id
    worker.pump_writes()
    dev.queue_reply([0xFF])
    worker.pump_once()
    with pytest.raises(IdUnhandledError):
        a.result(timeout=0.1)
    assert not b.done()


def test_open_with_backoff_does_not_busy_loop():
    """Backoff schedule: 1 s, 2 s, 5 s."""
    attempts = []
    times = [0.0]

    def fake_open():
        attempts.append(times[0])
        return None

    worker = HidIoWorker(open_fn=fake_open, now_fn=lambda: times[0])
    worker.maybe_reopen()
    assert len(attempts) == 1
    times[0] = 0.5
    worker.maybe_reopen()
    assert len(attempts) == 1
    times[0] = 1.1
    worker.maybe_reopen()
    assert len(attempts) == 2
    times[0] = 3.2
    worker.maybe_reopen()
    assert len(attempts) == 3


def test_successful_reopen_emits_device_state_empty():
    dev = FakeHID()
    times = [0.0]
    worker = HidIoWorker(open_fn=lambda: dev, now_fn=lambda: times[0])
    states = []
    worker.device_state.connect(lambda s: states.append(s))
    times[0] = 10.0
    assert worker.maybe_reopen() is True
    assert states == [""]


def test_open_error_is_retried_instead_of_escaping_worker_loop():
    dev = FakeHID()
    times = [0.0]
    attempts = [0]

    def flaky_open():
        attempts[0] += 1
        if attempts[0] == 1:
            raise OSError("temporarily unavailable")
        return dev

    worker = HidIoWorker(open_fn=flaky_open, now_fn=lambda: times[0])

    assert worker.maybe_reopen() is False
    assert worker._dev is None
    times[0] = 1.1
    assert worker.maybe_reopen() is True
    assert worker._dev is dev


def test_cancel_evicts_future_so_late_reply_is_dropped():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0])
    worker.pump_writes()
    worker.cancel(fut)
    # Late reply for cmd 0x04 arrives — there is no future to fulfil.
    dev.queue_reply([0x04, 0, 0, 0, 0, 0])
    worker.pump_once()
    assert fut.cancelled()


def test_stale_reply_after_close_is_dropped_silently():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0])
    worker.pump_writes()
    worker._close_handle_internal(reason="test")
    # A reply arriving after close (re-attach a new dev): no crash, no
    # future to fulfil — the demux must just drop it.
    new_dev = FakeHID()
    worker._dev = new_dev
    new_dev.queue_reply([0x04, 0, 0, 0, 0, 0])
    worker.pump_once()
    # fut already failed during close
    with pytest.raises(TransportClosedError):
        fut.result(timeout=0.1)


def test_mid_batch_write_error_fails_all_pending_in_batch():
    """If write fails partway through a batch, all subsequent futures
    in that batch must also fail — they should not sit pending until
    the caller's 1-second timeout."""
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    f1 = worker.send_request([0x04, 0])
    f2 = worker.send_request([0x05, 0])
    f3 = worker.send_request([0x14, 0])
    # First write succeeds, second raises, third would-have-succeeded
    original_write = dev.write
    state = {"calls": 0}

    def write_with_failure(data):
        state["calls"] += 1
        if state["calls"] == 2:
            raise OSError("boom mid-batch")
        return original_write(data)

    dev.write = write_with_failure
    worker.pump_writes()
    # f1 was written; its future is still pending a reply (correct).
    # f2 failed the write — must be failed.
    # f3 was in the batch, never written — must ALSO be failed.
    assert not f1.done() or f1.exception() is None  # written, still pending reply
    with pytest.raises(TransportClosedError):
        f2.result(timeout=0.1)
    with pytest.raises(TransportClosedError):
        f3.result(timeout=0.1)


def test_cancelled_unsent_requests_do_not_leak_or_replay():
    worker = HidIoWorker(open_fn=lambda: None)
    for _ in range(100):
        fut = worker.send_request([0x02, 0x03, 0])
        worker.cancel(fut)
    assert worker.pending_count() == 0
    assert not worker._write_q
    dev = FakeHID()
    worker._dev = dev
    worker.pump_writes()
    assert dev.writes == []


def test_offline_heartbeats_are_dropped():
    worker = HidIoWorker(open_fn=lambda: None)
    for _ in range(100):
        worker.send_untracked([0xA0, 0x01])
    assert not worker._write_q


def test_timeout_resets_stream_before_another_request_can_use_late_reply():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    old = worker.send_request([0x04, 0, 0, 1])
    worker.pump_writes()
    worker.cancel(old)
    new = worker.send_request([0x04, 0, 0, 2])
    dev.queue_reply([0x04, 0, 0, 1, 0xAA, 0xAA])
    worker.pump_once()
    with pytest.raises(TransportClosedError):
        new.result(timeout=0.1)
    assert dev._closed
    assert len(dev.writes) == 1


def test_wrong_echo_does_not_complete_key_read():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0, 0, 2])
    dev.queue_reply([0x04, 0, 0, 1, 0xAA, 0xAA])
    worker.pump_once()
    assert not fut.done()
    dev.queue_reply([0x04, 0, 0, 2, 0xBB, 0xBB])
    worker.pump_once()
    assert fut.result()[4:6] == [0xBB, 0xBB]


def test_cancel_during_write_error_does_not_escape_io_loop():
    dev = FakeHID()
    worker = HidIoWorker.with_handle(dev)
    fut = worker.send_request([0x04, 0, 0, 1])

    def cancelled_write(_frame):
        worker.cancel(fut)
        raise OSError("disconnected during write")

    dev.write = cancelled_write
    worker.pump_once()
    assert fut.cancelled()


def test_reopen_discards_buffered_replies_before_accepting_requests():
    dev = FakeHID()
    dev.queue_reply([0x04, 0, 0, 1, 0xAA, 0xAA])
    worker = HidIoWorker(open_fn=lambda: dev)
    assert worker.maybe_reopen()
    fut = worker.send_request([0x04, 0, 0, 1])
    worker.pump_once()
    assert not fut.done()
    dev.queue_reply([0x04, 0, 0, 1, 0xBB, 0xBB])
    worker.pump_once()
    assert fut.result()[4:6] == [0xBB, 0xBB]


def test_reopen_waits_for_barrier_even_after_a_quiet_read():
    class DelayedHID(FakeHID):
        quiet = True

        def read(self, n, timeout=0):
            if self.quiet:
                self.quiet = False
                return []
            return super().read(n, timeout)

    dev = DelayedHID()
    dev.queue_reply([0x04, 0, 0, 1, 0xAA, 0xAA])
    worker = HidIoWorker(open_fn=lambda: dev)
    assert worker.maybe_reopen()
    fut = worker.send_request([0x04, 0, 0, 1])
    worker.pump_once()
    assert not fut.done()
    dev.queue_reply([0x04, 0, 0, 1, 0xBB, 0xBB])
    worker.pump_once()
    assert fut.result()[4:6] == [0xBB, 0xBB]


def test_open_drain_read_error_closes_unusable_handle():
    dev = FakeHID()

    def bad_read(*args):
        raise OSError("unplugged while opening")

    dev.read = bad_read
    worker = HidIoWorker(open_fn=lambda: dev)
    assert not worker.maybe_reopen()
    assert dev._closed
