from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import runtime_control as control
from app.routers.runtime_control import router
from r1d_test_support import offline_asyncio  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
# Deterministic test-only value; never provisioned to a runtime.
TOKEN = "a" * 64


def call(method="GET", path="/status", *, peer="127.0.0.1", proxy=False, runtime=None, **kwargs):
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(router, prefix="/api/system/runtime-control")

    async def run():
        headers = dict(kwargs.get("headers", {}))
        body = kwargs.get("content", "").encode()
        if "json" in kwargs:
            body = json.dumps(kwargs["json"]).encode()
            headers["content-type"] = "application/json"
        full_path = "/api/system/runtime-control" + path
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "http", "path": full_path,
                 "raw_path": full_path.encode(), "query_string": b"", "root_path": "",
                 "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
                 "client": (peer, 12345), "server": ("fixture", 80)}
        sent = []
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        async def send(message):
            sent.append(message)
        asgi = ProxyHeadersMiddleware(app, trusted_hosts="*") if proxy else app
        await asgi(scope, receive, send)
        start = next(item for item in sent if item["type"] == "http.response.start")
        response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        return SimpleNamespace(status_code=start["status"], text=response_body.decode(),
                               headers={k.decode(): v.decode() for k, v in start["headers"]},
                               json=lambda: json.loads(response_body))
    return asyncio.run(run())


@pytest.fixture
def authorized(monkeypatch):
    monkeypatch.setenv(control.TOKEN_ENV, hashlib.sha256(TOKEN.encode()).hexdigest())
    return {"X-OMI-Runtime-Control-Token": TOKEN}


def payload():
    return {"request_id": str(uuid4()), "expected_owner_id": str(uuid4()), "confirmation": "restart_backend"}


@pytest.mark.parametrize("peer,headers", [
    ("192.0.2.4", {}), ("127.0.0.1", {"forwarded": "for=127.0.0.1"}),
    ("127.0.0.1", {"x-forwarded-for": "127.0.0.1"}),
    ("127.0.0.1", {"origin": "http://localhost:3000"}),
])
def test_reads_reject_untrusted_transport(monkeypatch, peer, headers):
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: pytest.fail("pipe must not be called"))
    assert call(peer=peer, headers=headers).status_code == 403
    assert call(path="/operations/" + str(uuid4()), peer=peer, headers=headers).status_code == 403


@pytest.mark.parametrize("token", [None, "b" * 64, "true"])
def test_unauthorized_restart_has_no_dispatch(monkeypatch, authorized, token):
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: pytest.fail("no dispatch"))
    headers = {"X-OMI-Runtime-Control-Token": token} if token else {}
    result = call("POST", "/restart-backend", headers=headers, json=payload())
    assert result.status_code == 403
    assert TOKEN not in result.text


def test_default_disabled_and_ai_auth_cannot_grant_authority(monkeypatch):
    monkeypatch.delenv(control.TOKEN_ENV, raising=False)
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: pytest.fail("no dispatch"))
    response = call("POST", "/restart-backend", json={**payload(), "allow_write": True},
                    headers={"Authorization": "Bearer " + TOKEN, "X-OMI-Runtime-Control-Token": TOKEN})
    assert response.status_code == 403


@pytest.mark.parametrize("change", [{"confirmation": True}, {"confirmation": "yes"},
                                    {"request_id": "../../foreign"}, {"pid": 1234}, {"port": 8400},
                                    {"command": "restart"}, {"allow_write": True},
                                    {"backend_preflight": {}}, {"all_writers_drained": True},
                                    {"owner_approval": True}])
def test_fixed_request_rejects_extra_authority(monkeypatch, authorized, change):
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: pytest.fail("no dispatch"))
    response = call("POST", "/restart-backend", headers=authorized, json={**payload(), **change})
    assert response.status_code == 422
    assert response.json() == {"schema": control.SCHEMA, "error": "INVALID_REQUEST"}


