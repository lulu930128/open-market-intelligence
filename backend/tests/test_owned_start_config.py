"""Production entry validation without importing app.main or creating a server."""
import io
import json
import os
import sys
from uuid import uuid4

import pytest

from app import owned_uvicorn as owned


@pytest.fixture
def boot(monkeypatch):
    value = dict(scope="PRODUCTION", instance=str(uuid4()), nonce="a" * 64,
                 runner_pid=str(os.getppid()), runner_created="123", launcher_pid="99",
                 launcher_created="456", host="127.0.0.1", port="49197")
    for key, env in (("launcher_pid", "OMI_RUNTIME_LAUNCHER_PID"), ("launcher_created", "OMI_RUNTIME_LAUNCHER_CREATED"),
                     ("host", "OMI_BACKEND_HOST"), ("port", "OMI_BACKEND_PORT")):
        monkeypatch.setenv(env, value[key])
    monkeypatch.setattr(owned, "creation", lambda pid: "123" if pid == os.getppid() else "456")
    return value


def test_fixed_start_never_uses_uvicorn_default_port(boot):
    assert owned.production_start_config(boot) == dict(host="127.0.0.1", port=49197, workers=1, reload=False)


@pytest.mark.parametrize("key,value", [("scope", "DISPOSABLE"), ("launcher_pid", "1"),
    ("launcher_created", "0"), ("host", "0.0.0.0"), ("port", "8000"), ("port", "0"),
    ("port", "049197"), ("port", "65536"), ("port", True)])
def test_bad_start_refused_before_app_import(boot, monkeypatch, key, value):
    boot[key] = value
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(boot) + "\n"))
    assert "app.main" not in sys.modules
    with pytest.raises(ValueError):
        owned.main()
    assert "app.main" not in sys.modules


@pytest.mark.parametrize("key,value", [("nonce", "x" * 64), ("nonce", True),
    ("runner_pid", "1"), ("runner_created", "0"), ("instance", "bad")])
def test_boot_identity_refusal(boot, monkeypatch, key, value):
    boot[key] = value
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(boot) + "\n"))
    with pytest.raises(ValueError):
        owned.read_boot()


def test_malformed_frame_does_not_echo_secret(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("x" * 8193))
    with pytest.raises(ValueError, match="^BOOT_FRAME_INVALID$"):
        owned.read_boot()
