"""Read-only Restart Manager feasibility; only three lexical candidate resources.

No filesystem probe of the candidate, SQL connection, lifecycle API, elevation,
service enumeration or command-line collection. A positive match is not a writer
classification. Empty/denied/unstable queries never establish writer absence.
"""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).absolute().parents[1]
CANDIDATE = str(ROOT / "data/open_market_intelligence.db")
RESOURCES = {"DB": CANDIDATE, "WAL": CANDIDATE + "-wal", "SHM": CANDIDATE + "-shm"}


class Unique(C.Structure):
    _fields_ = [("pid", W.DWORD), ("started", W.FILETIME)]


class Info(C.Structure):
    _fields_ = [("process", Unique), ("app_name", W.WCHAR * 256),
                ("service_name", W.WCHAR * 64), ("application_type", C.c_int),
                ("app_status", W.ULONG), ("session_id", W.DWORD), ("restartable", W.BOOL)]


def api():
    dll = C.WinDLL("rstrtmgr.dll", use_last_error=True)
    signatures = {
        "RmStartSession": [C.POINTER(W.DWORD), W.DWORD, W.LPWSTR],
        "RmRegisterResources": [W.DWORD, W.UINT, C.POINTER(W.LPCWSTR), W.UINT, C.c_void_p, W.UINT, C.c_void_p],
        "RmGetList": [W.DWORD, C.POINTER(W.UINT), C.POINTER(W.UINT), C.POINTER(Info), C.POINTER(W.DWORD)],
        "RmEndSession": [W.DWORD],
    }
    for name, args in signatures.items():
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = args, W.DWORD
    return dll


def query(role: str, dll=None) -> dict:
    if role not in RESOURCES:
        raise ValueError("named resource role required")
    result = {"role": role, "status": "UNKNOWN", "positive_matches": [],
              "writer_absence": "UNKNOWN", "calls": [], "session_ended": False}
    dll = dll or api()
    session, key = W.DWORD(), C.create_unicode_buffer(33)
    code = dll.RmStartSession(C.byref(session), 0, key)
    result["calls"].append(["RmStartSession", code])
    if code:
        return result
    try:
        names = (W.LPCWSTR * 1)(RESOURCES[role])
        code = dll.RmRegisterResources(session, 1, names, 0, None, 0, None)
        result["calls"].append(["RmRegisterResources", code])
        if code:
            return result
        capacity = 0
        for _ in range(3):
            needed, count, reason = W.UINT(), W.UINT(capacity), W.DWORD()
            entries = (Info * capacity)() if capacity else None
            code = dll.RmGetList(session, C.byref(needed), C.byref(count), entries, C.byref(reason))
            result["calls"].append(["RmGetList", code])
            if code == 234 and 0 < needed.value <= 1024:
                capacity = needed.value
                continue
            if code or count.value > capacity or reason.value:
                return result
            matches = []
            for entry in (entries or [])[:count.value]:
                ticks = entry.process.started.dwLowDateTime | entry.process.started.dwHighDateTime << 32
                if not entry.process.pid or not ticks:
                    return result
                matches.append({"pid": entry.process.pid, "creation_filetime": ticks,
                                "start_time_utc": (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)).isoformat(),
                                "resource_role": role, "match": "POSITIVE", "access_mode": "UNKNOWN"})
            result["positive_matches"] = matches
            result["status"] = "POSITIVE_MATCHES" if matches else "UNKNOWN_NO_MATCHES"
            return result
        return result
    finally:
        code = dll.RmEndSession(session)
        result["calls"].append(["RmEndSession", code])
        result["session_ended"] = code == 0
        if code:
            result["status"] = "UNKNOWN"
            result["positive_matches"] = []


def bounded_probe(role: str, seconds: float = 5.0) -> dict:
    """Launch behind a handshake; cancel only our retained, attested probe handle."""
    spec = importlib.util.spec_from_file_location("r1c_supervisor", ROOT / "scripts/omi-r1-backup-supervisor.py")
    supervisor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(supervisor)
    k = supervisor.kernel()
    process = subprocess.Popen([sys._base_executable, "-B", __file__, "--worker", role],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.DETACHED_PROCESS)
    result = {"role": role, "status": "UNKNOWN", "positive_matches": [], "writer_absence": "UNKNOWN"}
    attested = None
    try:
        attested = supervisor.identity(k, process)
        if attested["executable"] != os.path.normcase(sys._base_executable):
            return {**result, "failure": "EXECUTABLE_MISMATCH"}
        stdout, stderr = process.communicate(b"GO\n", timeout=seconds)
        if process.returncode or stderr or len(stdout) > 262144:
            return {**result, "failure": "PROBE_FAILED"}
        result = json.loads(stdout)
        return result
    except subprocess.TimeoutExpired:
        result["failure"] = "DEADLINE_SESSION_END_UNCONFIRMED"
        return result
    except (OSError, ValueError, supervisor.Closed):
        result["failure"] = "PROBE_UNAVAILABLE"
        return result
    finally:
        if process.poll() is None:
            # On identity failure the gated worker receives EOF and exits; no PID kill.
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            try:
                if attested and supervisor.identity(k, process) == attested:
                    k.TerminateProcess(int(process._handle), 93)
                    process.wait(timeout=1)
                else:
                    result["manual_review"] = True
            except (OSError, supervisor.Closed, subprocess.TimeoutExpired):
                result["manual_review"] = True
        result["probe_pid"] = process.pid
        result["probe_creation_filetime"] = attested["creation_filetime"] if attested else None
        result["probe_cleanup_confirmed"] = process.poll() is not None
        result["probe_exit_code"] = process.poll()
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=RESOURCES)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.worker:
        leash = threading.Timer(8, lambda: os._exit(94))
        leash.daemon = True
        leash.start()
        if sys.stdin.readline().strip() != "GO":
            return 2
        print(json.dumps(query(args.worker)))
        return 0
    if not args.probe:
        parser.error("explicit --probe required")
    started = time.monotonic()
    rows = [bounded_probe(role) for role in RESOURCES]
    print(json.dumps({"contract": "omi.r1c.resource-owners.v1", "observed_at": datetime.now(timezone.utc).isoformat(),
                      "resources": RESOURCES, "results": rows,
                      "elapsed_seconds": round(time.monotonic() - started, 3),
                      "scope": "positive_resource_match_only_not_complete_handle_inventory",
                      "B1": "BLOCKED", "B2": "UNKNOWN", "writer_absence": "UNKNOWN"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
