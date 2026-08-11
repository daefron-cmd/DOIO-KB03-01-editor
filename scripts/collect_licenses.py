#!/usr/bin/env python3
"""Collect distributable dependency license files for the macOS bundle."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
import shutil
import sys
from pathlib import Path


DISTRIBUTIONS = (
    "hidapi",
    "PyInstaller",
    "PySide6",
    "PySide6_Addons",
    "PySide6_Essentials",
    "shiboken6",
    "pyobjc-core",
    "pyobjc-framework-ApplicationServices",
    "pyobjc-framework-Cocoa",
    "pyobjc-framework-CoreText",
    "pyobjc-framework-Quartz",
)
LICENSE_WORDS = ("license", "copying", "notice")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value)


def collect(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=False)
    index: list[str] = []

    for requested_name in DISTRIBUTIONS:
        try:
            distribution = importlib.metadata.distribution(requested_name)
        except importlib.metadata.PackageNotFoundError:
            print(f"missing distribution: {requested_name}", file=sys.stderr)
            return 1

        name = distribution.metadata.get("Name", requested_name)
        destination = output / _safe_name(f"{name}-{distribution.version}")
        copied = 0
        for entry in distribution.files or ():
            if not any(part.endswith(".dist-info") for part in entry.parts):
                continue
            if not any(word in entry.name.lower() for word in LICENSE_WORDS):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file():
                continue
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / _safe_name("--".join(entry.parts[-2:]))
            shutil.copy2(source, target)
            copied += 1

        license_name = (
            distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or "See project metadata and upstream source"
        )
        index.append(f"{name} {distribution.version} | {license_name} | files: {copied}")

    (output / "INDEX.txt").write_text("\n".join(index) + "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    return collect(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