def test_oversized_body_is_not_reflected(monkeypatch, authorized):
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: pytest.fail("no dispatch"))
    response = call("POST", "/restart-backend", headers=authorized, content="secret" * 1000)
    assert response.status_code == 422 and "secret" not in response.text


@pytest.mark.parametrize("state,code", [("accepted", 202), ("running", 202), ("succeeded", 200),
                                      ("blocked", 409), ("failed", 409), ("unknown", 503)])
def test_receipt_transport(monkeypatch, authorized, state, code):
    body = payload()
    calls = []

    def dispatch(action, **kwargs):
        calls.append((action, kwargs))
        return {**control.unknown_operation(body["request_id"]), "state": state}

    monkeypatch.setattr(control, "launcher_request", dispatch)
    response = call("POST", "/restart-backend", headers=authorized, json=body)
    assert response.status_code == code
    assert response.headers["cache-control"] == "no-store"
    assert calls == [("RestartBackend", {"request_id": body["request_id"],
                                        "expected_owner_id": body["expected_owner_id"], "token": TOKEN,
                                        "backend_preflight": None})]
    assert TOKEN not in response.text


def test_unavailable_reads_unknown_and_post_does_not_claim_acceptance(monkeypatch, authorized):
    def unavailable(*a, **kw):
        raise OSError("test failure containing private data")
    monkeypatch.setattr(control, "launcher_request", unavailable)
    status = call().json()
    assert status["owner_id"] is None
    assert status["backend"]["identity"] == "UNATTESTED"
    assert status["source"]["loaded_release_identity"] == "UNATTESTED"
    assert status["serving_backend"]["database_readiness"] == "not_checked"
    assert len(json.dumps(status)) < 4096
    operation = call(path="/operations/" + str(uuid4()))
    assert operation.json()["state"] == "unknown"
    response = call("POST", "/restart-backend", headers=authorized, json=payload())
    assert response.status_code == 503
    assert "private" not in response.text


def test_read_only_dispatch_and_build_mismatch(monkeypatch):
    calls = []
    def dispatch(action, **kw):
        calls.append(action)
        if action == "Status":
            return {**control.unknown_status(), "owner_id": str(uuid4())}
        return control.unknown_operation(kw["request_id"], "NOT_FOUND")
    monkeypatch.setattr(control, "launcher_request", dispatch)
    monkeypatch.setattr(control, "LOADED_CONTROL_BUNDLE_ID", "old")
    assert call().json()["source"]["disk_matches_import"] is False
    assert call(path="/operations/" + str(uuid4())).json()["reason"] == "NOT_FOUND"
    assert calls == ["Status", "ReadOperation"]


def test_controller_conflict_and_corrupt_reply(monkeypatch, authorized):
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: {"reason": "OWNER_MISMATCH"})
    assert call("POST", "/restart-backend", headers=authorized, json=payload()).status_code == 409
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: {"state": "unknown"})
    result = call("POST", "/restart-backend", headers=authorized, json=payload())
    assert result.status_code == 503 and result.json()["reason"] == "STORE_UNAVAILABLE"


def test_windows_controller_fixture(tmp_path):
    executable = shutil.which("powershell.exe")
    if not executable:
        pytest.skip("Windows PowerShell required")
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File",
                             str(ROOT / "scripts/tests/test-omi-runtime-control.ps1"),
                             "-FixtureRoot", str(tmp_path / "controller")],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CONTROLLER_FIXTURE_PASS" in result.stdout


def test_windows_user_credential_adoption(tmp_path):
    executable = shutil.which("powershell.exe")
    if not executable:
        pytest.skip("Windows PowerShell required")
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-File",
         str(ROOT / "scripts/tests/test-runtime-credential.ps1"),
         "-FixtureRoot", str(tmp_path / "credential")],
        capture_output=True, text=True, timeout=50, check=False,
    )
    # Do not reflect captured output on failure: it is explicitly leak-tested.
    assert result.returncode == 0, "CREDENTIAL_FIXTURE_FAILED"
    assert result.stdout.strip() == "RUNTIME_CREDENTIAL_FIXTURE_PASS"
    assert not result.stderr


