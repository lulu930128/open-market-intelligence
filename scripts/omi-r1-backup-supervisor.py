"""Bounded Windows maintenance rehearsal. Production input is deliberately unavailable.

The sole backup implementation remains backup-omi-sqlite.py. Workers start behind
an IPC gate, in a private Windows job (no kill-on-close and no tree termination).
Only an attested retained process HANDLE may be cancelled. Fixture watchdogs are
independent of supervisor identity observations; unknown identities are not killed.
"""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import re
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).absolute().parents[1]
BASE = ROOT / ".tmp/us-r0-r5-20261009"
BACKUP = ROOT / "scripts/backup-omi-sqlite.py"
PYTHON = sys._base_executable  # Avoid the Windows venv redirector's extra children.
REVISION = "r1c_disposable_v1"
LIMIT = 2 * 1024 * 1024
SCENARIOS = ("success", "stall", "deadline", "identity_loss", "missing_receipt",
             "bogus_success", "existing_partial", "orphan", "verify_delay",
             "verify_deadline", "independent_deadline", "source_mutation",
             "wal_mutation", "forged_sha", "forged_size", "forged_revision",
             "forged_source", "forged_output", "forged_contract", "forged_counts",
             "corrupt_output", "quick_check_extra", "journal_existing")


class Closed(RuntimeError):
    pass


def checked_path(path: Path) -> Path:
    # Lexical deny precedes resolve/stat: never inspect a rejected production path.
    value = Path(os.path.abspath(path))
    try:
        relative = value.relative_to(BASE)
    except ValueError:
        raise Closed("PRODUCTION_PATH_DENIED") from None
    if not relative.parts or not re.fullmatch(r"r1c-[0-9a-f]{32}", relative.parts[0]):
        raise Closed("SAFE_DIRECTORY_REQUIRED")
    if any(p in {"data", ".env"} or ":" in p for p in relative.parts):
        raise Closed("UNSAFE_COMPONENT")
    for item in reversed((value, *value.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Closed("REPARSE_DENIED")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise Closed("HARDLINK_DENIED")
    return value


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    with checked_path(path).open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def fingerprint(source: Path) -> list:
    rows = []
    for suffix in ("", "-wal", "-shm"):
        path = checked_path(Path(str(source) + suffix))
        try:
            s = path.stat()
        except FileNotFoundError:
            rows.append([suffix, None])
            continue
        if s.st_size > LIMIT:
            raise Closed("FIXTURE_SIZE_LIMIT")
        rows.append([suffix, s.st_size, s.st_mtime_ns, digest(path)])
    return rows


def install_guard(directory: Path) -> None:
    def audit(event, args):
        if event == "subprocess.Popen" and "--worker" not in args[1]:
            raise Closed("UNEXPECTED_SUBPROCESS_DENIED")
        if event == "sqlite3.connect":
            value = str(args[0])
            from urllib.parse import unquote, urlsplit
            if value.startswith("file:"):
                value = unquote(urlsplit(value).path).lstrip("/")
            p = checked_path(Path(value))
            if p.parent != directory:
                raise Closed("FOREIGN_FIXTURE_DENIED")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            name = os.fsdecode(args[0])
            if Path(name).name.startswith(".env"):
                raise Closed("DOTENV_DENIED")
            low = name.lower().replace("\\", "/")
            if "/data/" in low or "g5a-preflight-20261009" in low:
                raise Closed("PRODUCTION_IO_DENIED")
    sys.addaudithook(audit)
    sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))
    sys.path.insert(0, str(ROOT / "backend/tests"))
    import g3_offline_guard
    g3_offline_guard.install()


