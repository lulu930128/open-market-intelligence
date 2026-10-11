"""Process-local guard for G3 evidence runs; never changes application settings."""

import sys
import re
from urllib.parse import parse_qs
from pathlib import Path
from unittest.mock import patch

from pydantic_settings.sources import DotEnvSettingsSource


def install():
    # Suppress implicit Settings dotenv reads before importing any app module.
    patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}).start()

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError(f"G3 offline guard denied {event}")
        if event == "sqlite3.connect":
            value = str(args[0])
            if value == ":memory:":
                return
            name, _, query = value.partition("?")
            if re.fullmatch(r"file:omi_[a-z_]+_[0-9a-f]{32}", name) and parse_qs(query).get("mode") == ["memory"]:
                return
            path = Path(value).resolve()
            # Tests may use their established disposable pytest/temp fixture paths.
            if "data" in path.parts or path.name.startswith("open_market_intelligence"):
                raise RuntimeError("G3 offline guard denied persistent database")
            if path.parent == Path(__file__).resolve().parent and re.fullmatch(
                r"\.us_truth_snapshot_[0-9a-f]{32}\.db", path.name
            ):
                return
            if not any(part.startswith(("pytest", "tmp", ".tmp", "Temp")) for part in path.parts):
                raise RuntimeError("G3 offline guard requires a disposable database path")

    sys.addaudithook(audit)


if __name__ == "__main__":
    install()
    import pytest

    raise SystemExit(pytest.main(sys.argv[1:]))
