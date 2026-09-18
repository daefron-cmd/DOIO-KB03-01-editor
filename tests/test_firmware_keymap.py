"""Host-side C harness, not a substitute for a full QMK build/flash test."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_firmware_boot_preserves_remaps_and_reserves_only_outer_ring(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler unavailable")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "keymap_test"
    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DENCODER_MAP_ENABLE",
            '-DQMK_KEYBOARD_H="qmk_stub.h"',
            "-I",
            str(root / "tests" / "firmware"),
            "-I",
            str(root / "firmware" / "keymaps" / "vegar"),
            str(root / "tests" / "firmware" / "keymap_harness.c"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
