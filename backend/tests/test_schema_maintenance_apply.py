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
                receipt_path=directory / 'apply.jsonl',
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
@pytest.mark.parametrize('revision', ['20261009_0092', '20261025_0093'])
def test_real_upgrade_excludes_writers_without_database_copies(database, monkeypatch, journal, revision):
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA journal_mode=' + journal)
        # Represents a writer that completed after backend exit, before reservation.
        db.execute('UPDATE us_daily_price SET trade_volume=456')
        db.execute('UPDATE alembic_version SET version_num=?', (revision,))
    args = arguments(database)
    original_upgrade = migrations.command.upgrade
    calls = []
    def upgrade(config, target):
        writer(database, 3)
        assert config.attributes['connection'].connection.driver_connection.in_transaction
        original_upgrade(config, target)
        writer(database, 3)
        calls.append('migration')
    monkeypatch.setattr(backup, 'backup_sqlite_database', lambda **kw: pytest.fail('unexpected full backup'))
    monkeypatch.setattr(migrations.command, 'upgrade', upgrade)
    result = maintenance.apply_stopped(**args)
    assert result['status'] == 'SUCCEEDED', result
    assert result['migration'] == 'COMMITTED' and result['startup'] == 'OWNER_ONLY'
    assert result['backup'] == 'NOT_REQUESTED' and not result['continuous_from_backend']
    assert result['before_revision'] == revision
    assert result['after_revision'] == result['target_revision'] == migrations.get_head_revision()
    assert calls == ['migration']
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT trade_volume FROM us_daily_price').fetchone() == (456,)
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (migrations.get_head_revision(),)
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('research_trade_proposal_version', 'research_candidate_revision', 'research_candidate_pending_revision')").fetchone() == (3,)
    assert not list(database.parent.glob('*.backup*'))
    assert not list(database.parent.glob('*.restore-check'))
    assert not (database.parent / 'backup.db').exists()
    writer(database, 0)
    before = args['receipt_path'].read_bytes()
    assert maintenance.apply_stopped(**args) == result
    assert args['receipt_path'].read_bytes() == before
    assert calls == ['migration']


@pytest.mark.parametrize('phase', ['ddl', 'early_commit', 'commit_reader', 'lock', 'writer'])
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
    original_upgrade = migrations.command.upgrade
    def failed_ddl(config, target):
        config.attributes['connection'].exec_driver_sql('ALTER TABLE us_daily_price ADD COLUMN partial_ddl TEXT')
        if phase == 'early_commit':
            config.attributes['connection'].exec_driver_sql('COMMIT')
        original_upgrade(config, target)
        raise RuntimeError('secret-token-must-not-be-recorded')
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
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'research_%'").fetchall() == []
    assert maintenance.apply_stopped(**args) == result
    assert args['receipt_path'].read_text() == text
    writer(database, 0)


def test_large_database_maintenance_has_finite_size_appropriate_budget():
    assert maintenance.maintenance_phase_seconds(1024 * 1024) == 120
    assert 1800 < maintenance.maintenance_phase_seconds(100 * 1024**3) < 7200
    assert maintenance.maintenance_phase_seconds(1024**5) == 7200


def test_at_head_skips_alembic_and_preserves_database_bytes(database, monkeypatch):
    migrations.run_database_migrations('sqlite:///' + database.as_posix())
    before = database.read_bytes()
    monkeypatch.setattr(migrations.command, 'upgrade', lambda *a, **k: pytest.fail('already at head'))
    monkeypatch.setattr(backup, 'backup_sqlite_database', lambda **kw: pytest.fail('unexpected backup'))
    result = maintenance.apply_stopped(**arguments(database))
    assert result['status'] == 'SUCCEEDED' and result['phase'] == 'AT_HEAD'
    assert result['migration'] == 'NOT_NEEDED' and result['backup'] == 'NOT_REQUESTED'
    assert result['before_revision'] == result['after_revision'] == result['target_revision'] == migrations.get_head_revision()
    assert database.read_bytes() == before
    writer(database, 0)


@pytest.mark.parametrize('revision', [None, '20990101_unknown'])
def test_unknown_revision_fails_without_schema_or_data_changes(database, monkeypatch, revision):
    with sqlite3.connect(database) as db:
        db.execute('DELETE FROM alembic_version')
        if revision is not None:
            db.execute('INSERT INTO alembic_version VALUES (?)', (revision,))
    before = database.read_bytes()
    monkeypatch.setattr(migrations.command, 'upgrade', lambda *a, **k: pytest.fail('unknown revision'))
    result = maintenance.apply_stopped(**arguments(database))
    assert result['status'] == 'FAILED' and result['migration'] == 'NOT_ATTEMPTED'
    assert result['error_code'] == 'KNOWN_REVISION_REQUIRED'
    assert database.read_bytes() == before
    writer(database, 0)


def test_upgrade_does_not_run_whole_database_checks(database):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    statements = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
        assert 'quick_check' not in statement.lower() and 'integrity_check' not in statement.lower()
    event.listen(Engine, 'before_cursor_execute', observe)
    try:
        result = maintenance.apply_stopped(**arguments(database))
    finally:
        event.remove(Engine, 'before_cursor_execute', observe)
    assert result['status'] == 'SUCCEEDED'
    assert any('alembic_version' in statement for statement in statements)


def test_committed_head_readback_failure_does_not_claim_rollback(database, monkeypatch):
    from alembic.runtime.migration import MigrationContext
    original = MigrationContext.get_current_revision
    def observed(context):
        if not context.connection.connection.driver_connection.in_transaction:
            return '20990101_unconfirmed'
        return original(context)
    monkeypatch.setattr(MigrationContext, 'get_current_revision', observed)
    result = maintenance.apply_stopped(**arguments(database))
    assert result['status'] == 'UNKNOWN' and result['migration'] == 'COMMITTED'
    assert result['error_code'] == 'MIGRATION_COMMITTED_HEAD_UNCONFIRMED'
    assert result['failed_phase'] == 'COMMITTING' and result['retry_allowed'] is False
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (migrations.get_head_revision(),)
        assert db.execute('SELECT trade_volume FROM us_daily_price').fetchone() == (123,)


