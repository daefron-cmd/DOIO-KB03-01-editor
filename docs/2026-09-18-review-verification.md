# Repository review fixes

The headless-server checks use simulated HID devices and Qt's offscreen backend.
They do not establish how scrolling feels on the MacBook or whether its macOS
permissions are correct. Subsequent SSH checks and the app replacement are
recorded below. No firmware was flashed.

## Changes and regression evidence

| Issue | Before | Regression check after correction |
|---|---|---|
| Cancelled HID queue entries | 100 cancellations retained and replayed 100 frames | Queue is empty and reconnect sends no cancelled commands; cancellation racing a write error does not escape |
| Late VIA replies | A column-1 reply completed a column-2 read | Sent timeouts reset the session; a protocol-version barrier consumes old replies, including replies arriving after a quiet read; address echoes are checked |
| Lighting persistence | Save preceded the pending brightness write; an earlier save acknowledged later edits | Pending writes precede save; acknowledgements mark only the requested state saved; revert discards pending edits |
| Reconnection | No-device startup looked like permission denial; listener read errors escaped | Snapshot reload and UI status recover on open; polling pauses offline; input handles close and reopen after errors |
| Layer inference | Releasing nested MO(2) returned to layer 0 while MO(1) was held | The radio-button display preserves the inferred layer mask and returns to layer 1 |
| Idle scroll engine | The 8 ms timer ran continuously | Timer runs only during active motion/momentum; reverse braking and completed momentum stop it; heartbeat readiness continues while idle |
| Firmware remap persistence | Boot erased the whole dynamic keymap | Native C harness executes the actual boot hook, preserves user keys/inner encoder, reserves outer bindings, and avoids redundant writes on the second boot |

The UI tests also exposed a pending highlight callback running after its widget
was deleted. The callback now has a Qt object context so deletion cancels it.

## MacBook installation verification

SSH through the configured tailnet worked. The MacBook's USB registry identified
the expected DOIO KB03-01 (`D010:0301`), and no competing DOIO process was running
before installation. Its old app was the development launcher, with both a
missing externally linked `libpython3.13.dylib` and a missing source checkout.
The user's DYLD crash report confirmed the missing library abort at launch.

Built the current source with `scripts/build_release.sh` and transferred the
self-contained archive. SHA-256:
`d19319b8b6b5892fc9d308adf02d3ace9bde05ca9f01a8c1909833c94a606e9a`.
The build's version, dependency/artwork self-test, signature, property list, and
ZIP integrity checks passed. The archive checksum, deep code-signature check,
`--version`, and `--self-test` also passed on the MacBook without external Python.

Installed the replacement at `/Applications/DOIO KB03-01.app` on the MacBook.
The old launcher is preserved there at
`~/Library/Application Support/DOIO KB03-01/Backups/20260918-development-launcher.app.backup`.
The replacement launched and remained running after 31 seconds, with no new
DOIO crash report. Its bundle ID is `io.github.daefron-cmd.doio-kb03-01`, replacing
`local.doio-kb03-01`; macOS may require new Input Monitoring/Accessibility grants.
No standalone raw-HID probe was run alongside the GUI. Interactive keymap,
lighting, reconnection, and scroll-feel checks below remain outstanding.

## Working VIA status follow-up

The user subsequently confirmed MX-Master emulator scrolling works. The GUI
showed available VIA matrix highlighting, while MacBook logs explicitly reported
`TCC deny IOHIDDeviceOpen` for direct input access. Enabling Input Monitoring did
not remove the warning according to the user. This does not establish the cause
of the persistent permission denial, nor does it make scrolling unavailable.

Changed the working VIA path to a neutral `Key highlights via VIA` status. Missing
devices and unavailable highlighting still produce warnings; the latter now
references the installed app instead of the launching terminal. Three regression
cases failed before the correction; all 162 tests, Ruff, and whitespace checks
passed afterward. The rebuilt release passed its bundled self-test, signature,
property-list, version, and archive checks. Its SHA-256 is
`bf5bbde1d232043bd3a27c39fa43687ea281e3a72c784e2500793acfc7d5fc75`.

On the MacBook, checksum, deep signature verification, and bundled self-test
passed. The request to gracefully quit the current app returned AppleScript
error -128 (`User canceled`), so installation initially paused. After the user
confirmed the app had closed, a process check confirmed no running instance.
Installed the staged update at `/Applications/DOIO KB03-01.app`, preserving the
previous release at
`~/Library/Application Support/DOIO KB03-01/Backups/20260918-before-via-status.app.backup`.
The installed app passed deep signature verification and its bundled self-test;
it was reopened and remained running after 15 seconds.

The user then reported ordinary scrolling instead of emulation, with `AX: no /
Host: waiting`. macOS logs explicitly reported that the current executable did
not match the stored Accessibility code requirement. Comparing the installed
and backed-up releases confirmed different ad-hoc signing hashes. After the
user removed and re-added the installed app in Accessibility and reopened it,
they confirmed emulation was restored. The old development-launcher backup also
appeared in Accessibility; it does not need permission.

Future deployment verification must include Accessibility readiness and a user
scroll test after replacement, not just signature/self-test/process-liveness
checks. Ad-hoc signed rebuilds can require a fresh grant even at the same path
and bundle ID. Stable signing across releases is not implemented by this change.

## MacBook verification still needed

1. Run the updated app with the DOIO disconnected. Compare trackpad scrolling in
   Finder and Ghostty with the app open and closed. The idle timer correction is
   implemented; its effect on the reported stutter has not been confirmed.
2. Plug in the DOIO after starting the app. Confirm the keymap loads, the missing
   device banner clears, and keyboard/consumer highlights work with the relevant
   permission granted. Unplug/replug and repeat.
3. Change lighting and immediately save. Replug and check the persisted value.
   Change another value while a save is pending and confirm it remains marked as
   unsaved. Revert a just-moved slider and check the physical lighting.
4. Check slow detents, acceleration, momentum, and reverse braking. Host takeover
   should remain ready while idle. Quit the app and confirm standalone scrolling.
5. Build the current firmware source with QMK before flashing. The tracked
   `20260810` images still erase remaps and do not contain this fix. After flashing,
   remap a key and the inner encoder, power-cycle, and check that both survive;
   verify the outer ring scrolls on all four layers.

SSH can support command-line HID checks on the MacBook if Remote Login and
authentication are configured. Close the GUI before raw-HID probes because that
interface is single-owner. An SSH-launched process may have different macOS
permissions from the signed app, so those checks cannot replace GUI permission
and trackpad-feel testing in the logged-in MacBook session.
