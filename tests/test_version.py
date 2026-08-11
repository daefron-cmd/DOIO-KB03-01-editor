import tomllib
from pathlib import Path

from version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_application_version_matches_project_metadata():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["version"] == APP_VERSION
