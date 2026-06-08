import threading

import pytest

from hid_io import (
    HidIoWorker, IdUnhandledError, TransportClosedError,
    RAW_EPSIZE, build_raw_hid_frame,
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
    assert frame[0] == 0x00     # report id
    assert frame[1] == 0xA0     # cmd id
    assert frame[2] == 0x01     # version
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
    assert not fut.done()       # waits for handle
    worker.stop()                # close: fails all pending
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
