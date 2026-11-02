"""Real Launcher function AST; disposable lifecycle adapters only."""
import json
from pathlib import Path

import pytest

from test_launcher_backend_start import START_SETUP
from test_runtime_launcher_recovery import _run_isolated_launcher
from test_launcher_failed_start_recovery import RECOVERY_CS


SETUP = START_SETUP + r'''
foreach ($name in @('Write-OmiSchemaOperation','Get-OmiSchemaWorkerOutcome','Invoke-OwnedSchemaUpgrade')) {
    $definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$false)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:RuntimeControlStore='STORE'
$script:SchemaMaintenanceAttempted=$false
$script:SchemaMaintenanceFailed=$false
$script:SafeStopAttempted=$false
$script:Mode='MODE'
$script:ApplicationRelease='fixture-release'
function Get-OmiBackendApplicationRelease { return $script:ApplicationRelease }
function Get-OmiSchemaSourceRelease { return 'fixture-schema-source' }
function Assert-OmiProductionBackendStartPreflight { if (-not $script:ServiceStartRequestInProgress) {throw 'NOT_FENCED'} }
function Assert-OmiFailedStartProcessExclusion { if ($script:Mode -eq 'ambiguous') {throw 'AMBIGUOUS'} }
$old=$script:OwnedBackendSession
$old.Terminal=$false; $old.Alive=$true; $old.LastStop=$null; $old.CanStartAfterStop=$false
$old | Add-Member -Force NoteProperty HasRetainedIdentity $true
$old | Add-Member NoteProperty CanRecoverFailedStart $true
$old | Add-Member NoteProperty SchemaWorkerSettled $false
$old | Add-Member NoteProperty CanResumeAfterSchemaStopRefusal $false
if ($script:Mode -like 'failed*' -or $script:Mode -eq 'ambiguous') {
    $old.StartupFailure='OWNED_START_EXIT_CONFIRMED'; $old.Terminal=$true; $old.Alive=$false
}
$originalFailure=$old.StartupFailure
$old | Add-Member ScriptMethod AdmitFailedStartSchemaMaintenance {
    param($id,$release)
    if (-not $this.CanRecoverFailedStart -or -not $script:ServiceStartRequestInProgress) {throw 'BAD_ADMISSION'}
    $script:Calls.Add('failed-admit')
}
$old | Add-Member ScriptMethod StopForSchemaMaintenanceAsync {
    param($id,$release)
    if (-not $script:ServiceStartRequestInProgress -or $script:Timer.Enabled -or $script:ActivationTimer.Enabled) {throw 'NOT_FENCED'}
    $script:Calls.Add('graceful-stop')
    $this.LastStop=[pscustomobject]@{RequestId=$id; BeforePid=$this.ChildPid; BeforeCreated=$this.ChildCreated;
        State='stopped'; Reason='LIFESPAN_AND_EXACT_EXIT'; ExactExit=$true; Forced=($script:Mode -eq 'forced'); ForcedExitConfirmed=$false; Rearmed=$false}
    $this.CanStartAfterStop=$true; $this.Terminal=$true; $this.Alive=$false
    $task=[Threading.Tasks.TaskCompletionSource[object]]::new();$task.SetResult($this.LastStop);return $task.Task
}
$old | Add-Member ScriptMethod AdmitStoppedSchemaMaintenance {
    param($id,$release)
    if (-not $this.CanStartAfterStop -or -not $this.SchemaWorkerSettled) {throw 'NOT_SETTLED'}
    $script:Calls.Add('stopped-admit')
}
$old | Add-Member ScriptMethod ApplyStoppedSchemaAsync {
    param($id,$release,$sourceRelease,$database,$lock,$receipt)
    $script:Calls.Add('apply')
    $this.SchemaWorkerSettled=$script:Mode -notin @('worker-unknown','committed-lost-reply','at-head-lost-reply')
    if (-not $script:ServiceStartRequestInProgress -or $script:Timer.Enabled -or $script:ActivationTimer.Enabled) {throw 'NOT_FENCED'}
    try {Invoke-OwnedSchemaUpgrade -RequestId $id -DatabasePath $database -SchemaLockPath $lock;throw 'REENTRY'}
    catch {if ($_.Exception.Message -ne 'SERVICE_OPERATION_IN_PROGRESS') {throw}}
    $worker=@{contract='omi.schema-apply.v1';request_id=$id;sequence=1;retry_allowed=$false;phase='COMMITTED';migration='COMMITTED'}
    if ($script:Mode -like 'at-head*') {
        $worker.phase='AT_HEAD';$worker.status='SUCCEEDED';$worker.migration='NOT_NEEDED'
        $worker.before_revision='20261030_0095';$worker.after_revision='20261030_0095';$worker.target_revision='20261030_0095'
        if ($script:Mode -eq 'at-head-bad-readback') {$worker.after_revision='20261025_0093'}
    }
    if ($script:Mode -like '*apply-failed') {$worker.phase='FAILED';$worker.migration='NOT_ATTEMPTED'}
    [IO.File]::WriteAllText($receipt, ($worker|ConvertTo-Json -Compress)+[Environment]::NewLine)
    if ($script:Mode -eq 'worker-unknown') {[IO.File]::WriteAllText($receipt,'{');throw 'LOST_CHANNEL'}
    if ($script:Mode -in @('committed-lost-reply','at-head-lost-reply')) {throw 'LOST_CHANNEL'}
    $task=[Threading.Tasks.TaskCompletionSource[bool]]::new();$task.SetResult($script:Mode -notlike '*apply-failed');return $task.Task
}
$old | Add-Member ScriptMethod RetireFailedStart {
    param($id,$release)
    $script:Calls.Add('failed-retire');$this.CanRecoverFailedStart=$false
    if (-not [object]::ReferenceEquals($this,$script:RetiredBackendSessions[0])) {throw 'NOT_RETAINED'}
}
$script:BaseFactory=(Get-Item Function:New-OmiProductionOwnedBackend).ScriptBlock
function New-OmiProductionOwnedBackend {
    param($ExpectedRelease)
    $result=& $script:BaseFactory
    $result | Add-Member -Force NoteProperty ReleaseId $script:ApplicationRelease
    return $result
}
if ($script:Mode -like '*start-failed') {$script:StartupFailure=$true}
if ($script:Mode -like '*readiness-failed') {$script:Ready=$false}
if ($script:Mode -eq 'wrong-owner') {$script:OwnsMutex=$false}
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedSchemaUpgrade -RequestId $id -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'} catch {}
$file=Join-Path 'STORE/schema-maintenance' ($id+'.operation.jsonl')
$rows=@(Get-Content -LiteralPath $file | ForEach-Object {$_ | ConvertFrom-Json})
$success=$script:Mode -in @('normal','failed-start','at-head')
if (($rows[-1].status -eq 'SUCCEEDED') -ne $success) {throw ('FALSE_RESULT '+($rows[-1]|ConvertTo-Json))}
if ($success -and ($rows[-1].after.readyz -ne 'VERIFIED' -or -not $rows[-1].after.created_at)) {throw 'READINESS_MISSING'}
if ($script:Mode -like 'failed*' -and ($null -ne $old.LastStop -or $old.StartupFailure -cne $originalFailure)) {throw 'FAILURE_REWRITTEN'}
$before=[IO.File]::ReadAllBytes($file)
$attempts=$script:SpawnCount
foreach($retry in @($id)) {
    try {Invoke-OwnedSchemaUpgrade -RequestId $retry -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock';throw 'REPLAY'}
    catch {if ($_.Exception.Message -ne 'SCHEMA_MAINTENANCE_NO_REPLAY') {throw}}
}
if ($attempts -ne $script:SpawnCount -or [Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes($file))) {throw 'REPLAY_MUTATED'}
if (-not [object]::ReferenceEquals($frontend,$script:FrontendProcess) -or $script:ServiceStartRequestInProgress) {throw 'FRONTEND_OR_FENCE_CHANGED'}
if ($script:Mode -in @('wrong-owner','ambiguous')) {
    if ($script:SchemaMaintenanceFailed -or $script:SafeStopAttempted) {throw 'PREFLIGHT_POISONED_RESTART'}
    # Exercise the actual Restart entry guard without calling any lifecycle:
    # an independent busy operation must win over the schema reconcile refusal.
    $script:ServiceStartRequestInProgress=$true
    try {Invoke-OwnedBackendRestart -RequestId ([Guid]::NewGuid().ToString('D')) -Deadline ([object]::new());throw 'UNEXPECTED_RESTART'}
    catch {if ($_.Exception.Message -ne 'SERVICE_OPERATION_IN_PROGRESS') {throw}}
    finally {$script:ServiceStartRequestInProgress=$false}
} elseif (-not $success -and -not $script:SchemaMaintenanceFailed) {throw 'RECONCILIATION_FENCE_LOST'}
'''


