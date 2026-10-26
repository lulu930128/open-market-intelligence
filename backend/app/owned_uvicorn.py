"""Fixed Uvicorn entry for the launcher-owned inherited control channel.

No HTTP stop endpoint, PID signal, force exit or writer-authority override.
Production launch adoption is deliberately gated in the launcher. The disposable
app is supplied by a fixed test entry, not by an IPC import string.
"""
from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import json
import hashlib
import marshal
import os
import queue
import sys
import threading
import time
import uuid

import uvicorn

_control_stdout = sys.stdout


def creation(pid: int) -> str:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(v) for v in values]):
            raise ctypes.WinError(ctypes.get_last_error())
        return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def emit(value):
    try:
        print(json.dumps(value, separators=(",", ":")), file=_control_stdout, flush=True)
        return True
    except (OSError, ValueError):
        # A vanished reader cannot cancel Server.serve and thereby trigger a
        # terminal lifespan stop. Prepared admission expires independently.
        return False


def read_boot():
    line = sys.stdin.readline(8193)
    if not line.endswith("\n") or len(line) > 8192:
        raise ValueError("BOOT_FRAME_INVALID")
    boot = json.loads(line)
    if not isinstance(boot, dict) or boot.get("scope") not in {"DISPOSABLE", "PRODUCTION"}:
        raise ValueError("BOOT_SCOPE_INVALID")
    if boot["runner_pid"] != str(os.getppid()):
        raise ValueError("RUNNER_PARENT_MISMATCH")
    for role in ("runner", "launcher"):
        if creation(int(boot[role + "_pid"])) != boot[role + "_created"]:
            raise ValueError("OWNER_CREATION_MISMATCH")
    nonce = boot.get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 64 or any(c not in "0123456789abcdef" for c in nonce):
        raise ValueError("NONCE_REQUIRED")
    if str(uuid.UUID(boot["instance"])) != boot["instance"]:
        raise ValueError("INSTANCE_INVALID")
    return boot


def production_start_config(boot):
    """Validate before importing app.main (which can initialize app resources).

    Only inherited fixed configuration is accepted, never a default port or an
    arbitrary ASGI entry. This does not grant STOP or full-release attestation.
    """
    if boot.get("scope") != "PRODUCTION":
        raise ValueError("PRODUCTION_SCOPE_REQUIRED")
    if any(boot.get(role + key) != os.environ.get(env) for role, key, env in (
        ("launcher", "_pid", "OMI_RUNTIME_LAUNCHER_PID"),
        ("launcher", "_created", "OMI_RUNTIME_LAUNCHER_CREATED"),
    )):
        raise ValueError("INHERITED_LAUNCHER_MISMATCH")
    host, port = boot.get("host"), boot.get("port")
    if host not in {"127.0.0.1", "::1"} or host != os.environ.get("OMI_BACKEND_HOST"):
        raise ValueError("FIXED_HOST_REQUIRED")
    if not isinstance(port, str) or not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("FIXED_PORT_REQUIRED")
    if str(int(port)) != port or port != os.environ.get("OMI_BACKEND_PORT"):
        raise ValueError("FIXED_PORT_REQUIRED")
    return {"host": host, "port": int(port), "workers": 1, "reload": False}


