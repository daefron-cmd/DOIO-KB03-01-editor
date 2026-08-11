from pathlib import Path

from version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_launcher_hosts_python_in_signed_app_process():
    source = (ROOT / "scripts" / "macos_launcher.c").read_text()

    assert "Py_InitializeFromConfig" in source
    assert 'execlp("uv"' not in source
    assert 'execlp("python"' not in source


def test_local_bundle_uses_public_bundle_id_and_shared_version():
    source = (ROOT / "scripts" / "build_app_bundle.sh").read_text()

    assert 'BUNDLE_ID="io.github.daefron-cmd.doio-kb03-01"' in source
    assert "from version import APP_VERSION" in source
    assert APP_VERSION == "0.1.0"
