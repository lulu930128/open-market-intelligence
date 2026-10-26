"""Disposable ApplyStopped transactions and owner admission counterexamples."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from test_schema_maintenance import database, maintenance, backup
from app.db import migrations
from app.runtime_lock import ProcessFileLock


def arguments(database):
    directory = database.parent
    return dict(database=database, schema_lock_path=directory / 'schema.lock',
                backup_path=directory / 'backup.db', receipt_path=directory / 'apply.jsonl',
                request_id=str(uuid4()))


def writer(path, expected):
    # A genuinely independent process/SQLite connection, never a fixture mock.
    script = """
import sqlite3,sys
db=sqlite3.connect(sys.argv[1],timeout=0)
try:
    db.execute('BEGIN IMMEDIATE')
except sqlite3.OperationalError:
    raise SystemExit(3)
db.rollback();db.close()
"""
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(path)],
                            capture_output=True, timeout=10)
    assert result.returncode == expected, result.stderr


@pytest.mark.parametrize('journal', ['wal', 'delete'])
def test_real_0092_upgrade_excludes_writers_through_backup_and_migration(database, monkeypatch, journal):
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA journal_mode=' + journal)
        # Represents a writer that completed after backend exit, before reservation.
        db.execute('UPDATE us_daily_price SET trade_volume=456')
    args = arguments(database)
    original_backup = backup.backup_sqlite_database
    original_upgrade = migrations.command.upgrade
    calls = []
    def copied(**kwargs):
        writer(database, 3)
        with sqlite3.connect(database, timeout=0) as reader:
            assert reader.execute('SELECT trade_volume FROM us_daily_price').fetchone() == (456,)
        result = original_backup(**kwargs)
        writer(database, 3)
        calls.append('backup')
        return result
    def upgrade(config, target):
        writer(database, 3)
        assert config.attributes['connection'].connection.driver_connection.in_transaction
        original_upgrade(config, target)
        writer(database, 3)
        calls.append('migration')
    monkeypatch.setattr(maintenance, '_backup_module', lambda: backup)
    monkeypatch.setattr(backup, 'backup_sqlite_database', copied)
    monkeypatch.setattr(migrations.command, 'upgrade', upgrade)
    result = maintenance.apply_stopped(**args)
    assert result['status'] == 'SUCCEEDED', result
    assert result['migration'] == 'COMMITTED' and result['startup'] == 'OWNER_ONLY'
    assert result['backup']['restore_verified'] and not result['continuous_from_backend']
    assert calls == ['backup', 'migration']
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT trade_volume,trade_volume_decimal FROM us_daily_price').fetchone() == (456, None)
    with sqlite3.connect(args['backup_path']) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('20261009_0092',)
        assert db.execute('SELECT trade_volume FROM us_daily_price').fetchone() == (456,)
    writer(database, 0)
    before = args['receipt_path'].read_bytes()
    assert maintenance.apply_stopped(**args) == result
    assert args['receipt_path'].read_bytes() == before
    assert calls == ['backup', 'migration']


@pytest.mark.parametrize('phase', ['backup', 'ddl', 'early_commit', 'commit_reader', 'lock', 'writer'])
def test_failed_maintenance_is_durable_no_retry_no_restore(database, monkeypatch, phase):
    args = arguments(database)
    other = None
    lock = ProcessFileLock(args['schema_lock_path'])
    if phase == 'lock':
        assert lock.acquire()
    if phase in {'writer', 'commit_reader'}:
        other = sqlite3.connect(database, timeout=0)
        other.execute('BEGIN IMMEDIATE' if phase == 'writer' else 'BEGIN')
        other.execute('SELECT * FROM us_daily_price').fetchall()
    def failed_backup(**kwargs):
        raise RuntimeError('secret-token-must-not-be-recorded')
    def failed_ddl(config, target):
        config.attributes['connection'].exec_driver_sql('ALTER TABLE us_daily_price ADD COLUMN partial_ddl TEXT')
        if phase == 'early_commit':
            config.attributes['connection'].exec_driver_sql('COMMIT')
        raise RuntimeError('secret-token-must-not-be-recorded')
    if phase == 'backup':
        monkeypatch.setattr(maintenance, '_backup_module', lambda: backup)
        monkeypatch.setattr(backup, 'backup_sqlite_database', failed_backup)
    if phase in {'ddl', 'early_commit'}:
        monkeypatch.setattr(migrations.command, 'upgrade', failed_ddl)
    try:
        result = maintenance.apply_stopped(**args)
    finally:
        if other is not None:
            other.close()
        lock.release()
    assert result['status'] == 'FAILED', result
    assert not result['retry_allowed']
    text = args['receipt_path'].read_text()
    assert 'secret-token' not in text
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('20261009_0092',)
        assert db.execute('SELECT trade_volume FROM us_daily_price').fetchone() == (123,)
        assert 'partial_ddl' not in {r[1] for r in db.execute('PRAGMA table_info(us_daily_price)')}
    assert maintenance.apply_stopped(**args) == result
    assert args['receipt_path'].read_text() == text
    writer(database, 0)


def test_non_launcher_parent_cannot_forge_apply_boot(database):
    from app.owned_uvicorn import creation
    boot = dict(action='ApplyStopped', launcher_pid=str(os.getpid()),
                launcher_created=creation(os.getpid()), nonce='a' * 64, request_id=str(uuid4()))
    result = subprocess.run([sys._base_executable, '-I', '-B', str(maintenance.ROOT / 'scripts/omi-schema-maintenance.py'),
                             'ApplyStopped'], input=json.dumps(boot) + '\n', text=True,
                            capture_output=True, timeout=15)
    assert result.returncode == 2
    response = json.loads(result.stdout)
    assert response['status'] == 'UNKNOWN' and response['error_type'] == 'RuntimeError'
    assert 'CHALLENGE' not in result.stdout
    assert not (database.parent / 'apply.jsonl').exists()


@pytest.mark.parametrize('content', ['', '{', '{"contract":"omi.schema-apply.v1"}\n'])
def test_torn_receipt_never_executes(database, content):
    args = arguments(database)
    args['receipt_path'].write_text(content)
    assert maintenance.apply_stopped(**args)['status'] == 'UNKNOWN'
    assert args['receipt_path'].read_text() == content
    assert not args['backup_path'].exists()


@pytest.mark.parametrize('definition', [
    "CREATE INDEX uq_job_run_us_eod_obligation ON job_run (job_type, target)",
    "CREATE UNIQUE INDEX uq_job_run_us_eod_obligation ON job_run (target, job_type) WHERE job_type = 'us.intraday_eod_obligation'",
    "CREATE UNIQUE INDEX uq_job_run_us_eod_obligation ON job_run (job_type, target) WHERE job_type = 'other'",
])
def test_0092_refuses_heterogeneous_index(tmp_path, definition):
    path = tmp_path / 'index.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE alembic_version(version_num TEXT)')
        db.execute("INSERT INTO alembic_version VALUES ('20261006_0091')")
        db.execute('CREATE TABLE job_run(job_type TEXT,target TEXT)')
        db.execute(definition)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='INDEX_DEFINITION_MISMATCH'):
        migrations.run_database_migrations('sqlite:///' + path.as_posix())
    assert path.read_bytes() == before


@pytest.mark.parametrize('fault', ['none', 'wrong-script', 'unowned'])
def test_os_parent_and_mutex_attestation_with_disposable_powershell(tmp_path, fault):
    from test_runtime_launcher_recovery import _powershell
    parent = tmp_path / 'fixture-launcher.ps1'
    child = tmp_path / 'verify-parent.py'
    mutex = 'omi-schema-fixture-' + uuid4().hex
    expected = parent if fault != 'wrong-script' else tmp_path / 'other.ps1'
    child.write_text(
        "import sys,importlib.util\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(maintenance.ROOT / '.venv/Lib/site-packages')!r})\n"
        f"spec=importlib.util.spec_from_file_location('maintenance',{str(maintenance.ROOT / 'scripts/omi-schema-maintenance.py')!r})\n"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
        "try:\n"
        f" m._attest_launcher_parent(Path({str(expected)!r}),{mutex!r})\n"
        " print('PASS')\n"
        "except Exception as exc:\n print(type(exc).__name__+':'+str(exc));sys.exit(2)\n",
        encoding='utf-8')
    parent.write_text(
        "$ErrorActionPreference='Stop'\n"
        f"$mutex=[Threading.Mutex]::new($true,'{mutex}')\n"
        + ("$mutex.ReleaseMutex()\n" if fault == 'unowned' else "")
        + "$info=[Diagnostics.ProcessStartInfo]::new()\n"
        f"$info.FileName='{sys._base_executable}'\n"
        f"$info.Arguments='-I -B \"{child}\"'\n"
        "$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true\n"
        "$child=[Diagnostics.Process]::Start($info)\n"
        "$output=$child.StandardOutput.ReadToEnd();$child.WaitForExit();Write-Output $output\n"
        "$code=$child.ExitCode;$child.Dispose()\n"
        + ("" if fault == 'unowned' else "$mutex.ReleaseMutex()\n")
        + "$mutex.Dispose();exit $code\n", encoding='utf-8-sig')
    result = subprocess.run([_powershell(), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(parent)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == (0 if fault == 'none' else 2), result.stdout + result.stderr
    assert ('PASS' in result.stdout) == (fault == 'none'), result.stdout
