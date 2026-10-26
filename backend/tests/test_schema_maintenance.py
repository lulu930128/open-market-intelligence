"""Offline inspector, gate, and concrete counterexamples to unsafe handoff."""
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest
from sqlalchemy.engine import make_url

from app.db import migrations
from app.db.quiescence import SQLiteWriterLease
from app.runtime_lock import ProcessFileLock

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maintenance = load_script("omi-schema-maintenance")
backup = load_script("backup-omi-sqlite")


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "fixture #1.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version(version_num TEXT NOT NULL)")
        db.execute("INSERT INTO alembic_version VALUES ('20261009_0092')")
        db.execute("CREATE TABLE us_daily_price(id INTEGER PRIMARY KEY, trade_volume BIGINT)")
        db.execute("INSERT INTO us_daily_price VALUES (1, 123)")
    return path


@pytest.mark.parametrize("revision,state,needed", [
    ("HEAD", "DB_AT_HEAD", False), ("20261009_0092", "DB_BEHIND", True),
    ("20990101_future", "DB_AHEAD_OR_UNKNOWN", None),
    ("not-a-revision", "DB_AHEAD_OR_UNKNOWN", None),
])
def test_read_only_revision_classification(database, revision, state, needed):
    revision = migrations.get_head_revision() if revision == "HEAD" else revision
    with sqlite3.connect(database) as db:
        db.execute("UPDATE alembic_version SET version_num=?", (revision,))
    before = database.read_bytes()
    result = maintenance.plan(database, check_integrity=True)
    assert result["schema"]["state"] == state
    assert result["schema"]["migration_needed"] is needed
    assert result["schema"]["integrity"] == "ok"
    assert result["schema"]["schema_validation"] == "UNVERIFIED"
    assert not result["safe_to_apply"]
    assert database.read_bytes() == before


@pytest.mark.parametrize("kind", ["missing", "multiple", "empty", "corrupt"])
def test_unknown_database_is_not_repaired(database, kind):
    if kind == "missing":
        database = database.parent / "missing.db"
    elif kind == "corrupt":
        database.write_bytes(b"not SQLite")
    else:
        with sqlite3.connect(database) as db:
            if kind == "multiple":
                db.execute("INSERT INTO alembic_version VALUES ('another')")
            else:
                db.execute("DELETE FROM alembic_version")
    before = database.read_bytes() if database.exists() else None
    assert maintenance.plan(database)["schema"]["state"] == "DB_UNKNOWN"
    assert (database.read_bytes() if database.exists() else None) == before


def test_source_plan_never_loads_settings_or_opens_database(monkeypatch):
    original = builtins.__import__
    def forbidden_settings(name, *args, **kwargs):
        assert name != "app.config", "inspection must not read dotenv"
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", forbidden_settings)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("unexpected DB IO"))
    assert maintenance.plan()["schema"]["reason"] == "EXPLICIT_DATABASE_PATH_REQUIRED"


def observed_runtime(database):
    return {
        "health": {"runtime": {"project_root": str(ROOT), "database_binding": {
            "diagnostic_contract": "omi.engine-binding.v1", "pid": 123,
            "target": {"kind": "sqlite_absolute_path", "path_sha256": hashlib.sha256(
                os.path.normcase(os.path.normpath(str(database))).encode()).hexdigest()},
            "engine_object_unchanged": True, "engine_url_unchanged": True,
            "settings_match_engine_url": True}}},
        "control": {"owner_id": "fixture", "backend": {"pid": 123},
                    "application_release_id": "fixture-release", "loaded_lifecycle_source_id": "fixture-source",
                    "serving_backend": {"runtime_started": True,
                                        "owned_start": {"child_pid": "123", "release_id": "fixture-release"}}},
        "readyz": {"status": "ready"},
    }


def test_runtime_match_is_configuration_only(database, monkeypatch):
    monkeypatch.setattr(maintenance, "read_runtime", lambda _: observed_runtime(database))
    result = maintenance.plan(database, base_url="http://127.0.0.1:8400")
    assert result["runtime"]["database_configuration_match"]
    assert result["runtime"]["application_release"] == "fixture-release"
    assert result["runtime"]["maintenance_owner"] == "UNVERIFIED"
    assert result["schema"]["state"] == "DB_BEHIND"
    assert result["status"] == "BLOCKED"


@pytest.mark.parametrize("mismatch", ["pid", "checkout", "release", "unavailable"])
def test_runtime_mismatch_prevents_db_read(database, monkeypatch, mismatch):
    observed = observed_runtime(database)
    if mismatch == "pid":
        observed["control"]["backend"]["pid"] = 999
    elif mismatch == "checkout":
        observed["health"]["runtime"]["project_root"] = str(database.parent)
    elif mismatch == "release":
        observed["control"]["application_release_id"] = "other-release"
    else:
        observed = {}
    monkeypatch.setattr(maintenance, "read_runtime", lambda _: observed)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("must not open DB"))
    result = maintenance.plan(database, base_url="http://127.0.0.1:8400")
    assert result["schema"]["reason"] == "LOADED_DATABASE_CONFIGURATION_NOT_MATCHED"


@pytest.mark.parametrize("url", ["http://example.com", "http://localhost:8400", "https://127.0.0.1:8400",
                                 "http://user:secret@127.0.0.1:8400", "http://127.0.0.1:8400/path"])
def test_runtime_rejects_nonlocal_or_credential_urls(url):
    with pytest.raises(ValueError):
        maintenance.read_runtime(url)


