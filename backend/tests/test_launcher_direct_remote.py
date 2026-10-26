"""Real isolated C# pipe server; this Python adapter is a different OS process.

No production pipe, credential, Launcher entrypoint, DB or service is accessed.
"""
import ctypes
from ctypes import wintypes
import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from test_runtime_launcher_recovery import _powershell
from test_owned_restart_preflight import (
    restart_runtime,
    test_production_transport_drains_real_runtime_through_uvicorn_lifespan as _exercise_owned_transport,
)


CONFIRM = {"RestartBackend": "restart_backend", "StartBackend": "start_backend",
           "RecoverFailedStart": "recover_failed_start", "SchemaUpgrade": "upgrade_schema"}


class Adapter:
    def __init__(self, process, info):
        self.process, self.info = process, info

    def owner(self, action, **values):
        self.process.stdin.write(json.dumps(dict(action=action, **values)) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def send(self, action, request_id=None, **changes):
        request = dict(action=action, request_id=request_id or str(uuid4()),
                       expected_owner_id=self.info["owner"], token="d" * 64)
        if action in CONFIRM:
            request["confirmation"] = CONFIRM[action]
        request.update(changes)
        if request.get("confirmation", "") is None:
            request.pop("confirmation")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        kernel.SetNamedPipeHandleState.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]
        for method in (kernel.ReadFile, kernel.WriteFile):
            method.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        # Server creates a fresh instance per frame. Retry only opening this
        # disposable transport, never retry a mutation whose frame was sent.
        until = time.monotonic() + 2
        while True:
            handle = kernel.CreateFileW("\\\\.\\pipe\\" + self.info["pipe"], 0xC0000000, 0, None, 3, 0, None)
            if handle != ctypes.c_void_p(-1).value:
                break
            assert time.monotonic() < until, "FIXTURE_PIPE_UNAVAILABLE"
            time.sleep(.01)
        try:
            actual = wintypes.ULONG()
            assert kernel.GetNamedPipeServerProcessId(handle, ctypes.byref(actual))
            assert actual.value == self.process.pid and self.process.poll() is None
            mode = wintypes.DWORD(1)
            assert kernel.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None)
            payload = json.dumps(request).encode() + b"\n"
            count = wintypes.DWORD()
            assert kernel.WriteFile(handle, payload, len(payload), ctypes.byref(count), None)
            assert count.value == len(payload)
            output = b""
            while time.monotonic() < until:
                buffer = ctypes.create_string_buffer(16384)
                if kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                    output += buffer.raw[:count.value]
                    if b"\n" in output:
                        return json.loads(output)
                time.sleep(.005)
            pytest.fail("FIXTURE_REPLY_TIMEOUT")
        finally:
            kernel.CloseHandle(handle)


