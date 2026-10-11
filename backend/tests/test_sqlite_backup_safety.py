"""Production backup owner tested only with disposable SQLite databases."""
import importlib.util
from pathlib import Path
import shutil
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("backup_safety", ROOT / "scripts/backup-omi-sqlite.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source #1.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version(version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('20261009_0092')")
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('preserved')")
    return path


def run(source, **kwargs):
    return backup.backup_sqlite_database(
        source=source, output=source.parent / "backup.sqlite3", integrity_check="full", **kwargs,
    )


def test_backup_independent_restore_and_source_unchanged(source):
    before = source.read_bytes()
    receipt = run(source, max_seconds=10)
    restored = source.parent / "independent.sqlite3"
    shutil.copyfile(receipt["output"], restored)
    with sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("SELECT value FROM evidence").fetchall() == [("preserved",)]
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20261009_0092"
    assert backup._sha256(restored) == receipt["sha256"]
    assert source.read_bytes() == before
    assert not (source.parent / "backup.sqlite3.partial").exists()


@pytest.mark.parametrize("seconds", [0, -1, float("inf"), float("nan"), True])
def test_invalid_deadline_has_no_io(monkeypatch, seconds):
    monkeypatch.setattr(Path, "resolve", lambda *_: pytest.fail("unexpected filesystem access"))
    with pytest.raises(ValueError, match="finite and positive"):
        run(Path("never-opened.sqlite3"), max_seconds=seconds)


def test_low_space_does_not_create_partial(source, monkeypatch):
    usage = shutil.disk_usage(source.parent)
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(ValueError, match="insufficient free space"):
        run(source)
    assert not (source.parent / "backup.sqlite3.partial").exists()


@pytest.mark.parametrize("name", ["backup.sqlite3", "backup.sqlite3.partial"])
def test_existing_files_never_overwritten(source, name):
    existing = source.parent / name
    existing.write_bytes(b"existing-owner")
    with pytest.raises(ValueError):
        run(source)
    assert existing.read_bytes() == b"existing-owner"


def test_output_created_during_hash_is_not_overwritten(source, monkeypatch):
    original = backup._sha256
    def racing_hash(path):
        digest = original(path)
        (source.parent / "backup.sqlite3").write_bytes(b"concurrent-owner")
        return digest
    monkeypatch.setattr(backup, "_sha256", racing_hash)
    with pytest.raises(FileExistsError):
        run(source)
    assert (source.parent / "backup.sqlite3").read_bytes() == b"concurrent-owner"
    assert (source.parent / "backup.sqlite3.partial").exists()


def test_deadline_during_copy_preserves_partial(source, monkeypatch):
    partial = source.parent / "backup.sqlite3.partial"
    # Advance only once copying has an output, independent of preflight checks.
    monkeypatch.setattr(backup.time, "monotonic", lambda: 100 if partial.exists() else 0)
    with pytest.raises(TimeoutError, match="deadline exceeded"):
        run(source, max_seconds=1)
    assert not (source.parent / "backup.sqlite3").exists()
    assert partial.exists()


def test_integrity_extra_rows_fail_closed(source, monkeypatch):
    connect = backup.sqlite3.connect
    class Cursor:
        def fetchall(self):
            return [("ok",), ("corruption",)]
    class Connection:
        def __init__(self, inner):
            self.inner = inner
        def execute(self, sql, *args):
            if sql == "PRAGMA integrity_check":
                return Cursor()
            return self.inner.execute(sql, *args)
        def close(self):
            self.inner.close()
    def wrapped(path, **kwargs):
        db = connect(path, **kwargs)
        return Connection(db) if str(path).endswith(".partial?mode=ro") else db
    monkeypatch.setattr(backup.sqlite3, "connect", wrapped)
    with pytest.raises(ValueError, match="integrity check failed"):
        run(source)
    assert not (source.parent / "backup.sqlite3").exists()
    assert (source.parent / "backup.sqlite3.partial").exists()


def test_pin_requires_bounded_deadline_before_io(monkeypatch):
    monkeypatch.setattr(Path, "resolve", lambda *_: pytest.fail("unexpected filesystem access"))
    with pytest.raises(ValueError, match="finite max_seconds"):
        run(Path("never-opened.sqlite3"), pin_wal_snapshot=True)


def test_pin_refuses_non_wal_without_changing_source(source):
    before = source.read_bytes()
    with pytest.raises(ValueError, match="already-WAL"):
        run(source, max_seconds=10, pin_wal_snapshot=True)
    assert source.read_bytes() == before
    assert not (source.parent / "backup.sqlite3.partial").exists()


def test_operator_cancel_before_copy(source):
    marker = source.parent / "cancel"
    marker.write_text("stop", encoding="utf-8")
    with pytest.raises(InterruptedError, match="cooperatively"):
        run(source, cancel_file=marker)
    assert not (source.parent / "backup.sqlite3.partial").exists()