@pytest.mark.parametrize('mode,apply,start', [
    ('normal', 1, 1), ('failed-start', 1, 1), ('forced', 0, 0), ('ambiguous', 0, 0),
    ('wrong-owner', 0, 0), ('apply-failed', 1, 0), ('failed-apply-failed', 1, 0),
    ('start-failed', 1, 1), ('failed-start-failed', 1, 1), ('readiness-failed', 1, 1),
    ('worker-unknown', 1, 0), ('committed-lost-reply', 1, 0),
    ('at-head', 1, 1), ('at-head-start-failed', 1, 1), ('at-head-lost-reply', 1, 0), ('at-head-bad-readback', 1, 0),
])
def test_owned_orchestrator_once_receipts_and_separate_failure_states(tmp_path, mode, apply, start):
    result = _run_isolated_launcher(tmp_path, SETUP.replace('STORE', str(tmp_path)).replace('MODE', mode))
    assert result['calls'].count('apply') == apply
    assert result['calls'].count('factory') == start
    receipt = next((tmp_path / 'schema-maintenance').glob('*.operation.jsonl'))
    records = [json.loads(row) for row in receipt.read_text().splitlines()]
    assert [r['sequence'] for r in records] == list(range(1, len(records) + 1))
    if (mode.endswith('start-failed') or mode == 'readiness-failed') and not mode.startswith('at-head'):
        assert records[-1]['failed_phase'] == 'STARTING_ONCE'
        assert json.loads(Path(records[-1]['worker_receipt']).read_text())['migration'] == 'COMMITTED'
        assert records[-1]['status'] == 'MIGRATED_START_FAILED'
        assert records[-1]['successor_outcome'] == 'FAILED_UNCONFIRMED'
    if mode == 'worker-unknown':
        assert records[-1]['status'] == 'UNKNOWN_RECONCILIATION_REQUIRED'
        assert records[-1]['migration_outcome'] == 'UNKNOWN'
    if mode in {'forced', 'ambiguous', 'wrong-owner', 'apply-failed', 'failed-apply-failed'}:
        assert records[-1]['status'] == 'BLOCKED_NO_DB_CHANGE'
    if mode == 'committed-lost-reply':
        assert records[-1]['status'] == 'MIGRATED_START_UNVERIFIED'
        assert records[-1]['migration_outcome'] == 'COMMITTED'
        assert records[-1]['successor_outcome'] == 'NOT_ATTEMPTED'
    if mode == 'at-head':
        assert records[-1]['migration_outcome'] == 'NOT_NEEDED'
        assert records[-1]['schema_revision_basis'] == 'WORKER_AT_HEAD'
        assert records[-1]['successor_outcome'] == 'VERIFIED'
    if mode in {'at-head-start-failed', 'at-head-lost-reply'}:
        assert records[-1]['migration_outcome'] == 'NOT_NEEDED'
        assert records[-1]['status'] == 'START_UNVERIFIED_NO_DB_CHANGE'
    if mode == 'at-head-bad-readback':
        assert records[-1]['migration_outcome'] == 'UNKNOWN'


