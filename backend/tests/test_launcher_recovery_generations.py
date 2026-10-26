"""Explicit new operations, never production lifecycle or database access."""
import pytest

from test_launcher_backend_start import RESTART_SETUP
from test_runtime_launcher_recovery import _run_isolated_launcher
from test_launcher_failed_start_recovery import RECOVERY_PS
from test_launcher_failed_start_recovery import RECOVERY_CS
from test_launcher_schema_maintenance import SETUP as SCHEMA_SETUP


@pytest.mark.parametrize("failure", ["source", "schema", "unknown"])
def test_restart_refuses_before_stop_and_keeps_old_generation(tmp_path, failure):
    scenario = RESTART_SETUP + r'''
$before=$script:OwnedBackendSession
function Assert-OmiSchemaCompatibility { param($ExpectedRelease,$DatabasePath,$SchemaLockPath,[switch]$Upgrade)
    if ('FAILURE' -ne 'source') {throw 'RESTART_COMPATIBILITY_NOT_ATTESTED'}
}
if ('FAILURE' -eq 'source') {$script:ApplicationRelease='dirty-candidate'}
try {Invoke-OwnedBackendRestart -RequestId ([Guid]::NewGuid().ToString('D')) -Deadline ([object]::new());throw 'UNSAFE_STOP'}
catch {if ($_.Exception.Message -notin @('RESTART_SOURCE_CHANGED','RESTART_COMPATIBILITY_NOT_ATTESTED')) {throw}}
if ($script:Calls.Contains('backend-stop') -or $script:SpawnCount -or
    -not [object]::ReferenceEquals($before,$script:OwnedBackendSession) -or -not $before.Alive) {throw 'OLD_GENERATION_CHANGED'}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("FAILURE", failure))


def test_previous_recovery_does_not_poison_new_failed_generation(tmp_path):
    scenario = RECOVERY_PS + r'''
# The diagnostic lifetime flag cannot veto the new retained failure proof.
$script:FailedStartRecoveryAttempted=$true
$script:ServiceStartRequestInProgress=$true
$script:Timer.Stop();$script:ActivationTimer.Stop()
$id=[Guid]::NewGuid().ToString('D')
$null=Start-OmiBackendAfterFailedStart -RequestId $id
if ($script:SpawnCount -ne 1 -or $original.StartupFailure -ne 'OWNED_START_EXIT_CONFIRMED') {throw 'GENERATION_POISONED'}
try {Start-OmiBackendAfterFailedStart -RequestId $id;throw 'REPLAY'}
catch {if ($_.Exception.Message -ne 'FAILED_START_RECOVERY_REPLAY') {throw}}
'''
    _run_isolated_launcher(tmp_path, scenario)


def test_successor_start_failure_uses_its_own_new_recovery_generation(tmp_path):
    scenario = RECOVERY_PS + r'''
$script:ServiceStartRequestInProgress=$true
$script:Timer.Stop();$script:ActivationTimer.Stop()
$script:StartupFailure=$true
$first=[Guid]::NewGuid().ToString('D')
try {Start-OmiBackendAfterFailedStart -RequestId $first;throw 'UNEXPECTED_READY'}
catch {if ($_.Exception.Message -ne 'OWNED_START_UNKNOWN') {throw}}
$failed=$script:OwnedBackendSession
if ([object]::ReferenceEquals($failed,$original) -or $script:SpawnCount -ne 1) {throw 'MISSING_NEW_FAILED_CHILD'}
# Model the new child's subsequently attested nonzero exit, without borrowing
# the old child's receipt. Native exact-exit/receipt invariants are tested separately.
$failed.StartupFailure='OWNED_START_EXIT_CONFIRMED';$failed.Alive=$false;$failed.Terminal=$true
$failed | Add-Member NoteProperty CanRecoverFailedStart $true
$failed | Add-Member ScriptMethod RetireFailedStart {
    param($id,$release)
    if (-not [object]::ReferenceEquals($this,$script:RetiredBackendSessions[$script:RetiredBackendSessions.Count-1])) {throw 'WRONG_GENERATION'}
    $this.CanRecoverFailedStart=$false
}
$script:StartupFailure=$false
$null=Start-OmiBackendAfterFailedStart -RequestId ([Guid]::NewGuid().ToString('D'))
if ($script:SpawnCount -ne 2 -or $script:RetiredBackendSessions.Count -ne 2 -or
    $original.StartupFailure -ne 'OWNED_START_EXIT_CONFIRMED' -or $failed.StartupFailure -ne 'OWNED_START_EXIT_CONFIRMED') {throw 'GENERATION_RECOVERY_FAILED'}
try {Start-OmiBackendAfterFailedStart -RequestId $first;throw 'UUID_REPLAY'}
catch {if ($_.Exception.Message -ne 'FAILED_START_RECOVERY_REPLAY') {throw}}
'''
    _run_isolated_launcher(tmp_path, scenario)


@pytest.mark.parametrize("mode", ["wrong-owner", "ambiguous"])
def test_terminal_preflight_refusal_accepts_new_uuid_without_rewriting_old_receipt(tmp_path, mode):
    setup = SCHEMA_SETUP.split("$id=[Guid]::NewGuid()", 1)[0]
    scenario = setup + r'''