@pytest.mark.parametrize("shape", ["missing", "uppercase", "newline", "short", "nonhex"])
def test_invalid_credential_keeps_read_api_available(monkeypatch, shape):
    digest = hashlib.sha256(TOKEN.encode("ascii")).hexdigest()
    invalid = {"uppercase": digest.upper(), "newline": digest + "\n",
               "short": digest[:-1], "nonhex": chr(0xff41) * 64}
    if shape == "missing":
        monkeypatch.delenv(control.TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(control.TOKEN_ENV, invalid[shape])
    calls = []

    def dispatch(action, **kwargs):
        calls.append(action)
        return control.unknown_status()

    monkeypatch.setattr(control, "launcher_request", dispatch)
    assert call().status_code == 200
    response = call("POST", "/restart-backend", json=payload(),
                    headers={"X-OMI-Runtime-Control-Token": TOKEN})
    assert response.status_code == 403
    assert calls == ["Status"]
    assert not control.token_authorized(TOKEN)
    assert TOKEN not in response.text and digest not in response.text


def test_windows_owned_identity_and_status_projection(monkeypatch):
    executable = shutil.which("powershell.exe")
    if not executable:
        pytest.skip("Windows PowerShell required")
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-File",
         str(ROOT / "scripts/tests/test-owned-backend-identity.ps1")],
        capture_output=True, text=True, timeout=40, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OWNED_IDENTITY_FIXTURE_PASS" in result.stdout
    snapshots = json.loads(next(line.removeprefix("OWNED_IDENTITY_STATUS=")
                                for line in result.stdout.splitlines()
                                if line.startswith("OWNED_IDENTITY_STATUS=")))
    sources = []
    for snapshot in snapshots:
        # Controller.Publish normally supplies these envelope fields; the
        # PowerShell sink deliberately avoids constructing a persistent store.
        snapshot = {"schema": control.SCHEMA, "owner_id": str(uuid4()), **snapshot}
        # Actual launcher publish payload through the in-process HTTP router;
        # no live controller/HTTP/DB/provider access or identity reimplementation.
        monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: dict(snapshot))
        response = call()
        assert response.status_code == 200
        data = response.json()
        assert data["backend"] == snapshot["backend"]
        assert data["restart"] == snapshot["restart"]
        assert data["restart"]["available"] is False
        assert data["serving_backend"]["database_readiness"] == "not_checked"
        sources.append(data["source"])
    assert sources[0] == sources[1]
    assert sources[0]["build_id_scope"] == "runtime_control_bundle_only"
    assert sources[0]["loaded_release_identity"] == "UNATTESTED"


def test_windows_syntax_and_production_refusal():
    source = (ROOT / "scripts/omi-runtime-control.ps1").read_text(encoding="utf-8-sig")
    restart = source.split("function Restart-Backend", 1)[1].split("function Invoke-OmiRuntimeControlTick", 1)[0]
    assert 'Invoke-OwnedBackendRestart -RequestId $RequestId -RemoteRequest' in restart
    launcher = (ROOT / "scripts/omi-launcher.ps1").read_text(encoding="utf-8-sig")
    restart = launcher.split('function Invoke-OwnedBackendRestart {', 1)[1].split('\nfunction ', 1)[0]
    commands = "\n".join(line for line in restart.splitlines() if not line.strip().startswith("#"))
    assert '$script:OwnsMutex' in commands and '$old.HasRetainedIdentity' in commands
    assert ".BeginAuthenticatedOwnedRestart($RequestId, $identity)" in commands
    assert ".Begin(" not in commands
    for forbidden in ("Stop-BackendService", "Stop-Process", "Start-Backend", "Restart-Services"):
        assert forbidden not in commands
    launcher = (ROOT / "scripts/omi-launcher.ps1").read_text(encoding="utf-8-sig")
    assert '$backendArguments = @("-m", "uvicorn", "app.main:app")' in launcher
    assert '"RestartServices" { $script:RestartEventName }' in launcher
    assert '$restartItem.add_Click({ try { Restart-Services } catch { Show-Message $_.Exception.Message } })' in launcher