def kernel():
    k = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "GetProcessTimes": ([W.HANDLE, C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME)], W.BOOL),
        "QueryFullProcessImageNameW": ([W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
        "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        "AssignProcessToJobObject": ([W.HANDLE, W.HANDLE], W.BOOL),
        "QueryInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
        "CloseHandle": ([W.HANDLE], W.BOOL),
        "TerminateProcess": ([W.HANDLE, W.UINT], W.BOOL),
        "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(k, name)
        fn.argtypes, fn.restype = args, result
    return k


def identity(k, process) -> dict:
    times = [W.FILETIME() for _ in range(4)]
    path, length = C.create_unicode_buffer(32768), W.DWORD(32768)
    if not k.GetProcessTimes(int(process._handle), *(C.byref(t) for t in times)):
        raise Closed("IDENTITY_UNKNOWN")
    if not k.QueryFullProcessImageNameW(int(process._handle), 0, path, C.byref(length)):
        raise Closed("IDENTITY_UNKNOWN")
    return {"pid": process.pid, "creation_filetime": times[0].dwLowDateTime | times[0].dwHighDateTime << 32,
            "executable": os.path.normcase(path.value)}


def job_pids(k, job) -> list[int]:
    class Pids(C.Structure):
        _fields_ = [("assigned", W.DWORD), ("count", W.DWORD), ("ids", C.c_size_t * 64)]
    result = Pids()
    if not k.QueryInformationJobObject(job, 3, C.byref(result), C.sizeof(result), None):
        raise Closed("TREE_UNKNOWN")
    if result.assigned != result.count or result.count > 64:
        raise Closed("TREE_UNKNOWN")
    return list(result.ids[:result.count])


def load_backup():
    spec = importlib.util.spec_from_file_location("r1c_existing_backup", BACKUP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_receipt(receipt: dict, source: Path, output: Path, verification: dict) -> None:
    expected = {"contract_version": "omi.sqlite-backup.v1", "source": str(source),
                "output": str(output), "integrity_check": "ok", "size_bytes": verification["size_bytes"],
                "sha256": verification["sha256"], "snapshot": verification["snapshot"]}
    if type(receipt) is not dict or any(type(receipt.get(k)) is not type(v) or receipt.get(k) != v for k, v in expected.items()):
        raise Closed("RECEIPT_MISMATCH")
    if verification["quick_check"] != [["ok"]] or verification["snapshot"]["revision"] != REVISION:
        raise Closed("INDEPENDENT_CHECK_FAILED")


def worker(directory: Path, phase: str, scenario: str) -> None:
    # A synthetic fixture safety leash, not a production backup cancellation policy.
    leash = threading.Timer(8, lambda: os._exit(91))
    leash.daemon = True
    leash.start()
    directory = checked_path(directory)
    if sys.stdin.readline().strip() != "GO":
        return
    install_guard(directory)
    source, output = directory / "source.sqlite3", directory / "backup.sqlite3"
    if phase == "leaf":
        time.sleep(1.5)
        return
    if scenario == "orphan" and phase == "copy":
        p = subprocess.Popen([PYTHON, "-B", __file__, "--worker", str(directory), "leaf", scenario],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.DETACHED_PROCESS)
        p.stdin.write(b"GO\n")
        p.stdin.close()
        return
    if phase == "copy" and scenario in {"stall", "deadline", "identity_loss"}:
        (directory / "backup.sqlite3.partial").write_bytes(b"owned partial")
        (directory / "backup.sqlite3.partial-journal").write_bytes(b"owned journal")
        time.sleep(6)
        return
    if phase == "copy" and scenario in {"source_mutation", "wal_mutation"}:
        target = source if scenario == "source_mutation" else Path(str(source) + "-wal")
        before = target.stat() if target.exists() else None
        with target.open("r+b" if before else "wb") as f:
            if before:
                f.seek(-1, 2)
            f.write(b"X")
        if before:
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        time.sleep(6)
        return
    module = load_backup()
    if phase == "copy":
        if scenario == "bogus_success":
            print('{"contract_version":"omi.sqlite-backup.v1"}')
            return
        if scenario in {"verify_delay", "verify_deadline"}:
            original_hash = module._sha256
            def delayed_hash(path):
                time.sleep(0.8 if scenario == "verify_delay" else 6)
                return original_hash(path)
            module._sha256 = delayed_hash
        result = module.backup_sqlite_database(source=source, output=output, integrity_check="quick")
        if scenario == "missing_receipt":
            return
        for name, key, value in (("sha", "sha256", "0" * 64), ("size", "size_bytes", 1),
                                 ("source", "source", "redacted-invalid"), ("output", "output", "redacted-invalid"),
                                 ("contract", "contract_version", "forged")):
            if scenario == "forged_" + name:
                result[key] = value
        if scenario == "forged_revision":
            result["snapshot"]["revision"] = "forged"
        if scenario == "forged_counts":
            result["snapshot"]["counts"] = {}
        if scenario == "corrupt_output":
            output.write_bytes(b"not sqlite")
        print(json.dumps(result), flush=True)
    else:
        if scenario == "independent_deadline":
            time.sleep(6)
        with sqlite3.connect(output.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=0.1) as db:
            db.execute("PRAGMA query_only=ON")
            checks = [list(row) for row in db.execute("PRAGMA quick_check").fetchall()]
            snapshot = module._database_snapshot(db)
        if scenario == "quick_check_extra":
            checks.append(["synthetic corruption"])
        print(json.dumps({"quick_check": checks, "snapshot": snapshot,
                          "size_bytes": output.stat().st_size, "sha256": digest(output)}), flush=True)


def run_child(directory: Path, phase: str, scenario: str, end: float,
              stall: float, original: list, report: dict) -> dict:
    k = kernel()
    job = k.CreateJobObjectW(None, None)
    if not job:
        raise Closed("JOB_UNAVAILABLE")
    process, attested, unknown = None, None, False
    stdout, stderr = directory / (phase + ".json"), directory / (phase + ".jsonl")
    record = {"phase": phase, "cancelled": False, "copy_complete": False}
    report["children"].append(record)
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            process = subprocess.Popen([PYTHON, "-B", __file__, "--worker", str(directory), phase, scenario],
                                       stdin=subprocess.PIPE, stdout=out, stderr=err,
                                       creationflags=subprocess.DETACHED_PROCESS, cwd=ROOT)
            # Child has no domain action until assignment + identity checks succeed.
            attested = identity(k, process)
            if attested["executable"] != os.path.normcase(PYTHON):
                raise Closed("EXECUTABLE_MISMATCH")
            record["identity"] = attested
            if not k.AssignProcessToJobObject(job, int(process._handle)):
                raise Closed("JOB_ASSIGNMENT_FAILED")
            process.stdin.write(b"GO\n")
            process.stdin.close()
            last_forward, lowest, highest = time.monotonic(), math.inf, 0
            while True:
                if time.monotonic() >= end:
                    raise Closed("TOTAL_DEADLINE")
                live = job_pids(k, job)
                if set(live) - {process.pid}:
                    unknown = True
                    record["unclassified_descendants"] = live
                    record["descendant_images"] = []
                    record["descendant_identities"] = []
                    for pid in set(live) - {process.pid}:
                        handle = k.OpenProcess(0x1000, False, pid)
                        if handle:
                            try:
                                observed = identity(k, SimpleNamespace(pid=pid, _handle=handle))
                                record["descendant_identities"].append(observed)
                                record["descendant_images"].append(observed["executable"])
                            except Closed:
                                record["descendant_identity_unknown"] = True
                            finally:
                                k.CloseHandle(handle)
                    raise Closed("ORPHAN_OR_UNCLASSIFIED_CHILD")
                try:
                    current = identity(k, process) if process.poll() is None else attested
                except Closed:
                    try:
                        process.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        unknown = True
                        raise Closed("IDENTITY_UNKNOWN") from None
                    current = attested
                if scenario == "identity_loss" or current != attested:
                    unknown = True
                    raise Closed("IDENTITY_UNKNOWN")
                if fingerprint(directory / "source.sqlite3") != original:
                    raise Closed("SOURCE_CHANGED")
                if stdout.stat().st_size > LIMIT or stderr.stat().st_size > LIMIT:
                    raise Closed("LOG_LIMIT")
                if phase == "copy":
                    for line in stderr.read_text(encoding="utf-8").splitlines():
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("phase") == "backup":
                            remaining = event.get("remaining_pages")
                            if type(remaining) is int and remaining >= 0 and remaining < lowest:
                                lowest, last_forward = remaining, time.monotonic()
                            if remaining == 0 and event.get("sqlite_status") == 101:
                                record["copy_complete"] = True
                    partial = directory / "backup.sqlite3.partial"
                    if partial.exists() and partial.stat().st_size > highest:
                        highest, last_forward = partial.stat().st_size, time.monotonic()
                if process.poll() is not None:
                    if job_pids(k, job):
                        unknown = True
                        raise Closed("ORPHAN_OR_UNCLASSIFIED_CHILD")
                    if process.returncode:
                        raise Closed("CHILD_FAILED")
                    break
                if phase == "copy" and not record["copy_complete"] and time.monotonic() - last_forward >= stall:
                    raise Closed("COPY_STALL")
                time.sleep(0.02)
        try:
            value = json.loads(stdout.read_text(encoding="utf-8"))
        except ValueError:
            raise Closed("MISSING_OR_INVALID_RECEIPT") from None
        if type(value) is not dict:
            raise Closed("MISSING_OR_INVALID_RECEIPT")
        return value
    except BaseException:
        if process is not None and process.poll() is None:
            try:
                if not unknown and attested and identity(k, process) == attested and not (set(job_pids(k, job)) - {process.pid}):
                    # Exact retained HANDLE eliminates PID reuse between check and cancel.
                    if not k.TerminateProcess(int(process._handle), 92):
                        raise Closed("CANCEL_FAILED")
                    record["cancelled"] = True
                else:
                    record["manual_review"] = True
            except (Closed, OSError):
                record["manual_review"] = True
        raise
    finally:
        if process is not None:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()  # EOF releases a worker that never received GO.
            # Separate bounded cleanup reserve. Unknown synthetic children self-expire.
            cleanup_end = time.monotonic() + 9
            while time.monotonic() < cleanup_end:
                try:
                    remaining = job_pids(k, job)
                    empty = not remaining
                except Closed:
                    remaining = None
                    empty = False
                if process.poll() is not None and empty:
                    break
                time.sleep(0.02)
            record["cleanup_confirmed"] = process.poll() is not None and empty
            record["final_job_pids"] = remaining
            record["exit_code"] = process.poll()
            if not record["cleanup_confirmed"]:
                record["manual_review"] = True
        k.CloseHandle(job)


def supervise(directory: Path, source: Path, output: Path, *, scenario="success", total=5.0, stall=1.5) -> dict:
    # All lexical gates run before any file inspection or child creation.
    directory, source, output = map(checked_path, (directory, source, output))
    if source != directory / "source.sqlite3" or output != directory / "backup.sqlite3":
        raise Closed("EXACT_FIXTURE_PATH_REQUIRED")
    if scenario not in SCENARIOS or not all(math.isfinite(n) and 0 < n <= 30 for n in (total, stall)):
        raise Closed("INVALID_BUDGET_OR_SCENARIO")
    start = time.monotonic()
    report = {"contract": "omi.r1c.fixture-supervisor.v1", "scenario": scenario,
              "scope": "DISPOSABLE_ONLY", "status": "FAIL_CLOSED", "children": [],
              "total_budget_seconds": total, "production_adoption": False}
    try:
        original = fingerprint(source)
        marker = json.loads((directory / "fixture.json").read_text(encoding="utf-8"))
        if marker != {"revision": REVISION, "source_sha256": digest(source)}:
            raise Closed("FIXTURE_ATTESTATION_FAILED")
        for suffix in ("", ".partial", ".partial-journal", ".partial-wal", ".partial-shm", "-wal", "-shm"):
            if checked_path(Path(str(output) + suffix)).exists():
                raise Closed("EXISTING_OUTPUT_OR_PARTIAL")
        report["source_before"] = original
        report["backup_script_sha256"] = digest(BACKUP)
        receipt = run_child(directory, "copy", scenario, start + total, stall, original, report)
        if not output.is_file() or Path(str(output) + ".partial").exists():
            raise Closed("PUBLISH_STATE_INVALID")
        if output.stat().st_size > LIMIT:
            raise Closed("FIXTURE_SIZE_LIMIT")
        verification = run_child(directory, "verify", scenario, start + total, stall, original, report)
        validate_receipt(receipt, source, output, verification)
        if fingerprint(source) != original or digest(BACKUP) != report["backup_script_sha256"]:
            raise Closed("SOURCE_OR_SCRIPT_CHANGED")
        if time.monotonic() >= start + total:
            raise Closed("TOTAL_DEADLINE")
        if any(not c.get("cleanup_confirmed") for c in report["children"]):
            raise Closed("CLEANUP_UNKNOWN")
        report.update(status="PASS", receipt=receipt, independent=verification)
    except (Closed, OSError, ValueError) as exc:
        report["failure"] = str(exc) if isinstance(exc, Closed) else type(exc).__name__
    report["elapsed_including_cleanup_seconds"] = round(time.monotonic() - start, 3)
    report["manual_review"] = any(c.get("manual_review") or not c.get("cleanup_confirmed") for c in report["children"])
    write_json(directory / "supervisor.json", report)
    return report


def fresh_fixture() -> Path:
    directory = checked_path(BASE / ("r1c-" + uuid.uuid4().hex))
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.executescript("CREATE TABLE alembic_version(version_num TEXT); CREATE TABLE tw_financial_filing(id INTEGER PRIMARY KEY);")
        db.execute("INSERT INTO alembic_version VALUES (?)", (REVISION,))
        db.execute("INSERT INTO tw_financial_filing VALUES (1)")
    write_json(directory / "fixture.json", {"revision": REVISION, "source_sha256": digest(source)})
    return directory


def rehearse(scenario: str) -> dict:
    directory = fresh_fixture()
    if scenario in {"existing_partial", "journal_existing"}:
        suffix = ".partial" if scenario == "existing_partial" else ".partial-journal"
        (directory / ("backup.sqlite3" + suffix)).write_bytes(b"preserve exactly")
    total = 1.5 if scenario in {"deadline", "verify_deadline", "independent_deadline"} else 5.0
    stall = 0.5 if scenario in {"stall", "verify_delay", "verify_deadline"} else 3.0
    result = supervise(directory, directory / "source.sqlite3", directory / "backup.sqlite3",
                       scenario=scenario, total=total, stall=stall)
    return {"directory": str(directory), **result}


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rehearse", choices=SCENARIOS, required=True)
    args = parser.parse_args()
    result = rehearse(args.rehearse)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
