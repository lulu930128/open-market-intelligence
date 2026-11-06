"""OMI-local config bootstrap, executed with OMI .venv (python-dotenv installed).

No broker/application import here. Credentials travel only in the child process
environment, never arguments, files, stdout, stderr, or captured diagnostics.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from .storage import OwnerLease
from .service import record_startup, replace_receipt


ROOT = Path(__file__).resolve().parents[1]
KEYS = ("KGI_SUPERPY_PERSON_ID", "KGI_SUPERPY_PASSWORD", "KGI_SUPERPY_TW_ACCOUNT", "KGI_SUPERPY_SIMULATION",
        "KGI_SUPERPY_US_ENABLED", "KGI_SUPERPY_US_ACCOUNT")


class LauncherOwner:
    """Retained Windows identity; loss requests OFFLINE, never starts a watchdog."""
    def __init__(self, pid, created):
        import ctypes
        from ctypes import wintypes as W
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.GetProcessTimes.argtypes = [W.HANDLE, W.LPVOID, W.LPVOID, W.LPVOID, W.LPVOID]
        self.kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        times = [ctypes.c_ulonglong() for _ in range(4)]
        if not self.kernel.GetProcessTimes(self.handle, *[ctypes.byref(t) for t in times]) or times[0].value != int(created):
            self.close()
            raise RuntimeError("LAUNCHER_OWNER_IDENTITY_MISMATCH")
        self.pid, self.created = pid, str(created)

    def alive(self):
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result not in {0, 258}:
            raise RuntimeError("LAUNCHER_OWNER_UNVERIFIED")
        return result == 258

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def read_receipt(path):
    """Read atomic receipts without blocking Windows replacement by their owner."""
    if os.name != "nt":
        return json.loads(path.read_text(encoding="utf-8"))
    import ctypes
    from ctypes import wintypes as W
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.ReadFile.argtypes = [W.HANDLE, W.LPVOID, W.DWORD, ctypes.POINTER(W.DWORD), W.LPVOID]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    # GENERIC_READ, FILE_SHARE_READ|WRITE|DELETE, OPEN_EXISTING. Sharing deletion
    # changes no ACL and grants no access beyond the ordinary read permission.
    # abspath is lexical; Path.resolve itself opens a Windows handle without our
    # sharing flags and can race the writer before CreateFileW even runs.
    deadline = time.monotonic() + 0.5
    while True:
        handle = kernel.CreateFileW(os.path.abspath(path), 0x80000000, 7, None, 3, 0, None)
        if handle != W.HANDLE(-1).value:
            break
        error = ctypes.get_last_error()
        # ReplaceFile's very short rename window can deny an otherwise shared
        # open. Retry ONLY ERROR_SHARING_VIOLATION, bounded to half a second.
        # ACL denial, identity and JSON errors never enter this retry path.
        if error != 32 or time.monotonic() >= deadline:
            raise ctypes.WinError(error)
        time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    try:
        buffer, read = ctypes.create_string_buffer(65537), W.DWORD()
        if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if read.value > 65536:
            raise ValueError("RECEIPT_TOO_LARGE")
        return json.loads(buffer.raw[:read.value].decode("utf-8"))
    finally:
        kernel.CloseHandle(handle)


def optional_receipt(path):
    try:
        return read_receipt(path)
    except FileNotFoundError:
        return None


def wait_startup(process, state, startup_id, *, timeout=30):
    """This launch's receipt only; stale RUNNING snapshots never imply readiness."""
    deadline = time.monotonic() + timeout
    path = state / ("startup-" + startup_id + ".json")
    latest = None
    while True:
        value = optional_receipt(path)
        if value is not None:
            if value.get("startup_id") != startup_id or value.get("status") not in {
                    "READY", "BLOCKED", "STARTING", "CONNECTING", "RECOVERING", "BACKOFF", "STOPPING", "STOPPED"}:
                return {"status": "BLOCKED", "code": "STARTUP_RECEIPT_INVALID", "startup_id": startup_id}
            if value["status"] in {"READY", "BLOCKED", "STOPPED"}:
                return value
            latest = value
        if process.poll() is not None:
            return {"status": "BLOCKED", "code": "CHILD_EXITED_BEFORE_READY", "startup_id": startup_id}
        if time.monotonic() >= deadline:
            return {"status": "STARTING", "launcher_pid": process.pid, "startup_id": startup_id,
                    "last_observed_status": latest.get("status") if latest else None,
                    "acceptance": "UNVERIFIED", "retry_policy": "CHECK_STATUS_DO_NOT_RELAUNCH"}
        time.sleep(0.1)


