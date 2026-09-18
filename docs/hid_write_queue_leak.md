# HID write-queue leak — findings + fix plan

**Date:** 2026-07-06
**Status (2026-09-18):** fixed in source; hardware reconnect verification pending.
**Symptom:** app footprint grows to 1.5 GB after ~12 days of uptime.

The sections below preserve the original investigation. Cancellation now removes
unsent frames from the write queue, offline heartbeats are dropped, and the
control worker stops matrix polling while disconnected. A sent request timing
out triggers an IO-thread close/reopen and a VIA protocol-version exchange to
consume older replies before accepting new requests. Regression tests in
`tests/test_hid_io.py` cover retention, replay, cancellation races, and delayed
responses; `tests/test_reconnect.py` covers offline polling and reconnection.

## Root cause

When the DOIO is **not attached**, every VIA request leaks one write-queue
entry, roughly once per second, forever:

1. `ControlWorker._poll_matrix` (30 ms QTimer, `worker.py`) keeps firing with
   no device. Each call goes through `_request` → `HidIoWorker.send_request`.
2. `send_request` (`hid_io.py`) appends the `(frame, future)` pair to **three**
   collections: `_inflight`, `_futures[cmd_id]`, and `_write_q`.
3. `pump_writes` early-returns when `_dev is None` — the queue is never
   drained and the futures are never failed.
4. After the 1 s reply timeout, `_request` calls `HidIoWorker.cancel(fut)`,
   which evicts the future from `_inflight` and `_futures` — **but not from
   `_write_q`**. The entry (frame bytes + cancelled `Future` + its
   `Condition`/waiters deque) is stranded permanently.

Net effect: one leaked bundle (~2 KB across malloc + pymalloc) per ~1 s
timeout cycle. Nothing to do with the scroll engine — `QtScrollEngine.tick()`
early-returns when idle and pyobjc releases posted CGEvents correctly.

## Evidence (live process, PID 985, 12 days uptime)

- `vmmap --summary`: physical footprint 1.5 G; writable regions 1.6 G with
  1.4 G written, 90 % swapped. IOSurface/graphics only ~73 M — it's heap.
- `heap`: 1.52 M live malloc nodes, dominated by two equal cohorts —
  **717,783 × 640 B** and **708,375 × 128 B** (one pair per leaked entry;
  the 640 B block is the `Condition._waiters` deque). Plus ~850 MB of
  pymalloc arenas (`VM_ALLOCATE`) holding the Python-side objects.
- ~710 k entries / 12.5 days ≈ one per ~1.5 s → matches the 1 s timeout
  loop (device absent most of the uptime; it is not attached right now).
- `system_profiler SPUSBDataType`: no `0xD010/0x0301` device present.

## Second latent bug (same code path)

On reconnect after a long absence, `pump_writes` drains the **entire stale
queue** to the device — potentially hundreds of thousands of ancient
matrix-poll frames flooding the firmware in one batch.

## What needs to be done

Fix in `hid_io.py`, TDD (failing test first — see
`tests/test_hid_io_*.py` for the existing style):

1. **Test:** with `_dev = None`, `send_request` + timeout + `cancel(fut)`
   leaves `_write_q` empty (or the entry is failed/dropped). Also assert
   `send_untracked` frames don't accumulate unboundedly with no device.
2. **Fix (pick one, first preferred):**
   - `cancel(fut)` also purges the matching `(frame, fut)` entry from
     `_write_q` — fixes leak *and* stale-flood in one move; or
   - `pump_writes` with `_dev is None` fails tracked futures with
     `TransportClosedError` and drops untracked frames instead of
     returning early.
3. **Test:** reconnect after N timed-out requests does **not** write stale
   frames to the device (guards the flood bug regardless of which fix).
4. Run full suite (120 tests as of tonight, all green pre-fix).

Keep the fix as its own commit — the working tree still has uncommitted
in-progress scroll/firmware work (`worker.py`, `main.py`, `scroll.py`,
`ui.py`, `tests/test_scroll_*`, `firmware/keymaps/vegar/*`).

## Housekeeping already done / still pending

- Repo renamed `usb-probe` → `doio-kb03-01`; all references updated
  (pyproject name, README, docs, bundle id); app bundle rebuilt and
  reinstalled with the new project root baked in.
- **Pending:** the running app (PID 985) still executes from the old
  `.venv` path and holds the leaked 1.5 GB — restart it. First launch of
  the rebuilt bundle needs **Input Monitoring + Accessibility re-granted**
  (bundle id changed `local.usb-probe.kb03` → `local.doio-kb03-01`).
