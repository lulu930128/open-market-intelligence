"""Run with python -B -m execution_broker_preflight.tests.run_offline.

Audit hooks are process-local and irreversible; this is a dedicated test process.
"""

import ast
import dataclasses
import datetime
import decimal
import enum
import os
from pathlib import Path
import sys
import unittest


DENIED_MODULES = ("kgisuperpy", "paos", "personal_asset_os", "kgi_broker_bridge",
                  "execution", "execution_simulation", "app", "backend", "agents",
                  "socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp",
                  "sqlite3", "sqlalchemy", "subprocess", "ctypes")


def offline_guard(name, args):
    if name == "import" and any(args[0] == p or args[0].startswith(p + ".") for p in DENIED_MODULES):
        raise RuntimeError("Offline import blocked: " + args[0])
    if name.startswith(("socket.", "sqlite3.", "subprocess.", "ctypes.")) or name in ("os.system", "os.fork", "os.posix_spawn"):
        raise RuntimeError("Offline operation blocked: " + name)
    if name == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            raise RuntimeError("Offline filesystem write blocked")


def main():
    sys.dont_write_bytecode = True
    sys.addaudithook(offline_guard)
    root = Path(__file__).resolve().parents[2]
    suite = unittest.defaultTestLoader.discover(str(root / "execution_broker_preflight/tests"), top_level_dir=str(root))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