def test_gate_has_no_database_or_lifecycle_effects_and_never_replays(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("gate cannot open DB"))
    monkeypatch.setattr(maintenance, "read_runtime", lambda _: pytest.fail("gate cannot call runtime"))
    path = tmp_path / "maintenance.jsonl"
    result = maintenance.record_gate(path)
    assert result["status"] == "BLOCKED"
    assert result["backup"] == result["migration"] == result["startup"] == "NOT_ATTEMPTED"
    assert not result["frontend_interrupted"]
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["status"] for record in records] == ["UNKNOWN", "BLOCKED"]
    before = path.read_bytes()
    assert maintenance.record_gate(path) == result
    assert path.read_bytes() == before


@pytest.mark.parametrize("content", ["{", "", '[1]\n',
    '{"contract":"omi.schema-maintenance.v1","request_id":"x","status":"UNKNOWN","retry_allowed":false}\n'])
def test_unknown_receipt_is_preserved(tmp_path, content):
    path = tmp_path / "receipt.jsonl"
    path.write_text(content)
    assert maintenance.record_gate(path)["status"] == "UNKNOWN"
    assert path.read_text() == content


def test_no_fake_apply_command(tmp_path):
    with pytest.raises(SystemExit) as caught:
        maintenance.main(["Apply", "--receipt", str(tmp_path / "unused.jsonl")])
    assert caught.value.code == 2
    assert not (tmp_path / "unused.jsonl").exists()


def test_schema_lock_is_not_a_writer_or_other_checkout_fence(database, tmp_path):
    first = ProcessFileLock(tmp_path / "checkout-a" / "schema.lock")
    second = ProcessFileLock(tmp_path / "checkout-b" / "schema.lock")
    try:
        assert first.acquire() and second.acquire()
        with sqlite3.connect(database, timeout=0) as writer:
            writer.execute("UPDATE us_daily_price SET trade_volume=124")
    finally:
        first.release()
        second.release()


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_writer_lease_blocks_second_writer_but_not_connections(database, journal_mode):
    with sqlite3.connect(database) as db:
        assert db.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()[0] == journal_mode
    lease = SQLiteWriterLease.acquire(make_url(f"sqlite:///{database.as_posix()}"))
    try:
        with sqlite3.connect(database, timeout=0) as other:
            assert other.execute("SELECT trade_volume FROM us_daily_price").fetchone() == (123,)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        assert lease.held
        receipt = backup.backup_sqlite_database(
            source=database, output=database.parent / "under-lease.db",
            integrity_check="quick", max_seconds=10)
        assert receipt["integrity_check"] == "ok" and lease.held
    finally:
        lease.release()
    with sqlite3.connect(database, timeout=0) as other:
        other.execute("BEGIN IMMEDIATE")  # Stop/exit does not preserve exclusion.


def test_existing_backup_then_existing_alembic_on_disposable_database(database, monkeypatch):
    receipt = backup.backup_sqlite_database(source=database, output=database.parent / "backup.db",
                                           integrity_check="full", max_seconds=10)
    restored = database.parent / "restored.db"
    shutil.copyfile(receipt["output"], restored)
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == receipt["sha256"]
    before = migrations.inspect_database_schema(database, check_integrity=True)
    restored_schema = migrations.inspect_database_schema(restored, check_integrity=True)
    assert restored_schema == before
    migrations.run_database_migrations(f"sqlite:///{database.as_posix()}")
    after = migrations.inspect_database_schema(database, check_integrity=True)
    assert after["state"] == "DB_AT_HEAD" and after["integrity"] == "ok"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT trade_volume,trade_volume_decimal FROM us_daily_price").fetchone() == (123, None)
    assert migrations.inspect_database_schema(restored)["state"] == "DB_BEHIND"
    before = database.read_bytes()
    monkeypatch.setattr(migrations.command, "upgrade", lambda *a: pytest.fail("head must not upgrade"))
    migrations.run_database_migrations(f"sqlite:///{database.as_posix()}")
    assert database.read_bytes() == before


def test_runtime_gets_are_bounded_no_redirect_or_post(monkeypatch):
    calls, closed = [], []
    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 8400, 3)
        def request(self, method, route):
            calls.append((method, route))
        def getresponse(self):
            return self
        status = 302
        def read(self, limit):
            pytest.fail("redirect body must not be read or followed")
        def close(self):
            closed.append(True)
    monkeypatch.setattr(maintenance.http.client, "HTTPConnection", Connection)
    assert maintenance.read_runtime("http://127.0.0.1:8400") == {"health": {}, "control": {}, "readyz": {}}
    assert len(calls) == len(closed) == 3
    assert all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize("partial", [False, True])
def test_migration_exception_preserves_partial_ddl_for_manual_recovery(database, monkeypatch, partial):
    before = database.read_bytes()
    calls = []
    def fail(config, target):
        calls.append(target)
        if partial:
            with sqlite3.connect(database) as db:
                db.execute("ALTER TABLE us_daily_price ADD COLUMN partial_marker TEXT")
        raise RuntimeError("fixture migration exception")
    monkeypatch.setattr(migrations.command, "upgrade", fail)
    with pytest.raises(RuntimeError, match="fixture migration exception"):
        migrations.run_database_migrations(f"sqlite:///{database.as_posix()}")
    assert calls == ["head"]
    assert migrations.inspect_database_schema(database)["state"] == "DB_BEHIND"
    assert (database.read_bytes() != before) is partial
    # These owner primitives are NOT an integrated production Apply claim.