@pytest.mark.parametrize('publish_fails', [False, True])
def test_pending_worker_keeps_status_current_without_abandoning_on_publish_failure(tmp_path, publish_fails):
    setup = SETUP.replace('STORE', str(tmp_path)).replace('MODE', 'normal')
    setup = setup.replace(
        "$task=[Threading.Tasks.TaskCompletionSource[bool]]::new();$task.SetResult($script:Mode -notlike '*apply-failed');return $task.Task",
        "$script:DelayTask=[SchemaHeartbeatDelay]::Run();return $script:DelayTask")
    setup = setup.replace("$id=[Guid]::NewGuid().ToString('D')", """
$id=[Guid]::NewGuid().ToString('D')
$script:UpdateOperation=@{request_id=$id;migration_outcome='NOT_ATTEMPTED'}
""")
    setup = setup.replace('function Assert-OmiProductionBackendStartPreflight', r'''
$script:HeartbeatCount=0
function Publish-OmiRuntimeControlStatus {
    if ($null -ne $script:DelayTask -and -not $script:DelayTask.IsCompleted) {
        $script:HeartbeatCount++
        $script:PendingOutcome=$script:UpdateOperation.migration_outcome
        if (PUBLISH_FAILS) {throw 'PUBLISH_FAILED'}
    }
    $script:Calls.Add('publish')
}
function Assert-OmiProductionBackendStartPreflight'''.replace('PUBLISH_FAILS', '$true' if publish_fails else '$false'))
    scenario = r'''
Add-Type -TypeDefinition 'public static class SchemaHeartbeatDelay { public static System.Threading.Tasks.Task<bool> Run() { return System.Threading.Tasks.Task.Delay(2300).ContinueWith(t => true); } }' -ReferencedAssemblies System.Core
''' + setup + r'''
if ($script:HeartbeatCount -lt 1 -or $script:PendingOutcome -cne 'UNKNOWN') {throw 'PENDING_WORKER_STATUS_MISSING'}
'''
    result = _run_isolated_launcher(tmp_path, scenario)
    assert result['calls'].count('apply') == 1 and result['calls'].count('factory') == 1
    assert any('status publish unavailable' in line for line in result['logs']) is publish_fails


