import re
from pathlib import Path

from app.version import PROJECT_VERSION


def test_project_version_matches_release_file() -> None:
    version_file = Path(__file__).resolve().parents[2] / "VERSION"

    assert PROJECT_VERSION == version_file.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", PROJECT_VERSION)
