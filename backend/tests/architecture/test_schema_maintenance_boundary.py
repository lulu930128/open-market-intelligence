"""The one-shot schema lane must not become ordinary restart authority."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_schema_lane_keeps_original_owner_and_no_cutoff_or_frontend():
    source = (ROOT / 'scripts/omi-launcher.ps1').read_text(encoding='utf-8-sig')
    upgrade = source.split('function Invoke-OwnedSchemaUpgrade {', 1)[1].split('\nfunction ', 1)[0]
    assert 'Assert-OmiManualBackendStartOwner' in upgrade
    assert 'StopForSchemaMaintenanceAsync' in upgrade
    assert 'AdmitFailedStartSchemaMaintenance' in upgrade
    assert 'RetireFailedStart' in upgrade
    assert 'Start-OmiBackendSuccessor' in upgrade
    for forbidden in ('StopWithinDeadlineAsync', 'apply-omi-update', 'Stop-Frontend', 'Stop-Process', 'Restore-', 'Downgrade-'):
        assert forbidden not in upgrade
    restart = source.split('function Invoke-OwnedBackendRestart {', 1)[1].split('\nfunction ', 1)[0]
    for forbidden in ('ApplyStoppedSchemaAsync', 'backup-omi-sqlite', 'run_database_migrations'):
        assert forbidden not in restart
    assert upgrade.index('$script:ServiceStartRequestInProgress = $true') < upgrade.index('StopForSchemaMaintenanceAsync')
    assert upgrade.index("successor_outcome='VERIFIED'") < upgrade.index('$script:SchemaMaintenanceFailed=$false')


def test_worker_admission_is_native_and_never_receipt_unlock():
    source = (ROOT / 'scripts/omi-schema-maintenance.py').read_text()
    worker = source.split('def owner_worker()', 1)[1].split('\ndef _attest_launcher_parent', 1)[0]
    assert worker.index('_attest_launcher_parent') < worker.index('apply_stopped(')
    assert 'CHALLENGE' in worker and 'OWNER_CAPABILITY_NOT_CONSUMED' in worker
    assert 'receipt_status(' not in worker
    native = source.split('def _attest_launcher_parent', 1)[1].split('\n\nBLOCKERS', 1)[0]
    assert 'QueryFullProcessImageNameW' in native and 'NtQueryInformationProcess' in native
    assert 'NtQueryMutant' in native and 'owner.process != os.getppid()' in native
    assert 'FIXED_LAUNCHER_INVOCATION_REQUIRED' in native


def test_maintenance_uses_lease_and_supplied_alembic_transaction():
    source = (ROOT / 'scripts/omi-schema-maintenance.py').read_text()
    apply = source.split('def apply_stopped(', 1)[1].split('\ndef apply_status', 1)[0]
    assert 'SQLiteWriterLease.acquire' in apply and 'ProcessFileLock(schema_lock_path)' in apply
    assert apply.index('lease = SQLiteWriterLease.acquire') < apply.index('backup.backup_sqlite_database')
    assert apply.index('restore_verified') < apply.index('run_database_migrations(connection=connection)')
    assert apply.index('run_database_migrations(connection=connection)') < apply.index('connection.commit()')
    assert 'SQLITE_TRANSACTION' in apply and 'SQLITE_DENY' in apply
    env = (ROOT / 'backend/alembic/env.py').read_text()
    supplied = env.split('if supplied is not None:', 1)[1].split('connectable =', 1)[0]
    assert 'connection=supplied' in supplied and 'transactional_ddl=True' in supplied
    assert '.commit(' not in supplied and '.close(' not in supplied and 'engine_from_config' not in supplied


def test_reentry_and_pre_stop_compatibility_stay_in_existing_owner():
    launcher = (ROOT / 'scripts/omi-launcher.ps1').read_text(encoding='utf-8-sig')
    restart = launcher.split('function Invoke-OwnedBackendRestart {', 1)[1].split('\nfunction ', 1)[0]
    assert '$targetRelease = Get-OmiBackendApplicationRelease' in restart
    assert '$targetRelease = $old.ReleaseId' not in restart
    assert restart.index('$script:OwnedBackendRestartRequests.Add') < restart.index('$targetRelease = Get-OmiBackendApplicationRelease')
    assert restart.index('$targetRelease = Get-OmiBackendApplicationRelease') < restart.index('Assert-OmiSchemaCompatibility')
    assert restart.index('Assert-OmiSchemaCompatibility') < restart.index('StopWithinDeadlineAsync')
    for entry in ('Invoke-OwnedBackendRestart', 'Invoke-BackendStartRequest', 'Invoke-OwnedSchemaUpgrade'):
        function = launcher.split('function ' + entry + ' {', 1)[1].split('\nfunction ', 1)[0]
        assert 'Assert-OmiSchemaRecoveryAdmission' in function
        assert 'if ($script:SchemaMaintenanceFailed)' not in function
        assert 'if ($script:SchemaMaintenanceAttempted)' not in function
    adapter = (ROOT / 'scripts/omi-runtime-control.ps1').read_text(encoding='utf-8-sig')
    client = adapter.split('function Invoke-OmiLauncherCommand {', 1)[1].split('\nfunction ', 1)[0]
    assert 'Controller]::RequestOwner' in client
    assert 'GetEnvironmentVariable' not in client and 'Invoke-Expression' not in client