def test_at_head_outcome_survives_public_diagnostic_sanitization(tmp_path):
    setup = SETUP.replace('STORE', str(tmp_path)).replace('MODE', 'at-head')
    scenario = setup + r'''
$d=[Omi.RuntimeControl.OperationDiagnostics]::new()
$d.request_id=$id;$d.phase='COMPLETE';$d.worker_phase='AT_HEAD';$d.migration_outcome='NOT_NEEDED'
$d.schema_revision_observed='20261030_0095';$d.schema_revision_basis='WORKER_AT_HEAD'
$d.worker_failure_code='KNOWN_REVISION_REQUIRED'
$safe=[Omi.RuntimeControl.OperationDiagnostics]::Sanitize($d,$id)
if ($safe.worker_phase -cne 'AT_HEAD' -or $safe.migration_outcome -cne 'NOT_NEEDED' -or
    $safe.schema_revision_basis -cne 'WORKER_AT_HEAD' -or $safe.worker_failure_code -cne 'KNOWN_REVISION_REQUIRED') {throw 'AT_HEAD_DIAGNOSTICS_LOST'}
'''
    assert _run_isolated_launcher(tmp_path, scenario)['calls'].count('factory') == 1


def test_real_failed_start_session_schema_admission_one_shot(tmp_path):
    app = tmp_path / 'backend/app'
    app.mkdir(parents=True)
    (app / 'fixture.py').write_text('# fixture')
    check = r'''
    Set-Field 'repo' 'ROOT'
    $release=[Omi.OwnedShutdown.ProductionSession]::ApplicationRelease('ROOT')
    $id=[Guid]::NewGuid().ToString('D')
    $session.AdmitFailedStartSchemaMaintenance($id,$release)
    try {$session.AdmitFailedStartSchemaMaintenance($id,$release);throw 'REPLAY'}
    catch {if ($_.Exception.Message -notmatch 'SCHEMA_ADMISSION_NOT_ATTESTED') {throw}}
    try {$session.ApplyStoppedSchemaAsync([Guid]::NewGuid().ToString('D'),$release,'unused','unused','unused','unused');throw 'WRONG_REQUEST'}
    catch {if ($_.Exception.Message -notmatch 'SCHEMA_ADMISSION_NOT_ATTESTED') {throw}}
    if ($session.LastStop -or -not $session.CanRecoverFailedStart -or
        [Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes('JOURNAL/startup-failure.json'))) {throw 'ORIGINAL_FAILURE_CHANGED'}
'''
    script = RECOVERY_CS.replace('FAULT', '').replace('EXPECTED', '$true').replace('CHECK', check)
    script = script.replace('ROOT', str(tmp_path)).replace('JOURNAL', str(tmp_path / 'journal'))
    assert not _run_isolated_launcher(tmp_path, script)['calls']