@pytest.mark.parametrize('at_head', [False, True])
def test_worker_protocol_without_backup_path(database, monkeypatch, capsys, at_head):
    # Protocol fixture only: native parent authority is covered separately.
    import io
    from types import SimpleNamespace
    from app import owned_uvicorn
    if at_head:
        migrations.run_database_migrations('sqlite:///' + database.as_posix())
    args = arguments(database)
    boot = dict(action='ApplyStopped', launcher_pid=str(os.getppid()), launcher_created='fixture-birth',
                nonce='a' * 64, request_id=args['request_id'], database=str(database),
                schema_lock=str(args['schema_lock_path']), receipt=str(args['receipt_path']),
                source_release=maintenance.maintenance_source_id())
    go = dict(request_id=boot['request_id'], nonce=boot['nonce'], challenge='61' * 32, action='GO')
    monkeypatch.setattr(owned_uvicorn, 'creation', lambda pid: 'fixture-birth')
    monkeypatch.setattr(maintenance, '_attest_launcher_parent', lambda *a: None)
    monkeypatch.setattr(maintenance.os, 'urandom', lambda size: b'a' * size)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(boot) + '\n' + json.dumps(go) + '\n'))
    monkeypatch.setitem(sys.modules, 'app.config', SimpleNamespace(settings=SimpleNamespace(
        database_url='sqlite:///' + database.as_posix(), runtime_lock_dir=database.parent)))
    assert maintenance.owner_worker() == 0
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert frames[0]['state'] == 'CHALLENGE'
    assert frames[-1]['request_id'] == boot['request_id'] and frames[-1]['nonce'] == boot['nonce']
    assert frames[-1]['status'] == 'SUCCEEDED'
    assert frames[-1]['migration'] == ('NOT_NEEDED' if at_head else 'COMMITTED')


def test_migration_timeout_keeps_original_database_and_has_safe_phase_code(database, monkeypatch):
    args = arguments(database)
    def timeout(config, target):
        config.attributes['connection'].exec_driver_sql('CREATE TABLE partial_ddl(value TEXT)')
        raise TimeoutError('private-path-must-not-be-recorded')
    monkeypatch.setattr(migrations.command, 'upgrade', timeout)
    result = maintenance.apply_stopped(**args)
    assert result['status'] == 'FAILED' and result['migration'] == 'FAILED_TRANSACTION_REQUIRES_INSPECTION'
    assert result['failed_phase'] == 'MIGRATING' and result['error_code'] == 'SCHEMA_MIGRATION_TIMEOUT'
    assert result['error_type'] == 'TimeoutError'
    assert 'private-path' not in args['receipt_path'].read_text()
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('20261009_0092',)
        assert db.execute("SELECT name FROM sqlite_master WHERE name='partial_ddl'").fetchall() == []
    writer(database, 0)


@pytest.mark.parametrize('expired', [False, True])
def test_sqlite_interrupt_is_timeout_only_when_owner_budget_expired(database, monkeypatch, expired):
    clock = [0.0]
    monkeypatch.setattr(maintenance.time, 'monotonic', lambda: clock[0])
    def interrupted(config, target):
        clock[0] = maintenance.maintenance_phase_seconds(database.stat().st_size) if expired else 1.0
        error = sqlite3.OperationalError('private-query-must-not-be-recorded')
        error.sqlite_errorcode = sqlite3.SQLITE_INTERRUPT
        raise error
    monkeypatch.setattr(migrations.command, 'upgrade', interrupted)
    args = arguments(database)
    result = maintenance.apply_stopped(**args)
    assert result['failed_phase'] == 'MIGRATING' and result['migration'] == 'FAILED_TRANSACTION_REQUIRES_INSPECTION'
    assert result['error_code'] == ('SCHEMA_MIGRATION_TIMEOUT' if expired else 'SCHEMA_QUERY_INTERRUPTED')
    assert 'private-query' not in args['receipt_path'].read_text()


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
    assert response['error_code'] == 'FIXED_LAUNCHER_EXECUTABLE_REQUIRED'
    assert response['request_id'] == boot['request_id']
    assert str(maintenance.ROOT) not in result.stdout
    assert 'CHALLENGE' not in result.stdout
    assert not (database.parent / 'apply.jsonl').exists()


@pytest.mark.parametrize('content', ['', '{', '{"contract":"omi.schema-apply.v1"}\n'])
def test_torn_receipt_never_executes(database, content):
    args = arguments(database)
    args['receipt_path'].write_text(content)
    assert maintenance.apply_stopped(**args)['status'] == 'UNKNOWN'
    assert args['receipt_path'].read_text() == content
    assert not (database.parent / 'backup.db').exists()


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


@pytest.mark.parametrize('fault', ['none', 'wrong-script', 'unowned', 'update', 'invalid-update', 'extra-update'])
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
    args = [_powershell(), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(parent)]
    if fault in {'update', 'invalid-update', 'extra-update'}:
        args += ['-UpdateRequestId', str(uuid4()) if fault != 'invalid-update' else 'not-a-uuid']
    if fault == 'extra-update':
        args += ['-Unexpected', 'value']
    result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    allowed = fault in {'none', 'update'}
    assert result.returncode == (0 if allowed else 2), result.stdout + result.stderr
    assert ('PASS' in result.stdout) == allowed, result.stdout