@pytest.mark.parametrize("cancel", [False, True])
def test_wal_snapshot_allows_writer_and_preserves_snapshot_or_cancels(source, monkeypatch, cancel):
    connect = backup.sqlite3.connect
    writer = connect(source, timeout=0.1)
    marker = source.parent / "cancel"
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE payload(value BLOB)")
        writer.execute("INSERT INTO payload VALUES (zeroblob(20000000))")
        writer.commit()
        wrote = []
        class ReadConnection:
            def __init__(self, inner): self.inner = inner
            def __getattr__(self, name): return getattr(self.inner, name)
            def backup(self, target, *, progress, **kwargs):
                def stepped(status, remaining, total):
                    if not wrote:
                        writer.execute("INSERT INTO evidence VALUES ('concurrent')")
                        writer.commit()  # A pinned WAL reader must not block this.
                        wrote.append(True)
                        if cancel: marker.write_text("stop", encoding="utf-8")
                    progress(status, remaining, total)
                return self.inner.backup(target, progress=stepped, **kwargs)
        def wrapped(path, **kwargs):
            db = connect(path, **kwargs)
            return ReadConnection(db) if str(path) == source.as_uri() + "?mode=ro" else db
        monkeypatch.setattr(backup.sqlite3, "connect", wrapped)
        if cancel:
            with pytest.raises(InterruptedError, match="cooperatively"):
                run(source, max_seconds=10, pin_wal_snapshot=True, cancel_file=marker)
            assert not (source.parent / "backup.sqlite3").exists()
        else:
            receipt = run(source, max_seconds=10, pin_wal_snapshot=True)
            assert receipt['source_snapshot_mode'] == 'bounded_wal_read_transaction'
            with connect(receipt['output']) as db:
                assert db.execute("SELECT value FROM evidence").fetchall() == [("preserved",)]
        assert wrote and writer.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 2
        # Copy failure/success releases the pinned reader, permitting a complete checkpoint.
        assert writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    finally:
        writer.close()


def test_wal_size_budget_refuses_snapshot(source, monkeypatch):
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO evidence VALUES ('wal')")
        writer.commit()
        monkeypatch.setattr(backup, "WAL_SNAPSHOT_LIMIT_BYTES", 1)
        with pytest.raises(RuntimeError, match="WAL snapshot size limit"):
            run(source, max_seconds=10, pin_wal_snapshot=True)
    assert not (source.parent / "backup.sqlite3").exists()


def test_cancel_during_integrity_check_interrupts_and_preserves_partial(source, monkeypatch):
    connect = backup.sqlite3.connect
    with connect(source) as db:
        db.executemany("INSERT INTO evidence VALUES (?)", [(str(i),) for i in range(10000)])
    marker = source.parent / "cancel"
    class VerificationConnection:
        def __init__(self, inner): self.inner = inner
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, *args):
            if sql == "PRAGMA integrity_check":
                marker.write_text("stop", encoding="utf-8")
            return self.inner.execute(sql, *args)
    def wrapped(path, **kwargs):
        db = connect(path, **kwargs)
        return VerificationConnection(db) if str(path).endswith(".partial?mode=ro") else db
    monkeypatch.setattr(backup.sqlite3, "connect", wrapped)
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        run(source, cancel_file=marker)
    assert not (source.parent / "backup.sqlite3").exists()
    assert (source.parent / "backup.sqlite3.partial").exists()


def test_cancel_during_hash_does_not_publish(source, monkeypatch):
    original = backup._sha256
    marker = source.parent / "cancel"
    def cancelling_hash(path, **kwargs):
        marker.write_text("stop", encoding="utf-8")
        return original(path, **kwargs)
    monkeypatch.setattr(backup, "_sha256", cancelling_hash)
    with pytest.raises(InterruptedError, match="cooperatively"):
        run(source, cancel_file=marker)
    assert not (source.parent / "backup.sqlite3").exists()
    assert (source.parent / "backup.sqlite3.partial").exists()


def test_wal_growth_during_source_metadata_closes_reader_before_copy(source, monkeypatch):
    writer = sqlite3.connect(source, timeout=0.1)
    original_snapshot = backup._database_snapshot
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        def snapshot_with_concurrent_growth(connection):
            result = original_snapshot(connection)
            writer.execute("INSERT INTO evidence VALUES ('metadata-window-write')")
            writer.commit()
            monkeypatch.setattr(backup, "WAL_SNAPSHOT_LIMIT_BYTES", 1)
            return result
        monkeypatch.setattr(backup, "_database_snapshot", snapshot_with_concurrent_growth)
        with pytest.raises(RuntimeError, match="WAL snapshot size limit"):
            run(source, max_seconds=10, pin_wal_snapshot=True)
        assert not (source.parent / "backup.sqlite3.partial").exists()
        assert writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    finally:
        writer.close()