def test_proxy_client_rewrite_cannot_bypass_loopback_check(monkeypatch, authorized):
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: pytest.fail("no dispatch"))
    # Uvicorn retains the forwarded header after changing scope.client. Even a
    # rewritten loopback client is rejected; other API trust behavior is unchanged.
    assert call(peer="192.0.2.4", proxy=True, headers={"x-forwarded-for": "127.0.0.1"}).status_code == 403
    assert call("POST", "/restart-backend", peer="192.0.2.4", proxy=True,
                headers={**authorized, "x-forwarded-for": "127.0.0.1"}, json=payload()).status_code == 403


def test_windows_native_pipe_owner_pin_and_roundtrip(tmp_path, monkeypatch):
    executable = shutil.which("powershell.exe")
    if not executable:
        pytest.skip("Windows PowerShell required")
    fixture_root = tmp_path / "pipe"
    process = subprocess.Popen([executable, "-NoProfile", "-NonInteractive", "-File",
                                str(ROOT / "scripts/tests/test-omi-runtime-control.ps1"),
                                "-FixtureRoot", str(fixture_root), "-PipeFixture",
                                "-BackendFixturePid", str(os.getpid())],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        owner = json.loads(process.stdout.readline())
        monkeypatch.setattr(control, "ROOT", fixture_root)
        monkeypatch.setenv("OMI_RUNTIME_LAUNCHER_PID", str(owner["pid"]))
        monkeypatch.setenv("OMI_RUNTIME_LAUNCHER_CREATED", owner["created"])

        def exchange(action, **kwargs):
            # Pipe listener accepts a single connection; only fixture reads retry
            # connect contention. A submitted restart never gets replayed here.
            time.sleep(0.05)
            return control.launcher_request(action, **kwargs)

        assert exchange("Status")["owner_id"] == owner["owner_id"]
        request_id = str(uuid4())
        accepted = exchange("RestartBackend", request_id=request_id,
                            expected_owner_id=owner["owner_id"], token=TOKEN,
                            backend_preflight={"schema": "omi.restart-preflight.v1", "runtime_started": True,
                                               "registered_drain_state": "NOT_REQUESTED",
                                               "all_writers_drained": False, "unknown_writer_count": 3})
        assert accepted["state"] == "accepted"
        assert exchange("ReadOperation", request_id=request_id)["state"] == "accepted"
        monkeypatch.setenv("OMI_RUNTIME_LAUNCHER_CREATED", str(int(owner["created"]) + 1))
        with pytest.raises(OSError, match="OWNER_NOT_ATTESTED"):
            exchange("Status")
    finally:
        # Gracefully finish this disposable fixture itself, not any OMI service.
        stdout, stderr = process.communicate("done\n", timeout=10)
    assert process.returncode == 0, stdout + stderr


def test_runtime_preflight_observes_without_closing_admission(monkeypatch):
    from app.runtime import RuntimeCoordinator, RuntimeDrainResult, UNATTESTED_WRITERS

    runtime = RuntimeCoordinator(schema_lock=object(), background_lock=object())
    monkeypatch.setattr(runtime, "stop", lambda **kw: pytest.fail("preflight must not drain"))
    initial = runtime.restart_preflight()
    assert initial["registered_drain_state"] == "NOT_REQUESTED"
    assert initial["unknown_writer_count"] == len(UNATTESTED_WRITERS)
    assert initial["all_writers_drained"] is False
    assert runtime._stop_task is None
    runtime._stop_task = SimpleNamespace(done=lambda: False)
    assert runtime.restart_preflight()["registered_drain_state"] == "IN_PROGRESS"
    runtime._stop_task = SimpleNamespace(done=lambda: True)
    assert runtime.restart_preflight()["registered_drain_state"] == "UNKNOWN"
    runtime._stop_task = None
    runtime.drain_result = RuntimeDrainResult(
        "REGISTERED_DRAINED", False, None, "not_owned", None, {}, False, None,
    )
    report = runtime.restart_preflight()
    assert report["registered_drain_state"] == "REGISTERED_DRAINED"
    assert report["all_writers_drained"] is False
    assert report["unknown_writer_count"] == len(UNATTESTED_WRITERS)
    monkeypatch.setattr(control, "launcher_request", lambda *a, **kw: control.unknown_status())
    assert call(runtime=runtime).json()["serving_backend"]["writer_preflight"] == report
    assert runtime._stop_task is None


@pytest.mark.parametrize("scenario", ["unknown_writers", "claimed_complete", "malformed", "stale",
                                    "unattested_client", "missing"])
def test_api_pipe_launcher_preflight_refusal(tmp_path, monkeypatch, authorized, scenario):
    """Real Windows pipe, isolated ASGI app/controller; no DB, port or OMI service."""
    executable = shutil.which("powershell.exe")
    if not executable:
        pytest.skip("Windows PowerShell required")
    fixture_root = tmp_path / "pipe-preflight"
    command = [
        executable, "-NoProfile", "-NonInteractive", "-File",
        str(ROOT / "scripts/tests/test-omi-runtime-control.ps1"),
        "-FixtureRoot", str(fixture_root), "-PipeFixture", "-BackendFixturePid", str(os.getpid()),
    ]
    if scenario == "unattested_client":
        command.append("-StaleClientIdentity")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        owner = json.loads(process.stdout.readline())
        monkeypatch.setattr(control, "ROOT", fixture_root)
        monkeypatch.setenv("OMI_RUNTIME_LAUNCHER_PID", str(owner["pid"]))
        monkeypatch.setenv("OMI_RUNTIME_LAUNCHER_CREATED", owner["created"])
        report = {"schema": "omi.restart-preflight.v1", "runtime_started": True,
                  "registered_drain_state": "REGISTERED_DRAINED", "all_writers_drained": False,
                  "unknown_writer_count": 3}
        if scenario == "claimed_complete":
            report.update(all_writers_drained=True, unknown_writer_count=0)
        if scenario == "malformed":
            report["all_writers_drained"] = "true"
        runtime = SimpleNamespace(restart_preflight=lambda: report)
        if scenario == "missing":
            runtime = None
        body = {**payload(), "expected_owner_id": owner["owner_id"]}
        response = call("POST", "/restart-backend", headers=authorized, json=body, runtime=runtime)
        refused_at_dispatch = scenario == "unattested_client"
        assert response.status_code == (409 if refused_at_dispatch else 202)
        accepted = response.json()
        assert accepted["state"] == ("blocked" if refused_at_dispatch else "accepted")
        if refused_at_dispatch:
            assert accepted["reason"] == "BACKEND_PREFLIGHT_NOT_ATTESTED"
            assert accepted["backend_preflight"] is None
        elif scenario in {"malformed", "missing"}:
            assert accepted["backend_preflight"] is None
        else:
            assert accepted["backend_preflight"] == report
            assert accepted["backend_preflight_identity"]["pid"] == os.getpid()
        process.stdin.write("tick-stale\n" if scenario == "stale" else "tick\n")
        process.stdin.flush()
        assert process.stdout.readline().strip() == "TICK_COMPLETE"
        time.sleep(0.05)
        receipt = call(path="/operations/" + body["request_id"]).json()
        assert receipt["state"] == "blocked"
        expected_reason = "BACKEND_PREFLIGHT_NOT_ATTESTED" if refused_at_dispatch else "OWNED_BOOTSTRAP_REQUIRED"
        assert receipt["reason"] == expected_reason
        assert receipt["after"] is None
        assert expected_reason in receipt["blockers"]
        time.sleep(0.05)
        replay = call("POST", "/restart-backend", headers=authorized, json=body, runtime=runtime)
        assert replay.status_code == 409 and replay.json() == receipt
        assert TOKEN not in replay.text
    finally:
        stdout, stderr = process.communicate("done\n", timeout=10)
    assert process.returncode == 0, stdout + stderr
