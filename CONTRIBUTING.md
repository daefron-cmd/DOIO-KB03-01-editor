# Contributing

This is a small, hardware-specific project. Focused fixes and confirmed support
for additional DOIO revisions are welcome.

## Development setup

```bash
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen pytest
bash -n scripts/build_app_bundle.sh firmware/build.sh
```

The automated suite does not require a connected macropad. Changes to HID
transport, macOS permissions, live highlighting, or firmware behavior should
also be exercised on hardware when possible; say exactly what was and was not
tested in the pull request.

To exercise the self-contained release path on macOS:

```bash
uv sync --frozen --group package
./scripts/build_release.sh
```

The application version lives in `version.py` and must match
`project.version` in `pyproject.toml`. A tag-triggered release must use the
corresponding `vMAJOR.MINOR.PATCH` name.

## Useful hardware report details

Include the macOS version, Python version, USB VID/PID, the firmware or dump
filename, and the exact command or UI action that triggered the problem. Close
the GUI before running a probe script because the VIA raw-HID interface is
single-owner.

Do not attach full system reports or logs without checking them for usernames,
home-directory paths, serial numbers, and other unrelated personal data.

## Scope

Keep changes narrowly tied to the KB03-01. Document another hardware revision
before adding compatibility logic, and do not silently broaden firmware flash
targets: an incorrect target can make the device temporarily unusable.
