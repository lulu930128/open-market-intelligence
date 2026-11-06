"""Offline backend regression entry: private config/data and network denied."""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SELF_PIPES = []


def isolated(event, args):
    if event in {"socket.connect", "socket.bind"}:
        # Windows asyncio implements its wakeup socketpair on an ephemeral
        # loopback listener. Permit only that self-pipe, never an existing API.
        sock, address = args
        if event == "socket.bind" and address[0] in {"127.0.0.1", "::1"} and address[1] == 0:
            SELF_PIPES.append(sock)
        elif event != "socket.connect" or not any(s.fileno() >= 0 and s.getsockname() == address for s in SELF_PIPES):
            raise AssertionError("external network forbidden in isolated acceptance")
    if event == "import" and str(args[0]).split(".")[0] == "kgisuperpy":
        raise AssertionError("native SDK import forbidden")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(args[0]).resolve()
        if path in {ROOT / ".env", ROOT / ".env.runtime"} or path.is_relative_to(ROOT / "data"):
            raise AssertionError("private configuration/data access forbidden")


def main():
    sys.addaudithook(isolated)
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
    from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource
    with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}), \
         patch.object(EnvSettingsSource, "_load_env_vars", return_value={"database_url": "sqlite:///:memory:"}):
        from app.market import exchange_calendar_cache
        import pytest
        # Historical fixtures use the checked-in calendar fallback, never the
        # workstation's current cached calendar snapshot.
        with patch.object(exchange_calendar_cache, "read_exchange_calendar_cache", return_value={"markets": {}}):
            return pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
