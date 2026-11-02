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
    $script:ApplicationRelease='dirty-candidate'
}
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


@pytest.mark.parametrize("fault", ["none", "worker", "receipt", "generation", "request"])
def test_post_stop_pre_worker_reconciliation_preserves_history(tmp_path, fault):
    setup = SCHEMA_SETUP.split("$id=[Guid]::NewGuid()", 1)[0]
    setup = setup.replace("$this.CanStartAfterStop=$true; $this.Terminal=$true; $this.Alive=$false",
                          "$this.CanStartAfterStop=$true; $this.Terminal=$true; $this.Alive=$false\n$script:DiskSource='changed'")
    scenario = setup + r'''
$old | Add-Member ScriptMethod CanRecoverSchemaBeforeWorker {
    param($request)
    return 'FAULT' -ne 'worker' -and $request -ceq $id -and $this.CanStartAfterStop
}
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedSchemaUpgrade -RequestId $id -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'} catch {}
$file=Join-Path 'STORE/schema-maintenance' ($id+'.operation.jsonl')
$before=[IO.File]::ReadAllBytes($file)
if ($script:LastSchemaOperation.failed_phase -ne 'POST_STOP_OWNER_CHECK' -or
    $script:Calls.Contains('apply') -or $script:SpawnCount) {throw 'DID_NOT_REPRODUCE_PRE_WORKER_FAILURE'}
if ('FAULT' -eq 'receipt') {[IO.File]::AppendAllText($file,'changed')}
if ('FAULT' -eq 'generation') {$script:BackendProcess=[object]::new()}
if ('FAULT' -eq 'request') {$script:LastSchemaOperation.request_id=[Guid]::NewGuid().ToString('D')}
$allowed=$false
try {Assert-OmiSchemaRecoveryAdmission;$allowed=$true}
catch {if ($_.Exception.Message -ne 'SCHEMA_MAINTENANCE_RECONCILIATION_REQUIRED') {throw}}
if ($allowed -ne ('FAULT' -eq 'none')) {throw 'WRONG_RECOVERY_ADMISSION'}
$diagnostic=Get-OmiOperationDiagnostics -RequestId $id
if ('FAULT' -eq 'none') {
    if ($diagnostic.recovery_fence.admission -ne 'RECHECK_REQUIRED' -or
        -not $diagnostic.recovery_fence.worker_not_dispatched -or
        $diagnostic.recovery_fence.worker_settled -or $diagnostic.recovery_fence.no_effects -or
        $diagnostic.recovery_fence.retained_generation -ne 'EXACT_EXIT') {throw 'FALSE_SETTLED_OR_NO_EFFECTS'}
    if ([Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes($file))) {throw 'HISTORY_REWRITTEN'}
    $latest=[Omi.RuntimeControl.OperationDiagnostics]::new();$latest.request_id=[Guid]::NewGuid().ToString('D')
    $script:LastRuntimeOperationDiagnostics=$latest
    $script:RuntimeController | Add-Member -Force ScriptMethod Publish {
        param($json,$identity,$attested)
        $snapshot=$json|ConvertFrom-Json
        if ($snapshot.last_operation.request_id -cne $latest.request_id -or
            $snapshot.schema_reconciliation.request_id -cne $id -or
            -not $snapshot.schema_reconciliation.recovery_fence.worker_not_dispatched) {throw 'STATUS_RECONCILIATION_LOST_OR_REPLACED_LATEST'}
        $script:StatusChecked=$true
    }
    $rt=[Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1'),[ref]$null,[ref]$null)
    $definition=$rt.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Publish-OmiRuntimeControlStatus'},$false)
    . ([scriptblock]::Create($definition.Extent.Text))
    Publish-OmiRuntimeControlStatus
    if (-not $script:StatusChecked) {throw 'STATUS_NOT_PUBLISHED'}
    try {Invoke-OwnedSchemaUpgrade -RequestId $id -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock';throw 'REPLAY'}
    catch {if ($_.Exception.Message -ne 'SCHEMA_MAINTENANCE_NO_REPLAY') {throw}}
    # A separately authorized fixture operation uses the existing stopped-owner
    # maintenance path after source revalidation; it never repeats the old STOP.
    function Publish-OmiRuntimeControlStatus {$script:Calls.Add('publish')}
    $script:DiskSource=$script:LoadedLifecycleSourceId
    $old | Add-Member -Force ScriptMethod AdmitStoppedSchemaMaintenance {
        param($request,$release)
        if (-not $this.CanRecoverSchemaBeforeWorker($id) -or $request -ceq $id) {throw 'NO_RETAINED_NO_WORKER_PROOF'}
        $script:Calls.Add('stopped-admit')
    }
    Invoke-OwnedSchemaUpgrade -RequestId ([Guid]::NewGuid().ToString('D')) -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'
    if ($script:SpawnCount -ne 1 -or $script:SchemaMaintenanceFailed -or
        $script:LastSchemaOperation.status -ne 'SUCCEEDED' -or
        @($script:Calls | Where-Object {$_ -eq 'graceful-stop'}).Count -ne 1 -or
        [Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes($file))) {throw 'RECONCILED_FLOW_DID_NOT_RECOVER'}
}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("STORE", str(tmp_path)).replace("MODE", "normal").replace("FAULT", fault))
