# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path


ROOT = Path(os.environ["DOIO_PROJECT_ROOT"])
VERSION = os.environ["DOIO_VERSION"]
ICON = os.environ["DOIO_ICON"]
LICENSES = os.environ["DOIO_LICENSES"]
TARGET_ARCH = os.environ["DOIO_TARGET_ARCH"]
CODESIGN_IDENTITY = os.environ.get("MACOS_CODESIGN_IDENTITY") or None

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "pictures" / "gui_background.png"), "pictures"),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (LICENSES, "third-party-licenses"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DOIOKB03",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DOIOKB03",
)
app = BUNDLE(
    coll,
    name="DOIO KB03-01.app",
    icon=ICON,
    bundle_identifier="io.github.daefron-cmd.doio-kb03-01",
    version=VERSION,
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=None,
    info_plist={
        "CFBundleDisplayName": "DOIO KB03-01",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSInputMonitoringUsageDescription": (
            "DOIO KB03-01 reads keyboard HID reports to highlight macropad key presses."
        ),
    },
)
