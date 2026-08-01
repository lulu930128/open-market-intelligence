from pathlib import Path


VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"
UNKNOWN_VERSION = "0.0.0+unknown"


def read_project_version() -> str:
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return UNKNOWN_VERSION

    return version or UNKNOWN_VERSION


PROJECT_VERSION = read_project_version()