$first=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedSchemaUpgrade -RequestId $first -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'} catch {}
$file=Join-Path 'STORE/schema-maintenance' ($first+'.operation.jsonl')
$before=[IO.File]::ReadAllBytes($file)
$script:OwnsMutex=$true; $script:Mode='normal'
$second=[Guid]::NewGuid().ToString('D')
Invoke-OwnedSchemaUpgrade -RequestId $second -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'
if ([Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes($file))) {throw 'HISTORY_REWRITTEN'}
if ($script:SpawnCount -ne 1) {throw 'NO_NEW_OPERATION'}
try {Invoke-OwnedSchemaUpgrade -RequestId $first -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock';throw 'REPLAY'}
catch {if ($_.Exception.Message -ne 'SCHEMA_MAINTENANCE_NO_REPLAY') {throw}}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("STORE", str(tmp_path)).replace("MODE", mode))


@pytest.mark.parametrize("mode", ["worker-unknown", "committed-lost-reply"])
def test_unknown_migration_allows_no_new_destructive_operation(tmp_path, mode):
    setup = SCHEMA_SETUP.split("$id=[Guid]::NewGuid()", 1)[0]
    scenario = setup + r'''
try {Invoke-OwnedSchemaUpgrade -RequestId ([Guid]::NewGuid().ToString('D')) -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'} catch {}
$before=$script:Calls.Count
try {Invoke-OwnedSchemaUpgrade -RequestId ([Guid]::NewGuid().ToString('D')) -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock';throw 'UNSAFE_REENTRY'}
catch {if ($_.Exception.Message -ne 'SCHEMA_MAINTENANCE_RECONCILIATION_REQUIRED') {throw}}
if ($before -ne $script:Calls.Count) {throw 'SIDE_EFFECT_AFTER_UNKNOWN'}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("STORE", str(tmp_path)).replace("MODE", mode))


@pytest.mark.parametrize("mode", ["apply-failed", "failed-apply-failed"])
def test_settled_backup_failure_can_enter_new_schema_operation(tmp_path, mode):
    setup = SCHEMA_SETUP.split("$id=[Guid]::NewGuid()", 1)[0]
    scenario = setup + r'''
$first=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedSchemaUpgrade -RequestId $first -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'} catch {}
$file=Join-Path 'STORE/schema-maintenance' ($first+'.operation.jsonl')
$before=[IO.File]::ReadAllBytes($file)
$script:Mode='normal'
Invoke-OwnedSchemaUpgrade -RequestId ([Guid]::NewGuid().ToString('D')) -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'
if ($script:SpawnCount -ne 1 -or $script:LastSchemaOperation.status -ne 'SUCCEEDED') {throw 'SAFE_TERMINAL_POISONED'}
if ([Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes($file))) {throw 'HISTORY_REWRITTEN'}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("STORE", str(tmp_path)).replace("MODE", mode))


@pytest.mark.parametrize("damage", ["missing", "edited"])
def test_terminal_receipt_loss_does_not_unlock_new_uuid(tmp_path, damage):
    setup = SCHEMA_SETUP.split("$id=[Guid]::NewGuid()", 1)[0]
    scenario = setup + r'''
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedSchemaUpgrade -RequestId $id -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'} catch {}
$file=Join-Path 'STORE/schema-maintenance' ($id+'.operation.jsonl')
if ('DAMAGE' -eq 'missing') {[IO.File]::Move($file,$file+'.preserved')} else {[IO.File]::AppendAllText($file,'corrupt')}
try {Invoke-OwnedSchemaUpgrade -RequestId ([Guid]::NewGuid().ToString('D')) -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock';throw 'RECEIPT_UNLOCK'}
catch {if ($_.Exception.Message -ne 'SCHEMA_MAINTENANCE_RECONCILIATION_REQUIRED') {throw}}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("STORE", str(tmp_path)).replace("MODE", "wrong-owner").replace("DAMAGE", damage))


@pytest.mark.parametrize("settled,no_change,pending,admitted", [(True, True, False, True), (False, True, False, False), (True, False, False, False), (True, True, True, False)])
def test_native_schema_reentry_requires_settled_no_change_worker(tmp_path, settled, no_change, pending, admitted):
    app = tmp_path / "backend/app"
    app.mkdir(parents=True)
    (app / "fixture.py").write_text("# disposable release\n")
    check = r'''
Set-Field 'repo' 'ROOT'
$pin=[Omi.OwnedShutdown.ProductionSession]::ApplicationRelease('ROOT')
$first=[Guid]::NewGuid().ToString('D')
$session.AdmitFailedStartSchemaMaintenance($first,$pin)
Set-Field 'schemaWorkerAttempted' $true
Set-Field 'schemaStopPending' PENDING
Set-Field '<SchemaWorkerSettled>k__BackingField' SETTLED
Set-Field '<SchemaWorkerNoChange>k__BackingField' NO_CHANGE
try {$session.AdmitFailedStartSchemaMaintenance($first,$pin);throw 'REPLAY'}
catch {if ($_.Exception.Message -notmatch 'SCHEMA_ADMISSION_NOT_ATTESTED') {throw}}
$accepted=$false
try {$session.AdmitFailedStartSchemaMaintenance([Guid]::NewGuid().ToString('D'),$pin);$accepted=$true}
catch {if ($_.Exception.Message -notmatch 'SCHEMA_ADMISSION_NOT_ATTESTED') {throw}}
if ($accepted -ne ADMITTED -or $session.LastStop -or -not $session.CanRecoverFailedStart) {throw 'FALSE_RECOVERY_AUTHORITY'}
'''
    for key, value in {"SETTLED": settled, "NO_CHANGE": no_change, "PENDING": pending, "ADMITTED": admitted}.items():
        check = check.replace(key, "$true" if value else "$false")
    scenario = RECOVERY_CS.replace("FAULT", "").replace("EXPECTED", "$true").replace("CHECK", check)
    _run_isolated_launcher(tmp_path, scenario.replace("ROOT", str(tmp_path)).replace("JOURNAL", str(tmp_path / "journal")))
