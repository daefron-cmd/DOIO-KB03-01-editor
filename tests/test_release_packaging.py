from pathlib import Path

import main
from scripts.collect_licenses import collect


ROOT = Path(__file__).resolve().parents[1]


def test_release_self_test_checks_dependencies_and_artwork(capsys):
    assert main._self_test() == 0
    assert "0.1.0 self-test passed" in capsys.readouterr().out


def test_release_spec_embeds_runtime_assets_and_licenses():
    source = (ROOT / "scripts" / "doio_kb03.spec").read_text()

    assert 'ROOT / "pictures" / "gui_background.png"' in source
    assert 'ROOT / "LICENSE"' in source
    assert 'ROOT / "THIRD_PARTY_NOTICES.md"' in source
    assert 'bundle_identifier="io.github.daefron-cmd.doio-kb03-01"' in source
    assert "project-root.txt" not in source


def test_dependency_license_collector_writes_index_and_available_texts(tmp_path):
    output = tmp_path / "licenses"

    assert collect(output) == 0
    index = (output / "INDEX.txt").read_text()
    assert "PySide6 " in index
    assert "PyObjC" in index or "pyobjc" in index
    assert any(path.name.startswith("licenses--LICENSE") for path in output.rglob("*"))
