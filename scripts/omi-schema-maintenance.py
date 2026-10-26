"""OMI inspector plus private Launcher-owned ApplyStopped worker.

Plan/Gate never grant authority. ApplyStopped accepts only a birth-bound stdin
channel from the retained Launcher session; no stop receipt import or public Apply.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import importlib.util
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if sys.argv[1:2] in (["ApplyStopped"], ["CheckStart"]):
    # Fixed base interpreter, -I -S; only this checkout's dependency environment.
    sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))
sys.path.insert(0, str(ROOT / "backend"))

from app.db.migrations import get_head_revision, inspect_database_schema


LIMITATIONS = [
    "Backend exit releases its lease; exclusion is reacquired, not transferred",
    "External writes committed before BEGIN IMMEDIATE are included in backup",
    "SQLite writers excluded only while maintenance reservation is held",
    "External readers allowed; rollback-journal readers may prevent commit",
    "After commit external writers may resume before successor readiness",
    "No protection against non-SQLite file writes or privileged interference",
    "No automatic restore, downgrade, retry or duplicate successor",
]


def _backup_module():
    spec = importlib.util.spec_from_file_location("omi_sqlite_backup", ROOT / "scripts/backup-omi-sqlite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def maintenance_source_id():
    paths = [ROOT / "scripts/omi-schema-maintenance.py", ROOT / "scripts/backup-omi-sqlite.py"]
    paths += list((ROOT / "backend/app").rglob("*.py"))
    paths += list((ROOT / "backend/alembic").rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: value.as_posix()):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def apply_stopped(*, database: Path, schema_lock_path: Path, backup_path: Path,
                  receipt_path: Path, request_id: str, expected_source: str | None = None) -> dict:
    """Private worker implementation, also exercised with disposable fixtures.

    Lifecycle authority is checked by ProductionSession before spawning this
    worker. This function cannot stop/start processes or consume old receipts.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from sqlalchemy.pool import NullPool
    from alembic.runtime.migration import MigrationContext
    from app.db.migrations import run_database_migrations
    from app.db.quiescence import SQLiteWriterLease
    from app.runtime_lock import ProcessFileLock

    UUID(request_id)
    receipt = dict(contract="omi.schema-apply.v1", request_id=request_id, status="UNKNOWN",
                   phase="INTENT", sequence=0, retry_allowed=False,
                   backup="NOT_ATTEMPTED", migration="NOT_ATTEMPTED", startup="OWNER_ONLY",
                   limitations=LIMITATIONS, frontend_interrupted=False)
    try:
        stream = receipt_path.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        return apply_status(receipt_path)  # Existing intent is never executed again.
    def persist(phase, **changes):
        receipt.update(changes, phase=phase, sequence=receipt["sequence"] + 1,
                       updated_at=datetime.now(timezone.utc).isoformat())
        stream.write(json.dumps(receipt, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    lock = ProcessFileLock(schema_lock_path)
    engine = connection = lease = None
    committed = False
    with stream:
        try:
            persist("INTENT")
            for path in (database, schema_lock_path, backup_path, receipt_path):
                if not path.is_absolute():
                    raise RuntimeError("ABSOLUTE_PATH_REQUIRED")
                for part in (path, *path.parents):
                    if part.exists() and (part.is_symlink() or getattr(part.stat(), "st_file_attributes", 0) & 0x400):
                        raise RuntimeError("PATH_ALIAS_REFUSED")
            if schema_lock_path.name != "schema.lock":
                raise RuntimeError("CANONICAL_SCHEMA_LOCK_REQUIRED")
            source_id = maintenance_source_id()
            if expected_source is not None and source_id != expected_source:
                raise RuntimeError("MAINTENANCE_SOURCE_OR_LEASE_CHANGED")
            if not lock.acquire():
                raise RuntimeError("SCHEMA_LOCK_BUSY")
            # Connect before lease: SQLAlchemy's initial dialect setup rolls back.
            engine = create_engine(URL.create("sqlite+pysqlite", database=database.as_uri(),
                                   query={"mode": "rw", "uri": "true"}),
                                   connect_args={"timeout": 0}, poolclass=NullPool)
            connection = engine.connect()
            lease = SQLiteWriterLease.acquire(URL.create("sqlite", database=str(database)), connection=connection)
            # A future Alembic autocommit_block must fail, never briefly release
            # writer exclusion and then appear transactional again.
            connection.connection.driver_connection.set_authorizer(
                lambda action, arg1, arg2, db, trigger: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_TRANSACTION and arg1 in {"COMMIT", "ROLLBACK"}
                else sqlite3.SQLITE_OK)
            persist("EXCLUSIVE", exclusion="schema.lock+BEGIN_IMMEDIATE", continuous_from_backend=False)
            before = MigrationContext.configure(connection).get_current_revision()
            from alembic.script import ScriptDirectory
            from app.db.migrations import create_alembic_config
            graph = ScriptDirectory.from_config(create_alembic_config("sqlite://"))
            if before not in {r.revision for r in graph.walk_revisions()} or before == graph.get_current_head():
                raise RuntimeError("KNOWN_BEHIND_REVISION_REQUIRED")
            persist("BACKUP", before_revision=before, target_revision=graph.get_current_head(), backup="RUNNING")
            backup = _backup_module()
            proof = backup.backup_sqlite_database(source=database, output=backup_path,
                                                  integrity_check="full", max_seconds=120)
            if backup._database_snapshot(connection.connection.driver_connection) != proof["snapshot"]:
                raise RuntimeError("BACKUP_SOURCE_MISMATCH")
            # Independent restore COPY only; the source database is never replaced.
            restored = backup_path.with_name(backup_path.name + ".restore-check")
            restore_deadline = time.monotonic() + 120
            with backup_path.open("rb") as src, restored.open("xb") as dst:
                for block in iter(lambda: src.read(8 * 1024 * 1024), b""):
                    backup._check_deadline(restore_deadline)
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
            if backup._sha256(restored, deadline=restore_deadline) != proof["sha256"]:
                raise RuntimeError("RESTORE_COPY_HASH_MISMATCH")
            restored_db = sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True, timeout=0)
            try:
                restored_db.set_progress_handler(lambda: int(time.monotonic() >= restore_deadline), 1000)
                if (restored_db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or
                        backup._database_snapshot(restored_db) != proof["snapshot"]):
                    raise RuntimeError("RESTORE_COPY_CHECK_FAILED")
            finally:
                restored_db.close()
            proof["restore_copy"] = str(restored)
            proof["restore_verified"] = True
            proof["maintenance_reservation"] = "BEGIN_IMMEDIATE"
            persist("BACKUP_VERIFIED", backup=proof)
            if not lease.held or maintenance_source_id() != source_id:
                raise RuntimeError("MAINTENANCE_SOURCE_OR_LEASE_CHANGED")
            persist("MIGRATING", migration="RUNNING")
            deadline = time.monotonic() + 120
            connection.connection.driver_connection.set_progress_handler(
                lambda: int(time.monotonic() >= deadline), 1000)
            run_database_migrations(connection=connection)
            if connection.exec_driver_sql("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("MIGRATION_INTEGRITY_FAILED")
            if not lease.held or maintenance_source_id() != source_id:
                raise RuntimeError("MAINTENANCE_SOURCE_OR_LEASE_CHANGED")
            after = MigrationContext.configure(connection).get_current_revision()
            persist("COMMITTING", migration="VERIFIED_UNCOMMITTED", after_revision=after)
            connection.connection.driver_connection.set_authorizer(None)
            connection.commit()  # Only this owner commits; busy readers fail, no retry.
            committed = True
            persist("COMMITTED", status="SUCCEEDED", migration="COMMITTED")
        except Exception as exc:
            phase = receipt["phase"]
            # No exception text/SQL/parameters/connection strings in receipts.
            known_codes = {
                "ABSOLUTE_PATH_REQUIRED", "PATH_ALIAS_REFUSED", "CANONICAL_SCHEMA_LOCK_REQUIRED",
                "SCHEMA_LOCK_BUSY", "KNOWN_BEHIND_REVISION_REQUIRED", "BACKUP_SOURCE_MISMATCH",
                "RESTORE_COPY_HASH_MISMATCH", "RESTORE_COPY_CHECK_FAILED",
                "MAINTENANCE_SOURCE_OR_LEASE_CHANGED", "MIGRATION_INTEGRITY_FAILED",
                "MIGRATION_TRANSACTION_OR_HEAD_LOST", "SQLITE_TARGET_UNSUPPORTED", "SQLITE_TARGET_ALIAS",
                "SQLITE_TARGET_NOT_LOCAL_FIXED_DISK", "MAINTENANCE_CONNECTION_TARGET_MISMATCH",
                "US_EOD_OBLIGATION_INDEX_DEFINITION_MISMATCH",
            }
            error_code = str(exc) if isinstance(exc, RuntimeError) and str(exc) in known_codes else "SCHEMA_MAINTENANCE_FAILED"
            persist("FAILED", status="FAILED" if not committed else "UNKNOWN", failed_phase=phase,
                    error_type=type(exc).__name__, error_code=error_code,
                    migration="COMMITTED" if committed else (
                        "FAILED_TRANSACTION_REQUIRES_INSPECTION" if phase in {"MIGRATING", "COMMITTING"}
                        else "NOT_ATTEMPTED"))
        finally:
            if lease is not None:
                connection.connection.driver_connection.set_authorizer(None)
                lease.release()
            if connection is not None:
                connection.close()
            if engine is not None:
                engine.dispose()
            lock.release()
    return receipt


def apply_status(path: Path, *, contract="omi.schema-apply.v1"):
    try:
        if path.stat().st_size > 262144:
            raise ValueError()
        raw = path.read_text(encoding="utf-8")
        if len(raw) > 262144 or not raw.endswith("\n"):
            raise ValueError()
        rows = [json.loads(line) for line in raw.splitlines()]
        for number, row in enumerate(rows, 1):
            if (row["contract"] != contract or row["sequence"] != number or
                    row["retry_allowed"] is not False or row["request_id"] != rows[0]["request_id"]):
                raise ValueError()
        UUID(rows[0]["request_id"])
        return rows[-1]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return dict(status="UNKNOWN", retry_allowed=False, error_code="RECEIPT_UNREADABLE_OR_INCOMPLETE")


def owner_worker() -> int:
    """Private inherited pipe. Not a CLI authority or a receipt-based unlock."""
    result = {"status": "UNKNOWN", "request_id": "", "nonce": ""}
    try:
        from app.owned_uvicorn import creation
        line = sys.stdin.readline(16385)
        if not line.endswith("\n") or len(line) > 16384:
            raise ValueError("OWNER_FRAME_INVALID")
        boot = json.loads(line)
        if (boot.get("action") != "ApplyStopped" or boot["launcher_pid"] != str(os.getppid()) or
                creation(os.getppid()) != boot["launcher_created"] or
                len(boot["nonce"]) != 64):
            raise ValueError("OWNER_CHANNEL_MISMATCH")
        _attest_launcher_parent(ROOT / "scripts/omi-launcher.ps1", "OpenMarketIntelligenceLauncher")
        result.update(request_id=boot["request_id"], nonce=boot["nonce"])
        challenge = os.urandom(32).hex()
        print(json.dumps(dict(result, state="CHALLENGE", challenge=challenge)), flush=True)
        authorization = json.loads(sys.stdin.readline(16385))
        if authorization != {"request_id": boot["request_id"], "nonce": boot["nonce"],
                             "challenge": challenge, "action": "GO"}:
            raise ValueError("OWNER_CAPABILITY_NOT_CONSUMED")
        _attest_launcher_parent(ROOT / "scripts/omi-launcher.ps1", "OpenMarketIntelligenceLauncher")
        # Settings are read only in the explicitly authorized worker, never Plan
        # or fixture Apply. No URL or settings object is serialized/logged.
        from app.config import settings
        from sqlalchemy.engine import make_url
        target = make_url(settings.database_url)
        database, lock = Path(boot["database"]), Path(boot["schema_lock"])
        if (target.drivername not in {"sqlite", "sqlite+pysqlite"} or target.query or
                target.username or target.password or target.host or not target.database or
                Path(target.database) != database or settings.runtime_lock_dir / "schema.lock" != lock):
            raise ValueError("CONFIGURED_TARGET_MISMATCH")
        receipt = apply_stopped(database=database, schema_lock_path=lock,
                               backup_path=Path(boot["backup"]), receipt_path=Path(boot["receipt"]),
                               request_id=boot["request_id"], expected_source=boot["source_release"])
        result.update(status=receipt["status"], migration=receipt["migration"])
    except Exception as exc:
        result.update(error_type=type(exc).__name__)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "SUCCEEDED" else 2


def _attest_launcher_parent(expected_script: Path, mutex_name: str):
    """Read OS process image/command line and actual mutant owner, not JSON claims.

    Windows only. Unknown access/native evidence fails closed. The fixed caller
    passes canonical Launcher constants; parameters permit disposable OS fixtures.
    """
    import ctypes
    from ctypes import wintypes as w
    if os.name != "nt":
        raise RuntimeError("WINDOWS_LAUNCHER_REQUIRED")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.OpenMutexW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
    kernel.OpenMutexW.restype = w.HANDLE
    kernel.LocalFree.argtypes = [w.HLOCAL]
    ntdll.NtQueryInformationProcess.argtypes = [w.HANDLE, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
    ntdll.NtQueryMutant.argtypes = [w.HANDLE, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
    shell.CommandLineToArgvW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(w.LPWSTR)
    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT), ("Buffer", ctypes.c_void_p)]
    class MutantOwner(ctypes.Structure):
        _fields_ = [("process", ctypes.c_void_p), ("thread", ctypes.c_void_p)]
    parent = kernel.OpenProcess(0x1000, False, os.getppid())
    if not parent:
        raise RuntimeError("LAUNCHER_PROCESS_UNVERIFIED")
    mutex = None
    try:
        size = w.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(parent, 0, image, ctypes.byref(size)):
            raise RuntimeError("LAUNCHER_IMAGE_UNVERIFIED")
        # GetWindowsDirectory is an OS fact, not a caller-controlled env variable.
        windows = ctypes.create_unicode_buffer(32768)
        if not kernel.GetWindowsDirectoryW(windows, len(windows)):
            raise RuntimeError("WINDOWS_DIRECTORY_UNVERIFIED")
        fixed = Path(windows.value) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if Path(image.value) != fixed:
            raise RuntimeError("FIXED_LAUNCHER_EXECUTABLE_REQUIRED")
        needed = w.ULONG()
        ntdll.NtQueryInformationProcess(parent, 60, None, 0, ctypes.byref(needed))
        if not 0 < needed.value <= 65536:
            raise RuntimeError("LAUNCHER_COMMAND_LINE_UNVERIFIED")
        buffer = ctypes.create_string_buffer(needed.value)
        if ntdll.NtQueryInformationProcess(parent, 60, buffer, needed, ctypes.byref(needed)) != 0:
            raise RuntimeError("LAUNCHER_COMMAND_LINE_UNVERIFIED")
        value = UnicodeString.from_buffer(buffer)
        command = ctypes.wstring_at(value.Buffer, value.Length // 2)
        count = ctypes.c_int()
        args = shell.CommandLineToArgvW(command, ctypes.byref(count))
        if not args:
            raise RuntimeError("LAUNCHER_COMMAND_LINE_UNVERIFIED")
        try:
            tokens = [args[i] for i in range(count.value)]
        finally:
            kernel.LocalFree(ctypes.cast(args, w.HLOCAL))
        lower = [t.lower() for t in tokens]
        if lower.count("-file") != 1:
            raise RuntimeError("FIXED_LAUNCHER_SCRIPT_REQUIRED")
        offset = lower.index("-file")
        if ("-noprofile" not in lower[:offset] or offset + 1 >= len(tokens) or Path(tokens[offset + 1]) != expected_script or
                any(t in lower[:offset] for t in ("-command", "-encodedcommand", "-c", "-ec"))):
            raise RuntimeError("FIXED_LAUNCHER_SCRIPT_REQUIRED")
        # PowerShell accepts abbreviated switches: a denylist alone would allow
        # -co '<attacker code>' followed by decoy -File tokens. Accept only the
        # actual fixed hidden launcher's invocation grammar (plus harmless flags).
        position = 1
        while position < offset:
            token = lower[position]
            if token in {"-noprofile", "-sta", "-nologo", "-noninteractive"}:
                position += 1
            elif (token in {"-executionpolicy", "-windowstyle"} and position + 1 < offset and
                  lower[position + 1] == {"-executionpolicy": "bypass", "-windowstyle": "hidden"}[token]):
                position += 2
            else:
                raise RuntimeError("FIXED_LAUNCHER_INVOCATION_REQUIRED")
        if lower[offset + 2:] not in ([], ["-launcheraction", "run"]):
            raise RuntimeError("FIXED_LAUNCHER_INVOCATION_REQUIRED")
        mutex = kernel.OpenMutexW(0x0001, False, mutex_name)  # MUTANT_QUERY_STATE
        owner = MutantOwner()
        if (not mutex or ntdll.NtQueryMutant(mutex, 1, ctypes.byref(owner), ctypes.sizeof(owner), None) != 0
                or owner.process != os.getppid()):
            raise RuntimeError("LAUNCHER_MUTEX_OWNER_UNVERIFIED")
    finally:
        if mutex:
            kernel.CloseHandle(mutex)
        kernel.CloseHandle(parent)


BLOCKERS = ["EXPLICIT_LAUNCHER_SCHEMA_ACTION_REQUIRED", "RUNTIME_ADOPTION_UNVERIFIED"]
HANDOFF = (
    "Run Plan with the operator-confirmed absolute database path and, when available, "
    "the selected loopback Backend URL. Preserve failed-start and maintenance receipts. "
    "Do not run Restart, Apply Update, raw Alembic, restore or downgrade to clear this gate. "
    "Use the source-adopted original Launcher tray Upgrade DB Schema action after explicit "
    "operator authorization. It admits graceful exact stop or attested failed-start exit, "
    "then reacquires SQLite exclusion for backup/migration and starts one successor. "
    "Source fixtures are not live adoption. Loading a new Launcher may separately require "
    "authorized Frontend downtime; never silently use Apply Update."
)


def read_runtime(base_url: str) -> dict:
    """Public observations only; no auth, proxy, redirects, refresh or retry."""
    url = urlsplit(base_url)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
            or url.username or url.password or url.query or url.fragment
            or url.path not in {"", "/"} or url.port is None):
        raise ValueError("EXPLICIT_LOOPBACK_BACKEND_URL_REQUIRED")
    results = {}
    for name, route in (("health", "health"), ("control", "runtime-control/status"),
                        ("readyz", "readyz")):
        # HTTPConnection has no proxy, netrc, redirect, auth or retry machinery.
        client = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
        try:
            client.request("GET", "/api/system/" + route)
            response = client.getresponse()
            if response.status != 200:
                raise ValueError("RUNTIME_RESPONSE_NOT_OK")
            content = response.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ValueError("RUNTIME_RESPONSE_TOO_LARGE")
            value = json.loads(content)
            results[name] = value if isinstance(value, dict) else {}
        except (OSError, http.client.HTTPException, ValueError):
            results[name] = {}
        finally:
            client.close()
    return results


def runtime_summary(observed: dict, database: Path | None) -> dict:
    """Whitelist diagnostic fields; never serialize a whole health response."""
    health = observed.get("health", {}).get("runtime", {})
    control = observed.get("control", {})
    binding = health.get("database_binding", {})
    backend = control.get("backend", {})
    owned = control.get("serving_backend", {}).get("owned_start", {})
    target_hash = None if database is None else hashlib.sha256(
        os.path.normcase(os.path.normpath(str(database))).encode("utf-8")
    ).hexdigest()
    target_matches = bool(
        target_hash and binding.get("diagnostic_contract") == "omi.engine-binding.v1"
        and binding.get("target", {}).get("kind") == "sqlite_absolute_path"
        and binding.get("target", {}).get("path_sha256") == target_hash
        and all(binding.get(key) is True for key in
                ("engine_object_unchanged", "engine_url_unchanged", "settings_match_engine_url"))
        and isinstance(binding.get("pid"), int) and binding["pid"] > 0
        and str(binding["pid"]) == str(backend.get("pid")) == str(owned.get("child_pid"))
        and control.get("application_release_id")
        and control["application_release_id"] == owned.get("release_id")
        and health.get("project_root")
        and os.path.normcase(os.path.normpath(health["project_root"])) == os.path.normcase(str(ROOT))
    )
    return {
        "observation": "OBSERVED" if control.get("owner_id") else "UNVERIFIED",
        "owner_id": control.get("owner_id"),
        "launcher_pid": control.get("launcher", {}).get("pid"),
        "backend_pid": backend.get("pid"),
        "application_release": control.get("application_release_id"),
        "loaded_lifecycle": control.get("loaded_lifecycle_source_id"),
        "runtime_started": control.get("serving_backend", {}).get("runtime_started"),
        "readyz_status": observed.get("readyz", {}).get("status"),
        "restart_available": control.get("restart", {}).get("available"),
        "database_configuration_match": target_matches,
        "database_handle_binding": "UNVERIFIED",
        "maintenance_owner": "UNVERIFIED",
    }


def plan(database: Path | None = None, *, base_url: str | None = None,
         check_integrity: bool = False) -> dict:
    runtime = runtime_summary(read_runtime(base_url) if base_url else {}, database)
    schema = {"current": None, "head": get_head_revision(), "state": "DB_UNKNOWN",
              "migration_needed": None, "reason": "EXPLICIT_DATABASE_PATH_REQUIRED"}
    if database is not None:
        if base_url and not runtime["database_configuration_match"]:
            schema["reason"] = "LOADED_DATABASE_CONFIGURATION_NOT_MATCHED"
        else:
            schema = inspect_database_schema(database, check_integrity=check_integrity)
    return {
        "contract": "omi.schema-maintenance.v1", "action": "Plan", "status": "BLOCKED",
        "implementation": "LAUNCHER_APPLY_STOPPED_SOURCE", "adoption": "UNVERIFIED",
        "database_path": str(database) if database else None,
        "path_basis": "operator_supplied_no_default_no_dotenv",
        "schema": schema, "runtime": runtime, "safe_to_apply": False,
        "blockers": list(BLOCKERS), "frontend_interrupted": False,
        "stop_scope": "Plan: NONE; explicit Launcher action: BACKEND_ONLY",
        "apply_update_scope": "Existing Apply Update may stop Backend AND Frontend; not a migration entry",
        "handoff": HANDOFF,
    }


def start_compatibility(*, database_url: str, lock_path: Path, database: Path | None = None,
                        schema_lock: Path | None = None, upgrade: bool = False,
                        base_url: str | None = None) -> dict:
    """Read-only pre-stop gate; paths are locally configured, never pipe inputs.

    A head match is not all-writer exclusion or permission to migrate. The worker
    still owns backup, schema lock, reservation and Alembic transaction.
    """
    from sqlalchemy.engine import make_url
    target = make_url(database_url)
    result = dict(contract="omi.start-compatibility.v1", compatible=False,
                  reason="CONFIGURED_TARGET_MISMATCH", backend_pid=None, owner_id=None)
    if (target.drivername not in {"sqlite", "sqlite+pysqlite"} or target.query or
            target.username or target.password or target.host or not target.database):
        return result
    configured = Path(target.database)
    if (not configured.is_absolute() or (database is not None and database != configured) or
            (schema_lock is not None and schema_lock != lock_path) or
            not lock_path.is_absolute() or lock_path.name != "schema.lock"):
        return result
    for path in (configured, lock_path):
        if path.resolve() != path:
            return result
        for part in (path, *path.parents):
            if part.exists() and (part.is_symlink() or getattr(part.stat(), "st_file_attributes", 0) & 0x400):
                return result
    observation = plan(configured, base_url=base_url)
    schema = observation["schema"]
    runtime = observation["runtime"]
    compatible = schema["state"] == ("DB_BEHIND" if upgrade else "DB_AT_HEAD")
    if base_url:
        compatible = compatible and runtime["database_configuration_match"]
    return dict(result, compatible=bool(compatible),
                reason="COMPATIBLE" if compatible else "SCHEMA_OR_BINDING_INCOMPATIBLE",
                backend_pid=runtime["backend_pid"], owner_id=runtime["owner_id"],
                configured_target=({"database_path": str(configured), "schema_lock_path": str(lock_path)}
                                   if upgrade and compatible else None),
                schema_generation={key: schema.get(key) for key in ("current", "head", "schema_sha256")})


def receipt_status(path: Path) -> dict:
    try:
        # A torn last record is UNKNOWN, never permission to replay a request.
        with path.open(encoding="utf-8") as stream:
            content = stream.read(65537)
        if len(content) > 65536 or not content.endswith("\n"):
            raise ValueError("INVALID_RECEIPT")
        lines = content.splitlines()
        records = [json.loads(line) for line in lines]
        if len(records) not in {1, 2} or any(record.get("contract") != "omi.schema-maintenance.v1"
                              or record.get("action") != "Gate"
                              or record.get("retry_allowed") is not False
                              or record.get("request_id") != records[0].get("request_id")
                              for record in records):
            raise ValueError("INVALID_RECEIPT")
        UUID(records[0]["request_id"])
        if [record.get("status") for record in records] not in (["UNKNOWN"], ["UNKNOWN", "BLOCKED"]):
            raise ValueError("INVALID_RECEIPT")
        return records[-1]
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        return {"status": "UNKNOWN", "reason": "RECEIPT_UNREADABLE_OR_INCOMPLETE",
                "retry_allowed": False, "handoff": HANDOFF}


def record_gate(path: Path) -> dict:
    """Persist intent BEFORE any work. Existing intent is read, never replayed.

    Deliberately no DB path, authority booleans, stop hooks or migration callbacks.
    A new CLI invocation cannot convert old UNKNOWN into execution authority.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "contract": "omi.schema-maintenance.v1", "request_id": str(uuid4()),
        "action": "Gate", "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "UNKNOWN", "phase": "INTENT_RECORDED", "retry_allowed": False,
        "backup": "NOT_ATTEMPTED", "migration": "NOT_ATTEMPTED",
        "startup": "NOT_ATTEMPTED", "frontend_interrupted": False,
        "adoption": "ADOPTION_BLOCKED", "handoff": HANDOFF,
    }
    try:
        stream = path.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        return receipt_status(path)
    with stream:
        def persist():
            stream.write(json.dumps(receipt, ensure_ascii=True, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        persist()
        receipt.update(status="BLOCKED", phase="MAINTENANCE_GATE", blockers=list(BLOCKERS))
        persist()
    return receipt


def main(argv=None) -> int:
    if (sys.argv[1:] if argv is None else argv) == ["ApplyStopped"]:
        return owner_worker()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("Plan", "Gate", "Status", "CheckStart"))
    parser.add_argument("--schema-lock-path", type=Path)
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--database-path", type=Path,
                        help="Explicit operator-confirmed absolute path; never inferred from .env")
    parser.add_argument("--base-url", help="Explicit selected loopback Backend URL; GET diagnostics only")
    parser.add_argument("--check-integrity", action="store_true", help="Plan: bounded read-only quick_check")
    parser.add_argument("--receipt", type=Path, help="Gate/Status: one durable JSONL receipt; never overwritten")
    args = parser.parse_args(argv)
    if args.action != "CheckStart" and (args.schema_lock_path or args.upgrade):
        parser.error("schema-lock-path/upgrade are CheckStart-only")
    if args.action not in {"Plan", "CheckStart"} and (args.database_path or args.base_url or args.check_integrity):
        parser.error("database/runtime options are Plan-only; ApplyStopped is a private owner channel")
    if args.action == "Plan" and args.receipt:
        parser.error("Plan prints observations only; receipt is Gate/Status-only")
    receipt = None
    try:
        if args.action == "CheckStart":
            if args.receipt or args.check_integrity:
                parser.error("CheckStart does not accept receipts or integrity work")
            from app.config import settings
            result = start_compatibility(database_url=settings.database_url,
                                         lock_path=settings.runtime_lock_dir / "schema.lock",
                                         database=args.database_path, schema_lock=args.schema_lock_path,
                                         upgrade=args.upgrade, base_url=args.base_url)
        elif args.action == "Plan":
            result = plan(args.database_path, base_url=args.base_url, check_integrity=args.check_integrity)
        else:
            if args.action == "Status" and args.receipt is None:
                parser.error("Status requires --receipt")
            receipt = args.receipt or ROOT / "logs" / "schema-maintenance" / (str(uuid4()) + ".jsonl")
            result = record_gate(receipt) if args.action == "Gate" else receipt_status(receipt)
            if args.action == "Status" and result.get("status") == "UNKNOWN":
                result = apply_status(receipt)
                if result.get("contract") != "omi.schema-apply.v1":
                    result = apply_status(receipt, contract="omi.schema-operation.v1")
            result = dict(result, receipt_path=str(receipt))
    except Exception as exc:
        result = {"status": "UNKNOWN", "error_type": type(exc).__name__,
                  "retry_allowed": False, "handoff": HANDOFF,
                  "receipt_path": str(receipt) if receipt else None}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    if args.action == "CheckStart":
        return 0 if result.get("compatible") is True else 2
    return 0 if args.action == "Status" and result.get("status") == "SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
