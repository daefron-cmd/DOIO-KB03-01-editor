"""Poke at a USB HID device and report what's inside.

Defaults to the DOIO KB03-01 (VID 0xD010 / PID 0x0301) but takes
--vid / --pid overrides. Uses hidapi for the HID view and libusb
(via pyusb) for the raw descriptor tree.
"""

import argparse

import hid
import libusb_package
import usb.core
import usb.util

# usage_page -> human label, with the QMK/VIA fingerprints called out
USAGE_PAGES = {
    0x01: "Generic Desktop",
    0x0C: "Consumer",
    0xFF60: "VIA raw HID  <-- QMK+VIA fingerprint",
    0xFF31: "QMK console  <-- QMK fingerprint",
}
GENERIC_USAGES = {0x02: "Mouse", 0x06: "Keyboard", 0x80: "System Control"}


def hid_view(vid: int, pid: int) -> set[int]:
    """Enumerate every HID interface the OS exposes for this device."""
    print("=" * 70)
    print("HIDAPI VIEW (what macOS exposes as HID interfaces)")
    print("=" * 70)
    seen_pages: set[int] = set()
    entries = hid.enumerate(vid, pid)
    if not entries:
        print("  (no HID interfaces found — is it plugged in / allowed?)")
        return seen_pages
    for d in entries:
        up, u = d["usage_page"], d["usage"]
        seen_pages.add(up)
        label = USAGE_PAGES.get(up, f"0x{up:04X}")
        if up == 0x01:
            label = f"Generic Desktop / {GENERIC_USAGES.get(u, f'usage 0x{u:02X}')}"
        print(f"\n  interface {d['interface_number']}:")
        print(f"    product      : {d['product_string']}")
        print(f"    manufacturer : {d['manufacturer_string']}")
        print(f"    usage_page   : 0x{up:04X}  ({label})")
        print(f"    usage        : 0x{u:02X}")
        print(f"    release bcd  : 0x{d['release_number']:04X}")
        print(f"    path         : {d['path'].decode(errors='replace')}")
    return seen_pages


def usb_view(vid: int, pid: int) -> None:
    """Read the raw USB descriptor tree via libusb."""
    print("\n" + "=" * 70)
    print("LIBUSB VIEW (raw USB descriptor tree)")
    print("=" * 70)
    backend = libusb_package.get_libusb1_backend()
    dev = usb.core.find(idVendor=vid, idProduct=pid, backend=backend)
    if dev is None:
        print("  (libusb could not find the device)")
        return

    print(f"\n  bcdUSB           : 0x{dev.bcdUSB:04X}")
    print(f"  idVendor         : 0x{dev.idVendor:04X}")
    print(f"  idProduct        : 0x{dev.idProduct:04X}")
    print(f"  bcdDevice        : 0x{dev.bcdDevice:04X}  (firmware/device version)")
    print(f"  bDeviceClass     : {dev.bDeviceClass}  (0 = per-interface)")
    print(f"  bNumConfigs      : {dev.bNumConfigurations}")

    # String descriptors need a control transfer; macOS may refuse on HID.
    for field, label in (("iManufacturer", "manufacturer"),
                          ("iProduct", "product"),
                          ("iSerialNumber", "serial")):
        idx = getattr(dev, field)
        try:
            val = usb.util.get_string(dev, idx) if idx else "(none)"
        except Exception as e:  # noqa: BLE001 - macOS HID access is best-effort
            val = f"<unreadable: {type(e).__name__}>"
        print(f"  {label:16s} : {val}")

    for cfg in dev:
        print(f"\n  configuration {cfg.bConfigurationValue}: "
              f"{cfg.bNumInterfaces} interfaces, "
              f"{cfg.bMaxPower * 2} mA max")
        for intf in cfg:
            print(f"    interface {intf.bInterfaceNumber} "
                  f"(alt {intf.bAlternateSetting}): "
                  f"class={intf.bInterfaceClass} "
                  f"subclass={intf.bInterfaceSubClass} "
                  f"protocol={intf.bInterfaceProtocol}")
            for ep in intf:
                direction = "IN " if usb.util.endpoint_direction(
                    ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
                print(f"        endpoint 0x{ep.bEndpointAddress:02X} {direction} "
                      f"max={ep.wMaxPacketSize}B interval={ep.bInterval}")


def verdict(seen_pages: set[int]) -> None:
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    via = 0xFF60 in seen_pages
    console = 0xFF31 in seen_pages
    if via or console:
        print("  Looks like QMK firmware:")
        if via:
            print("   - VIA raw-HID interface (0xFF60) present -> VIA-enabled")
        if console:
            print("   - QMK console interface (0xFF31) present")
        print("   Source likely lives in qmk/qmk_firmware under keyboards/doio/.")
        print("   VIA-enabled means you can read/remap keys live over raw HID.")
    else:
        print("  No QMK/VIA raw-HID fingerprints found.")
        print("  Could be locked-down stock firmware or a non-QMK chip.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vid", type=lambda x: int(x, 0), default=0xD010)
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=0x0301)
    args = ap.parse_args()
    pages = hid_view(args.vid, args.pid)
    usb_view(args.vid, args.pid)
    verdict(pages)


if __name__ == "__main__":
    main()
