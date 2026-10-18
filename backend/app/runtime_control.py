"""Bounded transport to the existing launcher. No lifecycle or database authority."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

SCHEMA = "omi.runtime-control.v1"
TOKEN_ENV = "OMI_RUNTIME_CONTROL_TOKEN_SHA256"
MAX_MESSAGE = 16384
ROOT = Path(__file__).resolve().parents[2]


class RestartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: UUID
    expected_owner_id: UUID
    confirmation: Literal["restart_backend"]


def bundle_id() -> str | None:
    """Disk control bundle only; this is NOT an attestation of the loaded release."""
    try:
        digest = hashlib.sha256()
        for name in (
            "backend/app/runtime_control.py", "backend/app/routers/runtime_control.py",
            "backend/app/runtime.py",
            "scripts/omi-runtime-control.ps1", "scripts/OmiRuntimeControl.cs",
        ):
            digest.update(name.encode())
            digest.update((ROOT / name).read_bytes())
        return digest.hexdigest()
    except OSError:
        return None


LOADED_CONTROL_BUNDLE_ID = bundle_id()


def token_authorized(token: str | None) -> bool:
    configured = os.environ.get(TOKEN_ENV, "")
    if len(configured) != 64 or any(c not in "0123456789abcdef" for c in configured):
        return False
    # Provision a separate random 32-byte token, represented as 64 lowercase hex.
    if token is None or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode("ascii")).hexdigest(), configured)


def unknown_operation(request_id: str, reason: str = "CONTROLLER_UNAVAILABLE") -> dict:
    return {"schema": SCHEMA, "request_id": request_id, "action": "RestartBackend",
            "state": "unknown", "reason": reason, "owner_id": None,
            "before": None, "after": None, "updated_at": None,
            "loaded_release_identity": "UNATTESTED"}


def unknown_status() -> dict:
    return {"schema": SCHEMA, "owner_id": None,
            "launcher": {"status": "unknown", "identity": "UNATTESTED"},
            "backend": {"status": "unknown", "identity": "UNATTESTED"},
            "frontend": {"status": "unknown", "identity": "UNATTESTED"},
            "mcp_dependency": {"status": "unknown", "identity": "UNATTESTED",
                               "reason": "EXTERNAL_ADAPTER_NOT_ATTESTED"},
            "restart": {"available": False, "reason": "CONTROLLER_UNAVAILABLE"}}


def _process_created_filetime(kernel, pid: int) -> int:
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OSError("OWNER_NOT_ATTESTED")
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in times)):
            raise OSError("OWNER_NOT_ATTESTED")
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def launcher_request(action: str, *, request_id: str | None = None,
                     expected_owner_id: str | None = None, token: str | None = None,
                     backend_preflight: dict | None = None) -> dict:
    """Fixed pipe, server PID + creation pinned by launcher-inherited environment.

    No discovery, redirects, subprocesses, arbitrary endpoints, or fallback owner.
    Nonblocking pipe IO has a single two-second deadline and bounded frames.
    """
    if action not in {"Status", "ReadOperation", "RestartBackend"}:
        raise ValueError("UNSUPPORTED_ACTION")
    if os.name != "nt":
        raise OSError("WINDOWS_OWNER_REQUIRED")
    owner_pid = int(os.environ.get("OMI_RUNTIME_LAUNCHER_PID", "0"))
    owner_created = int(os.environ.get("OMI_RUNTIME_LAUNCHER_CREATED", "0"))
    if owner_pid <= 0 or owner_created <= 0:
        raise OSError("OWNER_NOT_ATTESTED")
    suffix = hashlib.sha256(str(ROOT).lower().encode("utf-8")).hexdigest()[:24]
    name = "\\\\.\\pipe\\omi-runtime-" + suffix
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    kernel.SetNamedPipeHandleState.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
                                              ctypes.c_void_p, ctypes.c_void_p]
    for method in (kernel.ReadFile, kernel.WriteFile):
        method.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    handle = kernel.CreateFileW(name, 0xC0000000, 0, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("CONTROLLER_UNAVAILABLE")
    try:
        actual_pid = wintypes.ULONG()
        if (not kernel.GetNamedPipeServerProcessId(handle, ctypes.byref(actual_pid))
                or actual_pid.value != owner_pid
                or _process_created_filetime(kernel, owner_pid) != owner_created):
            raise OSError("OWNER_NOT_ATTESTED")
        mode = wintypes.DWORD(1)  # PIPE_NOWAIT, byte mode
        if not kernel.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            raise OSError("PIPE_MODE_UNAVAILABLE")
        message = {"action": action, "request_id": request_id,
                   "expected_owner_id": expected_owner_id, "token": token}
        if action == "RestartBackend" and backend_preflight is not None:
            # Internal observation only; never accepted in the public HTTP body.
            message["backend_preflight"] = json.dumps(backend_preflight, separators=(",", ":"))
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(payload) > MAX_MESSAGE:
            raise ValueError("REQUEST_TOO_LARGE")
        sent = wintypes.DWORD()
        if not kernel.WriteFile(handle, payload, len(payload), ctypes.byref(sent), None) or sent.value != len(payload):
            raise OSError("PIPE_WRITE_FAILED")
        deadline = time.monotonic() + 2
        result = bytearray()
        while time.monotonic() < deadline and len(result) <= MAX_MESSAGE:
            buffer = ctypes.create_string_buffer(4096)
            count = wintypes.DWORD()
            ok = kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None)
            if count.value:
                result.extend(buffer.raw[:count.value])
                if b"\n" in result:
                    if len(result) > MAX_MESSAGE:
                        raise OSError("RESPONSE_TOO_LARGE")
                    value = json.loads(result.split(b"\n", 1)[0])
                    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
                        raise OSError("INVALID_CONTROLLER_RESPONSE")
                    return value
            elif not ok and ctypes.get_last_error() not in {232, 536}:
                raise OSError("PIPE_READ_FAILED")
            time.sleep(0.01)
        raise OSError("CONTROLLER_TIMEOUT")
    finally:
        kernel.CloseHandle(handle)