@pytest.fixture
def adapter(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/tests/test-omi-direct-control.ps1"
    process = subprocess.Popen([_powershell(), "-NoProfile", "-NonInteractive", "-File", str(script),
                                "-FixtureRoot", str(tmp_path / "store")], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        info = json.loads(process.stdout.readline())
        assert info["pid"] != os.getpid()
        yield Adapter(process, info)
    finally:
        stdout, stderr = process.communicate("done\n", timeout=10)
        assert process.returncode == 0, stdout + stderr


@pytest.mark.parametrize("action", list(CONFIRM))
def test_independent_adapter_accepts_consumes_once_without_local_approval(adapter, action):
    if action == "RestartBackend":
        adapter.owner("running")
    accepted = adapter.send(action)
    assert accepted["state"] == "accepted"
    assert accepted["requester"]["pid"] == os.getpid()
    assert accepted["actor"] == "authenticated_pipe_client"
    assert accepted["local_approval"] is None
    request_id = accepted["request_id"]
    assert adapter.send(action, request_id) == accepted
    consumed = adapter.owner("consume")
    assert consumed["id"] == request_id and consumed["begun"]
    assert 0 < consumed["deadline"] <= 180000
    running = adapter.send("ReadOperation", request_id)
    assert running["state"] == "running" and running["intent_consumed_at"]
    assert adapter.owner("consume")["id"] is None
    adapter.owner("finish", id=request_id, kind=action)
    receipt = adapter.send("ReadOperation", request_id)
    assert receipt["state"] == "unknown"  # No invented stop/migration/start evidence.
    assert adapter.send(action, request_id) == receipt
    assert adapter.send("Status")["owner_id"] == adapter.info["owner"]
    assert adapter.send(action)["state"] == "accepted"


@pytest.mark.parametrize("changes", [
    {"token": "e" * 64}, {"expected_owner_id": str(uuid4())},
    {"confirmation": "restart_backend"}, {"confirmation": True}, {"confirmation": None},
    {"actor": "launcher_local_operator"}, {"approved": True},
    {"database_path": "C:\\arbitrary.db"}, {"command": "powershell.exe"},
    {"action": "ApplyRelease"}, {"action": "Shell"}, {"request_id": "not-a-uuid"},
])
def test_invalid_authority_never_queues_or_poison_next_uuid(adapter, changes):
    changes = dict(changes)
    action = changes.pop("action", "StartBackend")
    reply = adapter.send(action, **changes)
    assert reply.get("state") != "accepted"
    assert adapter.owner("consume")["id"] is None
    assert adapter.send("Status")["owner_id"] == adapter.info["owner"]
    assert adapter.send("StartBackend")["state"] == "accepted"


@pytest.mark.parametrize("fault", ["caller-reused", "wrong-generation"])
def test_retained_os_birth_and_backend_generation_rechecked(adapter, fault):
    adapter.owner("running")
    accepted = adapter.send("RestartBackend", confirmation=None)  # Existing four-key adapter wire.
    assert accepted["state"] == "accepted"
    adapter.owner(fault)
    assert adapter.owner("consume")["id"] is None
    assert adapter.send("ReadOperation", accepted["request_id"])["state"] == "blocked"
    assert adapter.send("StartBackend")["state"] == "accepted"


def test_caller_identity_lost_after_dequeue_does_not_strand_single_flight(adapter):
    accepted = adapter.send("StartBackend")
    assert adapter.owner("dequeue")["id"] == accepted["request_id"]
    adapter.owner("caller-reused")
    assert adapter.owner("begin", id=accepted["request_id"]) == {"begun": False}
    assert adapter.send("ReadOperation", accepted["request_id"])["state"] == "blocked"
    assert adapter.send("StartBackend")["state"] == "accepted"


def test_exited_independent_caller_cannot_be_replaced_by_reused_pid(adapter):
    # A real third process submits then exits; no PID-only rediscovery at consume.
    program = ("import ctypes,json,time\nfrom ctypes import wintypes\nfrom types import SimpleNamespace\nfrom uuid import uuid4\n"
               + "CONFIRM=" + repr(CONFIRM) + "\n" + inspect.getsource(Adapter)
               + "\ninfo=" + repr(adapter.info) + "\n"
               + "client=Adapter(SimpleNamespace(pid=info['pid'],poll=lambda:None),info)\n"
               + "print(json.dumps(client.send('StartBackend')))\n")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", program],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    accepted = json.loads(result.stdout)
    assert accepted["state"] == "accepted"
    assert adapter.owner("consume")["id"] is None
    assert adapter.send("ReadOperation", accepted["request_id"])["state"] == "blocked"
    assert adapter.send("StartBackend")["state"] == "accepted"


def test_schema_selector_failure_and_consume_io_failure_are_readable(adapter):
    accepted = adapter.send("SchemaUpgrade")
    assert adapter.owner("consume")["begun"]
    adapter.owner("finish", id=accepted["request_id"], kind="SchemaUpgrade", failure="SCHEMA_CONFIGURED_TARGET_UNAVAILABLE")
    receipt = adapter.send("ReadOperation", accepted["request_id"])
    assert receipt["state"] == "blocked" and receipt["reason"] == "SCHEMA_CONFIGURED_TARGET_UNAVAILABLE"
    assert receipt["next_action"] == "Status_then_CheckStart_configured_target_diagnostics"
    assert adapter.send("StartBackend")["state"] == "accepted"
    assert adapter.owner("locked-consume") == {"failed": True, "reused": False}
    assert adapter.send("StartBackend")["state"] == "accepted"


def test_direct_caller_cannot_spoof_backend_preflight(adapter):
    adapter.owner("running")
    reply = adapter.send("RestartBackend", confirmation=None, backend_preflight="{}")
    assert reply["state"] == "blocked" and reply["reason"] == "BACKEND_PREFLIGHT_NOT_ATTESTED"
    assert adapter.send("RestartBackend", confirmation=None)["state"] == "accepted"


def test_direct_restart_uses_real_owned_stop_and_retained_exit_reducer(adapter):
    observed = adapter.owner("owned-running")
    assert observed["backend_pid"] not in {os.getpid(), adapter.process.pid}
    accepted = adapter.send("RestartBackend", confirmation=None)
    assert accepted["state"] == "accepted"
    request_id = accepted["request_id"]
    assert adapter.owner("consume")["begun"]
    assert adapter.owner("owned-stop", id=request_id) == {"exact": True, "forced": False, "can_start": True}
    receipt = adapter.send("ReadOperation", request_id)
    assert receipt["stop_outcome"] == "stopped" and receipt["stop_evidence"]["ExactExit"]
    assert receipt["state"] == "failed" and receipt["reason"] == "SAFE_START_UNAVAILABLE"
    assert receipt["successor_outcome"] == "NOT_ATTEMPTED"
    assert adapter.send("StartBackend")["state"] == "accepted"


def test_direct_intent_then_production_prepare_and_writer_fence_on_temporary_sqlite(adapter, restart_runtime, monkeypatch):
    # Complements the retained C# exit test: exercise the real Backend transport
    # and RuntimeCoordinator, without binding a socket or importing app.main.
    adapter.owner("running")
    accepted = adapter.send("RestartBackend", confirmation=None)
    assert accepted["state"] == "accepted" and adapter.owner("consume")["begun"]
    _exercise_owned_transport(restart_runtime, monkeypatch, "normal")
    runtime, owner, _, path = restart_runtime
    assert path.is_file() and owner.observation()["active_connections"] == 0
    assert runtime._stop_task.done()
    adapter.owner("finish", id=accepted["request_id"], kind="RestartBackend")
    # This fixture has no successor. Do not fabricate a runtime success receipt.
    assert adapter.send("ReadOperation", accepted["request_id"])["state"] == "unknown"