def test_native_and_python_schema_source_pin_match(tmp_path):
    from test_owned_lifecycle_convergence import CS_SETUP
    from test_schema_maintenance import maintenance
    script = CS_SETUP + (
        f"\n$pin=[Omi.OwnedShutdown.ProductionSession]::SchemaSourceRelease('{maintenance.ROOT}')\n"
        f"if ($pin -cne '{maintenance.maintenance_source_id()}') {{throw 'SCHEMA_SOURCE_PIN_MISMATCH'}}\n")
    assert not _run_isolated_launcher(tmp_path, script)['calls']


@pytest.mark.parametrize('fault,phase,code,worker', [
    ('none', None, None, 'SETTLED'),
    ('owner', 'POST_STOP_OWNER_CHECK', 'BACKEND_START_OWNER_NOT_ATTESTED', 'NOT_ATTEMPTED'),
    ('source', 'POST_STOP_OWNER_CHECK', 'SOURCE_ADOPTION_NOT_ATTESTED', 'NOT_ATTEMPTED'),
    ('release', 'POST_STOP_RELEASE_CHECK', 'RESTART_SOURCE_CHANGED', 'NOT_ATTEMPTED'),
    ('schema', 'INTENT', 'RESTART_COMPATIBILITY_NOT_ATTESTED', 'NOT_ATTEMPTED'),
    ('worker', 'APPLY_STOPPED', 'SCHEMA_APPLY_UNCONFIRMED', 'SETTLED'),
    ('transaction', 'APPLY_STOPPED', 'SCHEMA_APPLY_UNCONFIRMED', 'UNCONFIRMED'),
    ('lost-reply', 'APPLY_STOPPED', 'UNCLASSIFIED_FAILURE', 'UNCONFIRMED'),
])
def test_schema_diagnostics_distinguish_gates_without_granting_recovery(tmp_path, fault, phase, code, worker):
    setup = SETUP.split('$id=[Guid]::NewGuid()', 1)[0]
    inject = {'owner': '$script:OwnsMutex=$false', 'source': "$script:DiskSource='changed'",
              'release': "$script:ApplicationRelease='changed'"}.get(fault, '')
    setup = setup.replace('$this.CanStartAfterStop=$true; $this.Terminal=$true; $this.Alive=$false',
                          '$this.CanStartAfterStop=$true; $this.Terminal=$true; $this.Alive=$false\n' + inject)
    setup = setup.replace("if ($script:Mode -like '*apply-failed') {$worker.phase='FAILED';$worker.migration='NOT_ATTEMPTED'}", r'''
    $worker.after_revision='20261030_0094';$worker.updated_at='2026-10-30T03:00:00Z'
    if ('FAULT' -in @('worker','transaction')) {
        $worker.phase='FAILED';$worker.failed_phase=if ('FAULT' -eq 'worker') {'EXCLUSIVE'} else {'MIGRATING'}
        $worker.error_code=if ('FAULT' -eq 'worker') {'KNOWN_BEHIND_REVISION_REQUIRED'} else {'SCHEMA_MAINTENANCE_FAILED'}
        $worker.error_type='RuntimeError';$worker.before_revision='20261025_0093'
        $worker.migration=if ('FAULT' -eq 'worker') {'NOT_ATTEMPTED'} else {'FAILED_TRANSACTION_REQUIRES_INSPECTION'}
        $this.SchemaWorkerSettled='FAULT' -eq 'worker'
    }
''').replace("$script:Mode -notlike '*apply-failed'", "'FAULT' -notin @('worker','transaction')")
    scenario = setup + r'''
function Assert-OmiSchemaCompatibility {param($ExpectedRelease,$DatabasePath,$SchemaLockPath,[switch]$Upgrade)
    $script:RestartCompatibilityObservation=[pscustomobject]@{Session=$old;TargetRelease=$ExpectedRelease;
        SchemaRevision='20261025_0093';ObservedAt='2026-10-30T02:59:00Z'}
    if ('FAULT' -eq 'schema') {throw 'RESTART_COMPATIBILITY_NOT_ATTESTED'}
}
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedSchemaUpgrade -RequestId $id -DatabasePath 'FIXTURE.db' -SchemaLockPath 'schema.lock'} catch {}
$diagnostic=Get-OmiOperationDiagnostics -RequestId $id
if ($null -eq $diagnostic -or $diagnostic.request_id -cne $id) {throw 'DIAGNOSTIC_MISSING'}
$diagnostic|ConvertTo-Json -Depth 6|Set-Content -LiteralPath 'OUTPUT' -Encoding UTF8
$before=$script:Calls.Count
if ('FAULT' -notin @('none','schema','worker')) {
    try {Assert-OmiSchemaRecoveryAdmission;throw 'FALSE_RECOVERY'}
    catch {if ($_.Exception.Message -ne 'SCHEMA_MAINTENANCE_RECONCILIATION_REQUIRED') {throw}}
}
if ($script:Calls.Count -ne $before) {throw 'DIAGNOSTIC_SIDE_EFFECT'}
# A different request cannot borrow this generation's phase, commit or fence.
$other=Get-OmiOperationDiagnostics -RequestId ([Guid]::NewGuid().ToString('D'))
if ($other.phase -ne 'UNKNOWN' -or $other.recovery_fence.admission -ne 'UNKNOWN' -or $other.schema_revision_observed) {throw 'CROSS_REQUEST_EVIDENCE'}
'''
    scenario = (scenario.replace('STORE', str(tmp_path)).replace('MODE', 'committed-lost-reply' if fault == 'lost-reply' else 'normal')
                .replace('FAULT', fault).replace('OUTPUT', str(tmp_path / 'diagnostic.json')))
    result = _run_isolated_launcher(tmp_path, scenario)
    diagnostic = json.loads((tmp_path / 'diagnostic.json').read_text(encoding='utf-8-sig'))
    assert diagnostic['failed_phase'] == phase
    assert diagnostic['failure_code'] == code
    assert diagnostic['worker_outcome'] == worker
    assert diagnostic['observation_only'] is True
    assert 'FIXTURE.db' not in json.dumps(diagnostic) and 'worker_receipt' not in diagnostic
    assert result['calls'].count('factory') == (fault == 'none')
    if fault == 'none':
        assert diagnostic['schema_revision_observed'] == '20261030_0094'
        assert diagnostic['schema_revision_basis'] == 'WORKER_COMMITTED'
        assert diagnostic['next_action'] == 'Status'
    if fault in {'worker', 'transaction'}:
        assert diagnostic['worker_failed_phase'] == ('EXCLUSIVE' if fault == 'worker' else 'MIGRATING')
        assert diagnostic['worker_failure_code'] == ('KNOWN_BEHIND_REVISION_REQUIRED' if fault == 'worker' else 'SCHEMA_MAINTENANCE_FAILED')
        assert diagnostic['schema_revision_observed'] == '20261025_0093'
        assert diagnostic['schema_revision_basis'] == 'WORKER_BEFORE'