def request_supervisor_stop(state, *, timeout=5):
    """Persist an exact supervisor stop intent; only its acknowledgement counts."""
    active = read_receipt(state / "supervisor-status.json")
    identity = active.get("startup_id", "")
    if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise RuntimeError("SUPERVISOR_IDENTITY_UNVERIFIED")
    request_id = uuid4().hex
    target = state / ("supervisor-stop-" + identity + ".json")
    temporary = target.with_suffix("." + request_id + ".tmp")
    temporary.write_text(json.dumps({"startup_id": identity, "request_id": request_id, "desired": "OFFLINE"}), encoding="utf-8")
    replace_receipt(temporary, target)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read_receipt(state / "supervisor-status.json")
        if value.get("startup_id") == identity and value.get("stop_request_id") == request_id:
            return {**value, "acknowledged": True}
        time.sleep(0.1)
    return {"status": "UNKNOWN", "startup_id": identity, "stop_request_id": request_id,
            "acknowledged": False, "code": "SUPERVISOR_STOP_UNCONFIRMED"}


def supervise(command, environment, state, startup_id, *, spawn=subprocess.Popen,
              retry_base=5.0, retry_cap=300.0, owner=None):
    """The one existing launch owner supervises one fully exited child at a time.

    No process guessing, force kill, order replay, service or scheduled task.
    Native still owns the session and Journal; this lease only excludes a second
    launch supervisor. An uncertain native lease always blocks replacement.
    """
    lease = OwnerLease(state / "launch-supervisor")
    lease.acquire()
    failures = 0
    stop_request = None
    last_value, last_publish = {}, 0.0
    child = None

    def publish(value):
        nonlocal last_value, last_publish
        last_value, last_publish = value, time.monotonic()
        value = {**value, "supervisor_pid": os.getpid(), "startup_id": startup_id,
                 "observed_at": datetime.now(timezone.utc).isoformat(),
                 "desired": "OFFLINE" if stop_request or value.get("reason") == "OPERATOR_STOP" else value.get("desired", "ONLINE")}
        if owner is not None:
            value.update(owner_pid=owner.pid, owner_created=owner.created)
        if child is not None and isinstance(getattr(child, "pid", None), int):
            value["child_launcher_pid"] = child.pid
        if stop_request:
            value["stop_request_id"] = stop_request
        record_startup(state, startup_id, value)
        temporary = state / "supervisor-status.tmp"
        temporary.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
        replace_receipt(temporary, state / "supervisor-status.json")

    def stop_requested():
        nonlocal stop_request
        if owner is not None and not owner.alive() and stop_request is None:
            stop_request = "owner-lost-" + uuid4().hex
        target = state / ("supervisor-stop-" + startup_id + ".json")
        value = optional_receipt(target)
        if value is not None:
            if value.get("startup_id") == startup_id and value.get("desired") == "OFFLINE":
                stop_request = value["request_id"]
        if time.monotonic() - last_publish >= 1:
            publish(last_value)
        return stop_request is not None

    try:
        publish({"status": "STARTING"})
        while True:
            # A previous redirector exit alone does not prove native ownership ended.
            native = OwnerLease(state / "native-session")
            try:
                native.acquire()
            except Exception:
                publish({"status": "BLOCKED", "code": "NATIVE_OWNER_UNVERIFIED"})
                return 2
            native.release()
            if stop_requested():
                publish({"status": "STOPPED", "owner_released": True})
                return 0
            child_id = uuid4().hex
            child = spawn([*command, "--persistent", "--startup-id", child_id], cwd=ROOT, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            child_receipt, observed = None, None
            started = time.monotonic()
            stop_sent = False
            path = state / ("startup-" + child_id + ".json")
            while True:
                value = optional_receipt(path)
                if value is not None:
                    if value.get("startup_id") != child_id:
                        raise RuntimeError("STARTUP_RECEIPT_IDENTITY_MISMATCH")
                    child_receipt = value
                    if value != observed:
                        publish({**value, "child_startup_id": child_id,
                            "supervisor_pid": os.getpid(), "restart_count": failures})
                        observed = value
                code = child.poll()
                if code is not None:
                    break
                if stop_requested():
                    publish({"status": "STOPPING", "child_startup_id": child_id, "owner_released": False})
                    if not stop_sent and child_receipt and child_receipt.get("pid"):
                        from .control import request_control
                        # OS-authenticated peer must be the child that acknowledged
                        # this startup. Never stop a guessed/reused process.
                        response = request_control({"operation": "stop"}, expected_pid=child_receipt["pid"], timeout=5)
                        if not response.get("ok"):
                            publish({"status": "BLOCKED", "code": "NATIVE_STOP_UNCONFIRMED"})
                            return 2
                        stop_sent = True
                time.sleep(0.1)
            # poll() may observe an exit immediately after the first receipt
            # read. Re-read AFTER proven exit so a just-acknowledged stop wins.
            final_receipt = optional_receipt(path)
            if final_receipt is not None:
                child_receipt = final_receipt
                if child_receipt.get("startup_id") != child_id:
                    raise RuntimeError("STARTUP_RECEIPT_IDENTITY_MISMATCH")
                publish({**child_receipt, "child_startup_id": child_id,
                    "supervisor_pid": os.getpid(), "restart_count": failures})
            if stop_requested():
                # Iterate through the same lease proof before publishing STOPPED.
                continue
            # Child terminal receipt is written before its normal process exit.
            if child_receipt and child_receipt.get("reason") == "OPERATOR_STOP":
                native = OwnerLease(state / "native-session")
                try:
                    native.acquire()
                except Exception:
                    publish({"status": "BLOCKED", "reason": "OPERATOR_STOP", "code": "NATIVE_OWNER_UNVERIFIED"})
                    return 2
                native.release()
                publish({"status": "STOPPED", "reason": "OPERATOR_STOP", "owner_released": True})
                return 0  # An acknowledged OFFLINE remains offline even after a crash.
            if code in {0, 1, 2} or not child_receipt or child_receipt.get("status") != "READY":
                publish({"status": "BLOCKED", "code": "CHILD_EXIT_REQUIRES_OPERATOR",
                    "exit_code": code, "supervisor_pid": os.getpid()})
                return 2
            # Unexpected nonzero exit: before every restart reacquire the exact
            # native lease. Same journal startup handles UNKNOWN, never resend.
            if time.monotonic() - started >= 60:
                failures = 0
            failures += 1
            delay = min(retry_cap, retry_base * 2 ** min(failures - 1, 16))
            publish({"status": "RECOVERING", "code": "CHILD_EXITED",
                "exit_code": code, "supervisor_pid": os.getpid(), "restart_count": failures,
                "retry_in_seconds": delay, "resend": False})
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline and not stop_requested():
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    finally:
        lease.release()


def child_environment(root, environment):
    # Same OMI-local file order and env-over-file precedence as app.config.
    # No backend import or settings initialization; reuse its dotenv parser.
    from dotenv import dotenv_values
    values = {}
    for name in (".env", ".env.runtime"):
        path = root / name
        if path.is_file():
            parsed = dotenv_values(path, encoding="utf-8")
            values.update({key: parsed[key] for key in KEYS if parsed.get(key) is not None})
    values.update({key: environment[key] for key in KEYS if key in environment})
    child = {key: value for key, value in environment.items() if not key.startswith("KGI_SUPERPY_")}
    child.update(values)
    return child


def main(argv=None):
    parser = argparse.ArgumentParser(description="Load existing OMI .env/.env.runtime and start the native stdin runtime")
    parser.add_argument("--connect", action="store_true", help="Explicit native login; never sends an entry without confirm")
    parser.add_argument("--stop", action="store_true", help="Request OFFLINE from the exact launch supervisor, including recovery backoff")
    parser.add_argument("--enable-strategy-effects", action="store_true")
    parser.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--startup-id", help=argparse.SUPPRESS)
    parser.add_argument("--owner-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--owner-created", help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--background", action="store_true")
    args = parser.parse_args(argv)
    if args.stop:
        if args.connect or args.background or args.probe or args.supervise or args.enable_strategy_effects:
            parser.error("--stop cannot start or connect")
        try:
            value = request_supervisor_stop(ROOT / "data" / "execution-runtime")
            print(json.dumps(value, ensure_ascii=True))
            return 0 if value["acknowledged"] else 2
        except Exception:
            print('{"status":"UNKNOWN","acknowledged":false,"code":"SUPERVISOR_STOP_UNCONFIRMED"}')
            return 2
    if not args.connect:
        parser.error("--connect is required; no configuration or credentials loaded")
    if args.probe and args.enable_strategy_effects:
        parser.error("probe forbids strategy effects")
    if args.supervise and (args.probe or args.background or not args.startup_id or
            len(args.startup_id) != 32 or any(c not in "0123456789abcdef" for c in args.startup_id)):
        parser.error("invalid supervisor startup identity")
    if bool(args.owner_pid) != bool(args.owner_created) or (args.owner_pid and not args.supervise):
        parser.error("owner identity requires supervisor mode")
    interpreter = ROOT / ".venv-kgi" / "Scripts" / "python.exe"
    if not interpreter.is_file():
        print('{"status":"BLOCKED","error":"OMI_VENV_KGI_MISSING"}')
        return 2
    try:
        environment = child_environment(ROOT, os.environ)
        command = [str(interpreter), "-B", "-m", "execution_runtime", "native", "--connect"]
        if args.enable_strategy_effects:
            command.append("--enable-strategy-effects")
        if args.probe:
            command.append("--probe")
        if args.supervise:
            owner = LauncherOwner(args.owner_pid, args.owner_created) if args.owner_pid else None
            try:
                return supervise(command, environment, ROOT / "data" / "execution-runtime", args.startup_id, owner=owner)
            finally:
                if owner is not None:
                    owner.close()
        if args.background:
            startup_id = uuid4().hex
            command = [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-B", "-m", "execution_runtime.launch",
                       "--connect", "--supervise", "--startup-id", startup_id]
            if args.enable_strategy_effects:
                command.append("--enable-strategy-effects")
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startup,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            receipt = wait_startup(process, ROOT / "data" / "execution-runtime", startup_id)
            print(json.dumps(receipt, ensure_ascii=True))
            return 0 if receipt["status"] == "READY" else 2
        # Inherit one stdin/stdout pair; no server, polling, retries or daemon.
        process = subprocess.Popen(command, cwd=ROOT, env=environment)
        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # The console also delivers Ctrl+C to the child. Let its
                # runtime close/logout finish; never kill it from the bootstrap.
                continue
    except KeyboardInterrupt:
        return 130
    except Exception:
        if args.supervise:
            record_startup(ROOT / "data" / "execution-runtime", args.startup_id,
                           {"status": "BLOCKED", "code": "SUPERVISOR_FAILED_CHECK_OWNER"})
        print('{"status":"BLOCKED","error":"OMI_CONFIG_OR_LAUNCH_FAILED"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