async def serve_owned(app, *, fixture_owner=None, boot=None):
    """Run real ASGI shutdown; only the owner channel can request cooperative exit."""
    boot = read_boot() if boot is None else boot
    if fixture_owner is not None and boot["scope"] != "DISPOSABLE":
        raise ValueError("FIXTURE_SCOPE_REQUIRED")
    fixed_config = {} if fixture_owner is not None else production_start_config(boot)
    identity = {key: boot[key] for key in (
        "instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created")}
    identity.update(child_pid=str(os.getpid()), child_created=creation(os.getpid()))
    messages = queue.Queue(maxsize=4)

    def read_control():
        try:
            while True:
                line = sys.stdin.readline(8193)
                if not line or len(line) > 8192:
                    messages.put(None)
                    return
                value = json.loads(line)
                messages.put(value if isinstance(value, dict) else None)
        except (ValueError, OSError):
            messages.put(None)

    threading.Thread(target=read_control, daemon=True).start()
    config = uvicorn.Config(app, lifespan="on", log_level="warning", access_log=False, **fixed_config)
    server = uvicorn.Server(config)
    # Fixtures have no sockets and cannot import app.main or connect to a DB.
    serving = asyncio.create_task(server.serve(sockets=[] if fixture_owner else None))
    started = time.monotonic()
    while not server.started:
        if serving.done() or time.monotonic() - started > (5 if fixture_owner else 90):
            raise RuntimeError("LIFESPAN_STARTUP_FAILED")
        await asyncio.sleep(.01)
    # This fingerprint is over executing transport code, not a reread disk hash
    # or a certificate for app.main/dependencies. Keep full release untrusted.
    serving_identity = dict(identity, state="READY")
    if fixture_owner is None:
        runtime = getattr(app.state, "runtime", None)
        if runtime is None or not runtime.started:
            server.should_exit = True
            await serving
            raise RuntimeError("RUNTIME_STARTUP_NOT_READY")
        serving_identity.update(
            host=fixed_config["host"], port=str(fixed_config["port"]),
            loaded_entry_sha256=hashlib.sha256(marshal.dumps(serve_owned.__code__)).hexdigest(),
            loaded_release_identity="APPLICATION_SOURCE_SNAPSHOT",
            release_id=sys.modules["_omi_owned_release"].release_id,
            restart_blocker=runtime.owned_restart_preflight()["state"],
            restart_abort_protocol="1",
        )
        app.state.owned_start = {key: serving_identity[key] for key in (
            "child_pid", "child_created", "instance", "host", "port", "release_id", "loaded_release_identity", "restart_blocker")}
    emit(serving_identity)
    prepared = None
    stop_requested = False
    expired = False
    while not serving.done():
        try:
            message = messages.get_nowait()
        except queue.Empty:
            message = {}
        # Fixture-only finite lease: independent cooperative cleanup, never Stop proof.
        if fixture_owner and time.monotonic() - started > 7:
            expired = True
            fixture_owner.release()
            server.should_exit = True
        if message is None:
            # Owner loss does not authorize production shutdown.
            if fixture_owner is None and not stop_requested:
                runtime.abort_owned_restart()
                prepared = None
            message = {}
        # Retain the authenticated PREPARE correlation after lease expiry. A
        # missing guard is not rearm evidence, nor authority to execute STOP.
        if message:
            valid = all(message.get(k) == v for k, v in identity.items())
            try:
                uuid.UUID(message["request_id"])
                remaining = int(message["deadline"]) - int(time.time() * 1000)
                valid = valid and 0 < remaining <= (10000 if fixture_owner else 120000)
                for role in ("runner", "launcher"):
                    valid = valid and creation(int(identity[role + "_pid"])) == identity[role + "_created"]
            except (KeyError, ValueError, OSError, TypeError, AttributeError):
                valid = False
            if not valid:
                emit(dict(identity, state="REJECTED"))
            elif message.get("action") == "PREPARE" and prepared is None:
                if fixture_owner is None:
                    runtime = getattr(app.state, "runtime", None)
                    prepare = getattr(runtime, "prepare_owned_restart", None)
                    state = "PRODUCTION_WRITER_COVERAGE_UNAVAILABLE"
                    outcome = {}
                    if callable(prepare) and remaining > 1000:
                        try:
                            outcome = await prepare(timeout_seconds=min(60, remaining / 1000 - 1))
                            state = outcome["state"]
                        except Exception:
                            state = "PREFLIGHT_REARMED" if runtime.abort_owned_restart() else "REARM_UNKNOWN"
                    if state == "WRITERS_PREPARED":
                        prepared = message.copy()
                    emit(dict(message, state=state, stage=outcome.get("stage", ""),
                              rearmed="true" if state == "PREFLIGHT_REARMED" and runtime.owned_restart_rearmed() else "false"))
                else:
                    state = await fixture_owner.prepare()
                    if state == "DISPOSABLE_DRAINED":
                        prepared = message.copy()
                    emit(dict(message, state=state))
            elif message.get("action") == "ABORT_PREPARE" and fixture_owner is None and prepared is not None and all(
                message.get(k) == prepared.get(k) for k in ("request_id", "deadline")
            ) and not stop_requested:
                # Only the same authenticated operation can undo its reversible
                # PREPARE. No STOP, exit, or new admission owner is introduced.
                rearmed = runtime.abort_owned_restart() and runtime.owned_restart_rearmed()
                emit(dict(message, state="PREFLIGHT_REARMED" if rearmed else "REARM_UNKNOWN",
                          rearmed="true" if rearmed else "false", stage="RESTART_SOURCE_CHANGED"))
                if rearmed:
                    prepared = None
            elif message.get("action") == "STOP" and prepared is not None and all(
                message.get(k) == prepared.get(k) for k in ("request_id", "deadline")
            ) and not stop_requested:
                if fixture_owner is None:
                    try:
                        runtime.commit_owned_restart()
                    except RuntimeError:
                        rearmed = runtime.abort_owned_restart() and runtime.owned_restart_rearmed()
                        emit(dict(message, state="PREFLIGHT_REARMED" if rearmed else "REARM_UNKNOWN",
                                  rearmed="true" if rearmed else "false", stage="PREPARE_AUTHORITY_EXPIRED"))
                        if rearmed:
                            prepared = None
                        continue
                stop_requested = True
                emit(dict(message, state="STOP_ACCEPTED"))
                server.should_exit = True
            else:
                emit(dict(message, state="REJECTED"))
        await asyncio.sleep(.01)
    await serving
    if stop_requested and not expired and not server.lifespan.error_occurred and not server.lifespan.shutdown_failed:
        if fixture_owner is None and not runtime.restart_preflight()["all_writers_drained"]:
            return 73
        # Uvicorn observes lifespan.shutdown.complete only after runtime.stop returns.
        emit(dict(prepared, state="LIFESPAN_COMPLETE"))
        return 0
    return 72


def main():
    # Fixed production entry, only through the inherited Launcher/Runner channel.
    boot = read_boot()
    production_start_config(boot)
    release = sys.modules.get("_omi_owned_release")
    if release is None or boot.get("release_id") != release.release_id:
        raise ValueError("APPLICATION_SOURCE_MISMATCH")
    release.verified = True
    # Application stdout must not become control frames or disclose credentials
    # to the owner channel. Runner still needs production stderr/log adoption.
    sys.stdout = sys.stderr
    from app.main import app

    return asyncio.run(serve_owned(app, boot=boot))


if __name__ == "__main__":
    raise SystemExit(main())
