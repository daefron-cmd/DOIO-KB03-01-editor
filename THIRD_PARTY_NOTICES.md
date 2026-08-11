# Third-party notices

The macOS application is built from the exact dependency versions recorded in
`uv.lock`. Its distributable bundle includes components from these projects:

| Component | License | Project |
|---|---|---|
| CPython | Python Software Foundation License | <https://www.python.org/> |
| PyInstaller bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception | <https://pyinstaller.org/> |
| Qt for Python (`PySide6`, `shiboken6`, Qt) | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | <https://doc.qt.io/qtforpython-6/> |
| cython-hidapi / HIDAPI | BSD-style and GPL licensing; see the included package license files | <https://github.com/trezor/cython-hidapi> |
| PyObjC | MIT | <https://github.com/ronaldoussoren/pyobjc> |

The release builder copies license, copying, and notice files exposed by these
installed distributions into `Contents/Resources/third-party-licenses/`.
Inclusion in this notice does not imply endorsement by any upstream project.
