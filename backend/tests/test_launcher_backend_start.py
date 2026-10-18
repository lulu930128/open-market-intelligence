"""Explicit tray start, using real Launcher AST and retained-process reducers.

Never execute the Launcher entrypoint, its real factory, named events, OMI
endpoints, providers or database. C# children below are disposable fixtures.
"""
from pathlib import Path

import pytest

from test_launcher_safe_stop import SETUP
from test_owned_lifecycle_convergence import CS_SETUP
from test_runtime_launcher_recovery import _run_isolated_launcher


START_SETUP = SETUP + r"""
. (Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1')
foreach ($name in @('Start-OmiBackendAfterExactStop', 'Invoke-BackendStartRequest', 'Invoke-OwnedBackendRestart', 'Start-Services', 'Start-Backend', 'Start-Frontend')) {
    $definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$false)
    . ([scriptblock]::Create($definition.Extent.Text))
}
Add-Type 'namespace System.Windows.Forms { public class MenuItem {
    public string Text; public event System.Action Click; public void PerformClick() { Click(); }
} }'
$script:Menu=[pscustomobject]@{ MenuItems=[Collections.Generic.List[object]]::new() }
foreach ($statement in @($ast.EndBlock.Statements | Where-Object {
    $_.Extent.Text -match '^\$startBackendItem\b' -or
    $_.Extent.Text -eq '[void]$script:Menu.MenuItems.Add($startBackendItem)'
})) { . ([scriptblock]::Create($statement.Extent.Text)) }
if ($script:Menu.MenuItems.Count -ne 1 -or $startBackendItem.Text -ne 'Start Backend') { throw 'MENU_NOT_WIRED' }
$script:RuntimeController=[pscustomobject]@{OwnerId='fixture-controller'}
$script:RuntimeController | Add-Member ScriptMethod TakePending { return $null }
$script:LoadedRuntimeController=$script:RuntimeController
$script:LoadedRuntimeControllerOwnerId=$script:RuntimeController.OwnerId
$script:Mutex=[pscustomobject]@{SafeWaitHandle=[pscustomobject]@{IsClosed=$false;IsInvalid=$false}}
$script:LoadedLifecycleSourceId='loaded-fixture'
$script:DiskSource='loaded-fixture'
$script:BackendPort=8400
$script:BackendHost='127.0.0.1'
$script:SafeStopAttempted=$true
$script:BackendStopExpected=$true
$script:RetiredBackendSessions=[Collections.Generic.List[object]]::new()
$script:ManualBackendStartAttemptedSession=$null
$script:LastBackendStartError=$null
$script:FrontendProcess=New-TestProcess
$frontend=$script:FrontendProcess
$script:SpawnCount=0
$script:Ready=$true
$script:Bindable=$true
function Test-TcpPortBindable {
    param([int]$Port, [string]$HostName, [string]$ServiceName, [switch]$Quiet)
    if ($Port -ne $script:OwnedBackendSession.SelectedPort -or $HostName -cne $script:OwnedBackendSession.SelectedHost -or
        $ServiceName -cne 'Backend' -or -not $Quiet) { throw 'WRONG_BIND_PROBE' }
    return $script:Bindable
}
function Get-OmiLifecycleSourceId { return $script:DiskSource }
function Get-OmiOwnedBackendIdentity {
    if ($script:WrongIdentity) { return [pscustomobject]@{pid=999;created_at='wrong'} }
    return [pscustomobject]@{pid=$script:OwnedBackendSession.ChildPid;created_at=$script:OwnedBackendSession.ChildCreated}
}
function Publish-OmiRuntimeControlStatus {
    if ($script:PublishFailure) { throw 'PUBLISH_FAILED' }
    $script:Calls.Add('publish')
}
function New-FakeOwned {
    $result=[pscustomobject]@{RunnerProcess=(New-TestProcess); ChildPid=(100+$script:SpawnCount); ChildCreated='fixture-created';
        Alive=$true;Terminal=$false;StartupFailure=$null;StartupExitConfirmed=$false;LastStop=$null;CanStartAfterStop=$false;RestartBlocker='';
        SelectedHost=$script:BackendHost;SelectedPort=$script:BackendPort}
    $result | Add-Member ScriptMethod DisposeAfterConfirmedStop {
        $script:Calls.Add('retire')
        if (-not [object]::ReferenceEquals($this,$script:RetiredBackendSessions[$script:RetiredBackendSessions.Count-1])) { throw 'NOT_ARCHIVED_FIRST' }
        if ($script:DisposeFailure) { throw 'DISPOSE_FAILED' }
        $this.CanStartAfterStop=$false
    }
    $result | Add-Member ScriptMethod WaitForStartReadinessAsync {
        param($budget)
        if ($budget -ne 30000 -or $script:Timer.Enabled -or $script:ActivationTimer.Enabled -or
            -not $script:ServiceStartRequestInProgress) { throw 'START_NOT_SERIALIZED' }
        if ($script:ProbeStartReentrancy) {
            foreach ($name in @('Invoke-BackendStartRequest','Stop-Services')) {
                try { & $name; throw 'REENTRY_ACCEPTED' }
                catch { if ($_.Exception.Message -ne 'SERVICE_OPERATION_IN_PROGRESS') { throw } }
            }
            Exit-Launcher -Reason 'during-start'
            Invoke-ServiceStartRequest -Reason 'during-start'
            foreach ($timerName in @('$script:Timer','$script:ActivationTimer')) {
                $tick=$ast.Find({param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and
                    $n.Member.Value -eq 'add_Tick' -and $n.Expression.Extent.Text -eq $timerName},$true)
                & $tick.Arguments[0].ScriptBlock.GetScriptBlock()
            }
        }
        if ($script:DriftDuringReadiness) { $script:DiskSource='changed' }
        $task=[Threading.Tasks.TaskCompletionSource[bool]]::new(); $task.SetResult($script:Ready); return $task.Task
    }
    $result | Add-Member ScriptMethod StopAsync {
        param($request)
        $script:Calls.Add('stop-new')
        $this.LastStop=[pscustomobject]@{RequestId=$request;State='stopped';Reason='LIFESPAN_AND_EXACT_EXIT';ExactExit=$true;Rearmed=$false}
        $this.Terminal=$true; $this.Alive=$false; $this.CanStartAfterStop=$true
        $task=[Threading.Tasks.TaskCompletionSource[object]]::new();$task.SetResult($this.LastStop);return $task.Task
    }
    return $result
}
function New-OmiProductionOwnedBackend {
    $script:Calls.Add('factory'); $script:SpawnCount++
    if (-not $script:SafeStopAttempted -or -not $script:ServiceStartRequestInProgress) { throw 'AUTO_GUARD_UNLOCKED' }
    if ($script:FactoryFailure) { throw 'FACTORY_FAILED' }
    $script:CreatedSession=New-FakeOwned
    if ($script:StartupFailure) { $script:CreatedSession.StartupFailure='OWNED_START_UNKNOWN';$script:CreatedSession.Terminal=$true }
    return $script:CreatedSession
}
$script:RestartReadyBackendSession=$null
$script:OwnedBackendSession=New-FakeOwned
$script:OwnedBackendSession.LastStop=$script:StopResult
$script:OwnedBackendSession.CanStartAfterStop=$true
$script:OwnedBackendSession.Terminal=$true
$script:OwnedBackendSession.Alive=$false
$script:BackendProcess=$script:OwnedBackendSession.RunnerProcess
$original=$script:OwnedBackendSession
$receipt=$original.LastStop
function Assert-StartResources {
    if ($script:ServiceStartRequestInProgress -or -not $script:SafeStopAttempted -or
        -not [object]::ReferenceEquals($frontend,$script:FrontendProcess) -or
        -not [object]::ReferenceEquals($receipt,$original.LastStop) -or [System.Windows.Forms.Application]::Exits) {
        throw 'OWNER_RECEIPT_OR_FRONTEND_LOST'
    }
}
"""


def test_explicit_tray_start_repeated_cycles_keep_receipts_and_auto_queue_fenced(tmp_path):
    result = _run_isolated_launcher(tmp_path, START_SETUP + r"""
$script:ProbeStartReentrancy=$true
for ($cycle=0;$cycle -lt 3;$cycle++) {
    $startBackendItem.PerformClick()
    Assert-StartResources
    if ($script:LastBackendStartError -or $script:BackendStopExpected -or
        $script:RetiredBackendSessions.Count -ne ($cycle+1)) { throw 'NEW_OWNER_NOT_READY' }
    $beforeCalls=$script:Calls.Count
    Invoke-OmiRuntimeControlTick
    if ($script:Calls.Count -gt ($beforeCalls+1)) { throw 'QUEUE_EXECUTED' }
    try { Restart-Services; throw 'RESTART_ACCEPTED' }
    catch { if ($_.Exception.Message -ne 'OWNED_RESTART_NOT_AVAILABLE_FROM_TRAY') { throw } }
    foreach ($name in @('Start-Services','Start-Backend','Start-Frontend')) {
        try { & $name; throw 'AUTOMATIC_START_ACCEPTED' }
        catch { if ($_.Exception.Message -ne 'SAFE_STOP_NO_START_OR_RECOVERY') { throw } }
    }
    Stop-Services -BackendOnly
    if (-not $script:BackendStopExpected -or -not $script:OwnedBackendSession.LastStop.ExactExit) { throw 'NEW_STOP_BROKEN' }
}
if ($script:SpawnCount -ne 3 -or -not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled) { throw 'CYCLE_FAILED' }
""")
    assert result['calls'].count('factory') == 3
    assert result['calls'].count('stop-new') == 3
    assert sum(line.startswith('Backend started. Owned READY') for line in result['logs']) == 3


@pytest.mark.parametrize('occupied', [False, True])
def test_retained_nondefault_port_is_supported_but_occupied_port_refused(tmp_path, occupied):
    result = _run_isolated_launcher(tmp_path, START_SETUP + r"""
$script:BackendPort=8401
$original.SelectedPort=8401
OCCUPIED
$startBackendItem.PerformClick()
Assert-StartResources
if ($script:SpawnCount -ne EXPECTED) { throw 'NONDEFAULT_FIXED_PORT_BROKEN' }
""".replace('OCCUPIED', 'function Get-ListeningProcessIdsOnPort { param($Port) if ($Port -ne 8401) {throw "WRONG_PORT"}; return @(777) }' if occupied else '')
        .replace('EXPECTED', '0' if occupied else '1'))
    assert any(line.startswith('Backend started. Owned READY') for line in result['logs']) is (not occupied)


def test_unbindable_port_refuses_before_consuming_attempt_and_can_be_explicitly_rechecked(tmp_path):
    result = _run_isolated_launcher(tmp_path, START_SETUP + r"""
$script:Bindable=$false
$startBackendItem.PerformClick()
Assert-StartResources
if ($script:SpawnCount -or $script:RetiredBackendSessions.Count -or $script:ManualBackendStartAttemptedSession -or
    -not [object]::ReferenceEquals($original,$script:OwnedBackendSession) -or -not $original.CanStartAfterStop) {throw 'BIND_REFUSAL_CONSUMED_OWNER'}
$script:Bindable=$true
$startBackendItem.PerformClick()
if ($script:SpawnCount -ne 1) {throw 'PRECHECK_BLOCKED_EXPLICIT_FUTURE_ACTION'}
""")
    assert 'FIXED_PORT_NOT_BINDABLE' in result['logs']
    assert result['calls'].count('factory') == 1
    assert result['calls'].count('retire') == 1


@pytest.mark.parametrize('fault', [
    '$script:OwnsMutex=$false', '$script:Mutex=$null',
    '$script:Mutex.SafeWaitHandle.IsClosed=$true',
    '$script:RuntimeController=$null',
    "$script:RuntimeController=[pscustomobject]@{OwnerId='fixture-controller'}",
    "$script:RuntimeController.OwnerId='other'", "$script:DiskSource='changed'",
    "$script:LoadedLifecycleSourceId=''", '$script:BackendPort=8401',
    "$script:BackendHost='::1'", '$script:BackendReload=$true', '$script:IsPackagedRelease=$true',
    '$script:OwnedBackendSession=$null', '$script:OwnedBackendSession.CanStartAfterStop=$false',
    '$script:BackendProcess=New-TestProcess',
    'function Get-ListeningProcessIdsOnPort { return @(777) }',
    "function Get-ListeningProcessIdsOnPort { throw 'PORT_OBSERVATION_UNAVAILABLE' }",
    '$script:ManualBackendStartAttemptedSession=$original',
])
def test_manual_start_preconditions_fail_before_retirement_or_spawn(tmp_path, fault):
    result = _run_isolated_launcher(tmp_path, START_SETUP + fault + r"""
$startBackendItem.PerformClick()
Assert-StartResources
if ($script:SpawnCount -or $script:RetiredBackendSessions.Count -or
    -not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled) { throw 'PRECHECK_SIDE_EFFECT' }
""")
    assert not result['calls']
    assert not any(line.startswith('Backend started') for line in result['logs'])


@pytest.mark.parametrize('fault,spawned', [
    ('$script:DisposeFailure=$true', False), ('$script:FactoryFailure=$true', False),
    ('$script:StartupFailure=$true', True), ('$script:Ready=$false', True),
    ('$script:WrongIdentity=$true', True), ('$script:DriftDuringReadiness=$true', True),
    ('$script:PublishFailure=$true', True),
])
def test_failed_attempt_retains_owner_no_retry_no_false_success(tmp_path, fault, spawned):
    result = _run_isolated_launcher(tmp_path, START_SETUP + fault + r"""
$script:Timer.Enabled=$false
$startBackendItem.PerformClick()
Assert-StartResources
if ($script:Timer.Enabled -or -not $script:ActivationTimer.Enabled -or
    -not $script:LastBackendStartError -or $script:RetiredBackendSessions.Count -ne 1) { throw 'FAILED_ATTEMPT_LOST' }
$expected=EXPECTED
if (-not [object]::ReferenceEquals($expected,$script:OwnedBackendSession)) { throw 'CURRENT_OWNER_LOST' }
$attempts=$script:SpawnCount
$startBackendItem.PerformClick()
if ($script:SpawnCount -ne $attempts) { throw 'FAILED_ATTEMPT_REPLAYED' }
""".replace('EXPECTED', '$script:CreatedSession' if spawned else '$original'))
    assert not any(line.startswith('Backend started') for line in result['logs'])


@pytest.mark.parametrize('flag', ['IsShuttingDown', 'ServiceStopInProgress', 'ServiceStartRequestInProgress',
                                 'RuntimeControlInProgress', 'BackendRecoveryInProgress', 'FrontendHealthRecoveryInProgress'])
def test_busy_owner_never_enters_manual_start(tmp_path, flag):
    result = _run_isolated_launcher(tmp_path, START_SETUP + f'$script:{flag}=$true\n' + r"""
$startBackendItem.PerformClick()
if ($script:SpawnCount -or $script:RetiredBackendSessions.Count -or -not $script:Timer.Enabled) { throw 'BUSY_START_ENTERED' }
""")
    assert not result['calls']
    assert 'SERVICE_OPERATION_IN_PROGRESS' in result['logs']


@pytest.mark.parametrize('fault', ['', 'no-respawn', 'receipt-uuid', 'receipt-child', 'receipt-state', 'receipt-reason',
                                  'no-receipt', 'child-created', 'runner-created', 'launcher-created',
                                  'child-code', 'runner-code', 'child-alive', 'runner-alive',
                                  'startup-failure', 'rearmed', 'unknown', 'timeout'])
def test_csharp_restart_eligibility_rechecks_receipt_and_original_handles(tmp_path, fault):
    scenario = CS_SETUP + r"""
$child=Start-Disposable '-B -c "import time; time.sleep(CHILD_DELAY); raise SystemExit(CHILD_CODE)"'
$runner=Start-Disposable '-B -c "import time; time.sleep(RUNNER_DELAY); raise SystemExit(RUNNER_CODE)"'
try {
    $identity['child_pid']=$child.Id.ToString();$identity['child_created']=(Created $child)
    $identity['runner_pid']=$runner.Id.ToString();$identity['runner_created']=(Created $runner)
    Set-Field 'child' $child;Set-Field 'runner' $runner;Set-Field 'identity' $identity
    Set-Field 'stopGate' ([object]::new());Set-Field 'terminal' $true
    $stopType=[Omi.OwnedShutdown.ProductionSession+StopEvidence]
    $stop=[Runtime.Serialization.FormatterServices]::GetUninitializedObject($stopType)
    $stopValues=@{RequestId=[Guid]::NewGuid().ToString('D');BeforePid=$child.Id;BeforeCreated=$session.ChildCreated;
        State='stopped';Reason='LIFESPAN_AND_EXACT_EXIT';ExactExit=$true;Rearmed=$false}
    foreach ($item in $stopValues.GetEnumerator()) { $stopType.GetProperty($item.Key).SetValue($stop,$item.Value,$null) }
    $stops=[Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new()
    $stops.Add($stop.RequestId,$stop);Set-Field 'stops' $stops
    Set-Field '<LastStop>k__BackingField' $stop
    $receipt=[Collections.Generic.Dictionary[string,string]]::new($identity)
    $receipt['request_id']=$stop.RequestId;$receipt['state']='SUCCEEDED_PRODUCTION'
    $receipt['reason']='LIFESPAN_AND_EXACT_EXIT';$receipt['no_respawn']='true'
    Set-Field 'confirmedStopReceipt' $receipt
    if ($fault -ne 'child-alive') { if (-not $child.WaitForExit(3000)) { throw 'FIXTURE_CHILD_TIMEOUT' } }
    if ($fault -ne 'runner-alive') { if (-not $runner.WaitForExit(3000)) { throw 'FIXTURE_RUNNER_TIMEOUT' } }
    switch ($fault) {
        'no-respawn' {$receipt['no_respawn']='false'}
        'receipt-uuid' {$receipt['request_id']=[Guid]::NewGuid().ToString('D')}
        'receipt-child' {$receipt['child_pid']='999'}
        'receipt-state' {$receipt['state']='UNKNOWN'}
        'receipt-reason' {$receipt['reason']='STOP_TIMEOUT'}
        'no-receipt' {Set-Field 'confirmedStopReceipt' $null}
        'child-created' {$identity['child_created']='wrong';$receipt['child_created']='wrong'}
        'runner-created' {$identity['runner_created']='wrong';$receipt['runner_created']='wrong'}
        'launcher-created' {$identity['launcher_created']='wrong';$receipt['launcher_created']='wrong'}
        'startup-failure' {Set-Field '<StartupFailure>k__BackingField' 'OWNED_START_UNKNOWN'}
        'rearmed' {$stopType.GetProperty('Rearmed').SetValue($stop,$true,$null)}
        'unknown' {$stopType.GetProperty('ExactExit').SetValue($stop,$false,$null)}
        'timeout' {$stopType.GetProperty('Reason').SetValue($stop,'STOP_TIMEOUT',$null)}
    }
    if ($session.CanStartAfterStop -ne ($fault -eq '')) { throw 'FALSE_RESTART_AUTHORITY' }
    if ($fault -eq '') {
        $session.DisposeAfterConfirmedStop()
        if ($session.CanStartAfterStop -or -not [object]::ReferenceEquals($stop,$session.LastStop) -or
            -not [object]::ReferenceEquals($stop,$session.Stop($stop.RequestId))) { throw 'RETIRED_RECEIPT_LOST' }
    } else {
        try {$session.DisposeAfterConfirmedStop();throw 'UNSAFE_DISPOSE'}
        catch {if ($_.Exception.Message -notmatch 'PREVIOUS_EXACT_STOP_NOT_ATTESTED') {throw}}
    }
} finally {
    if ($fault -ne '') {
        if (-not $child.WaitForExit(5000) -or -not $runner.WaitForExit(5000)) { throw 'FIXTURE_DID_NOT_EXIT' }
        $child.Dispose();$runner.Dispose()
    }
}
"""
    scenario = (f"$fault='{fault}'\n" + scenario
                .replace('CHILD_DELAY', '2' if fault == 'child-alive' else '.1')
                .replace('RUNNER_DELAY', '2' if fault == 'runner-alive' else '.1')
                .replace('CHILD_CODE', '7' if fault == 'child-code' else '0')
                .replace('RUNNER_CODE', '7' if fault == 'runner-code' else '0'))
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


def test_manual_start_has_only_one_factory_and_no_frontend_or_legacy_dispatch():
    source = (Path(__file__).resolve().parents[2] / 'scripts/omi-launcher.ps1').read_text(encoding='utf-8-sig')
    body = source.split('function Start-OmiBackendAfterExactStop {', 1)[1].split('\nfunction ', 1)[0]
    assert body.count('New-OmiProductionOwnedBackend') == 1
    for forbidden in ('Start-Process', 'Start-Backend\n', 'Start-Services', 'Start-Frontend', 'Stop-Frontend',
                      'Stop-Legacy', 'Stop-Process', 'TakePending', '$script:SafeStopAttempted = $false'):
        assert forbidden not in body
    assert body.index('DisposeAfterConfirmedStop') < body.index('New-OmiProductionOwnedBackend')
    assert body.index('Test-TcpPortBindable') < body.index('$script:RetiredBackendSessions.Add') < body.index('DisposeAfterConfirmedStop')
    bind = source.split('function Test-TcpPortBindable {', 1)[1].split('\nfunction ', 1)[0]
    assert '$listener.Stop()' in bind.split('finally {', 1)[1]
    assert body.index('$script:OwnedBackendSession = $next') < body.index('WaitForStartReadinessAsync')
    assert body.index('GetAwaiter().GetResult()') < body.index('return $identity')
    manual = source.split('function Invoke-BackendStartRequest {', 1)[1].split('\nfunction ', 1)[0]
    assert manual.index('Start-OmiBackendAfterExactStop') < manual.index("Write-LauncherLog 'Backend started")


def test_missing_port_inspector_is_unknown_and_never_port_free(tmp_path):
    scenario = r"""
$definition=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-ListeningProcessIdsOnPort'},$false)
. ([scriptblock]::Create($definition.Extent.Text))
function Test-Path { return $false }
try {Get-ListeningProcessIdsOnPort -Port 8401 -RequireObservation;throw 'UNKNOWN_PORT_ACCEPTED'}
catch {if ($_.Exception.Message -ne 'PORT_OBSERVATION_UNAVAILABLE') {throw}}
"""
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


def test_status_publisher_tracks_new_generation_and_keeps_old_queue_fenced(tmp_path):
    result = _run_isolated_launcher(tmp_path, START_SETUP + r"""
$controlAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1'),[ref]$null,[ref]$null)
$publish=$controlAst.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Publish-OmiRuntimeControlStatus'},$false)
. ([scriptblock]::Create($publish.Extent.Text))
$script:RuntimeController | Add-Member ScriptMethod Publish {
    param($json,$identity,$attested)
    $status=$json | ConvertFrom-Json
    if ($status.backend.status -ne $script:ExpectedStatus -or
        $status.restart.available -ne ($script:ExpectedStatus -eq 'observed')) {throw 'FALSE_PUBLISHED_STATE'}
    if ($script:ExpectedStatus -eq 'stopped') {
        if ($attested -or $null -ne $identity) {throw 'STOPPED_IDENTITY_ADOPTED'}
    } elseif ($status.backend.pid -ne $script:OwnedBackendSession.ChildPid) {throw 'OLD_GENERATION_PUBLISHED'}
    $script:Calls.Add('checked-publish')
}
$script:ExpectedStatus='observed'
$startBackendItem.PerformClick()
$first=$script:OwnedBackendSession
Stop-Services -BackendOnly
$script:ExpectedStatus='stopped';$script:RuntimeControlLastPublish=[DateTime]::MinValue
Invoke-OmiRuntimeControlTick
$script:Ready=$false
$startBackendItem.PerformClick()
if (-not [object]::ReferenceEquals($first,$script:ManualBackendStartAttemptedSession) -or
    [object]::ReferenceEquals($first,$script:OwnedBackendSession)) {throw 'ATTEMPT_GENERATION_WRONG'}
$script:ExpectedStatus='unknown';$script:RuntimeControlLastPublish=[DateTime]::MinValue
Invoke-OmiRuntimeControlTick
Stop-Services -BackendOnly
if ($script:LastBackendStartError) {throw 'STOP_DID_NOT_RESOLVE_START_STATUS'}
$script:ExpectedStatus='observed';$script:Ready=$true
$startBackendItem.PerformClick()
Assert-StartResources
if ($script:SpawnCount -ne 3 -or $script:RetiredBackendSessions.Count -ne 3) {throw 'NEXT_GENERATION_BLOCKED'}
""")
    assert result['calls'].count('checked-publish') == 4
    assert 'queue' not in result['calls']
    assert not any('tick failed closed' in line for line in result['logs'])


@pytest.mark.parametrize('terminal', [False, True])
def test_status_timer_cannot_show_api_ok_from_unrelated_http_or_failed_start(tmp_path, terminal):
    result = _run_isolated_launcher(tmp_path, START_SETUP + r"""
function Get-ExitedProcessCode {return $null}
function Test-HttpOk {return $true}
function Test-FrontendOk {return $true}
$script:OwnedBackendSession.Terminal=TERMINAL
$script:LastBackendStartError='BACKEND_START_UNCONFIRMED'
$script:StatusItem=[pscustomobject]@{Text=''}
$script:NotifyIcon=[pscustomobject]@{Text=''}
$script:LastStatusText=$null
$script:AppDisplayName='OMI'
$script:FrontendHealthRecoveryAttempts=0
$tick=$ast.Find({param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and
    $n.Member.Value -eq 'add_Tick' -and $n.Expression.Extent.Text -eq '$script:Timer'},$true)
& $tick.Arguments[0].ScriptBlock.GetScriptBlock()
if ($script:StatusItem.Text -match 'API OK' -or $script:StatusItem.Text -notmatch 'API start unconfirmed') {throw 'FALSE_TIMER_SUCCESS'}
""".replace('TERMINAL', '$true' if terminal else '$false'))
    assert not result['calls']


def test_real_stop_reducer_retains_success_receipt_for_retirement(tmp_path):
    runner = tmp_path / 'stop_receipt.py'
    runner.write_text('''import json, sys, time
request = json.loads(sys.stdin.readline())
time.sleep(.3)
request.update(state='SUCCEEDED_PRODUCTION', reason='LIFESPAN_AND_EXACT_EXIT', no_respawn='true')
print(json.dumps(request), flush=True)
''', encoding='utf-8')
    scenario = CS_SETUP + r"""
$child=Start-Disposable '-B -c "import time; time.sleep(.2)"'
$runner=Start-Disposable '-B "RUNNER"'
try {
    $identity['child_pid']=$child.Id.ToString();$identity['child_created']=(Created $child)
    $identity['runner_pid']=$runner.Id.ToString();$identity['runner_created']=(Created $runner)
    Set-Field 'child' $child;Set-Field 'runner' $runner;Set-Field 'identity' $identity
    Set-Field 'stopGate' ([object]::new())
    Set-Field 'stops' ([Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new())
    $receipt=$session.Stop([Guid]::NewGuid().ToString('D'))
    if (-not $receipt.ExactExit -or -not $session.CanStartAfterStop) {throw 'REAL_STOP_RECEIPT_NOT_USABLE'}
    $session.DisposeAfterConfirmedStop()
    if (-not [object]::ReferenceEquals($receipt,$session.LastStop)) {throw 'RECEIPT_LOST'}
} finally {
    if (-not $receipt.ExactExit) {
        $runner.StandardInput.Close()
        if (-not $runner.WaitForExit(3000) -or -not $child.WaitForExit(3000)) {throw 'FIXTURE_TIMEOUT'}
        $runner.Dispose();$child.Dispose()
    }
}
""".replace('RUNNER', str(runner))
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


READINESS_SERVER = '''import json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
fault = sys.argv[1]
status_calls = 0
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        global status_calls
        code = 200
        if self.path == '/api/system/runtime-control/status':
            status_calls += 1
            owned = dict(identity)
            if fault in ('pid', 'instance', 'release'):
                owned[{'pid':'child_pid','instance':'instance','release':'release_id'}[fault]] = 'wrong'
            if fault == 'changed-after-ready' and status_calls >= 2: owned['instance'] = 'wrong'
            value = {'serving_backend': {'runtime_started': True, 'owned_start': owned}}
        elif self.path == '/api/system/readyz':
            value = {'status':'ready','checks':{'runtime':'ok','database':'ok'}}
            if fault == '503': code = 503
            if fault == 'database': value['checks']['database'] = 'not_ready'
            if fault == 'unrelated': value = {'status':'ok'}
            if fault == 'slow': time.sleep(1.5)
        else: raise AssertionError('unexpected fixture path')
        data = json.dumps(value).encode()
        try:
            self.send_response(code); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
assert server.server_port not in (8400, 3000)
print(server.server_port, flush=True)
identity = json.loads(sys.stdin.readline())
threading.Thread(target=server.serve_forever, daemon=True).start()
sys.stdin.readline()
server.shutdown(); server.server_close()
'''


@pytest.mark.parametrize('fault', ['normal', 'pid', 'instance', 'release', 'changed-after-ready',
                                  '503', 'database', 'unrelated', 'slow', 'source-drift'])
def test_csharp_readiness_requires_exact_serving_identity_and_real_readyz(tmp_path, fault):
    # A private ephemeral loopback HTTP fixture, never OMI ports or app imports.
    server = tmp_path / 'readiness_fixture.py'
    server.write_text(READINESS_SERVER, encoding='utf-8')
    app = tmp_path / 'backend/app'
    app.mkdir(parents=True)
    (app / 'fixture.py').write_text('# fixture source\n', encoding='utf-8')
    scenario = CS_SETUP + r"""
$child=Start-Disposable '-B "SERVER" FAULT'
$runner=Start-Disposable '-B -c "import sys; sys.stdin.readline()"'
try {
    $selected=[int]$child.StandardOutput.ReadLine()
    if ($selected -in @(8400,3000)) {throw 'PRODUCTION_PORT_FORBIDDEN'}
    $identity['child_pid']=$child.Id.ToString();$identity['child_created']=(Created $child)
    $identity['runner_pid']=$runner.Id.ToString();$identity['runner_created']=(Created $runner)
    $identity['port']=$selected.ToString()
    $release=[Omi.OwnedShutdown.ProductionSession]::ApplicationRelease('ROOT')
    $identity['release_id']=$release
    Set-Field 'child' $child;Set-Field 'runner' $runner;Set-Field 'identity' $identity
    Set-Field 'repo' 'ROOT';Set-Field 'host' '127.0.0.1';Set-Field 'port' $selected;Set-Field 'release' $release
    $child.StandardInput.WriteLine(($identity | ConvertTo-Json -Compress));$child.StandardInput.Flush()
    if ('FAULT' -eq 'source-drift') { [IO.File]::AppendAllText('ROOT/backend/app/fixture.py','# changed') }
    $clock=[Diagnostics.Stopwatch]::StartNew()
    $ok=$session.WaitForStartReadinessAsync(650).GetAwaiter().GetResult()
    if ($ok -ne ('FAULT' -eq 'normal') -or $session.StartReadinessVerified -ne $ok -or $clock.ElapsedMilliseconds -gt 2500 -or
        -not $session.Alive -or $null -ne $session.LastStop -or $session.SelectedPort -ne $selected) {throw 'READINESS_PROOF_OR_BUDGET_BROKEN'}
} finally {
    $child.StandardInput.Close();$runner.StandardInput.Close()
    if (-not $child.WaitForExit(4000) -or -not $runner.WaitForExit(4000)) {throw 'FIXTURE_DID_NOT_EXIT'}
    $child.Dispose();$runner.Dispose()
}
""".replace('SERVER', str(server)).replace('ROOT', str(tmp_path)).replace('FAULT', fault)
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


RESTART_SETUP = START_SETUP + r"""
$script:RuntimeControlLastPublish=[DateTime]::UtcNow
$script:OwnedBackendRestartRequests=[Collections.Generic.HashSet[string]]::new()
$script:SafeStopAttempted=$false
$script:OldReady=$true
$script:RemoteIntentAccepted=$true
$script:StopMode='exact'
$script:RestartIds=[Collections.Generic.List[string]]::new()
$script:BaseFakeOwned=(Get-Item Function:New-FakeOwned).ScriptBlock
function New-FakeOwned {
    $result=& $script:BaseFakeOwned
    $result.ChildCreated='created-'+$script:SpawnCount
    $result | Add-Member ScriptMethod VerifyReadiness {return $script:OldReady}
    $result | Add-Member -Force ScriptMethod StopAsync {
        param($request)
        if ($script:Timer.Enabled -or $script:ActivationTimer.Enabled -or (-not $script:ServiceStartRequestInProgress -and -not $script:ServiceStopInProgress)) {throw 'STOP_NOT_SERIALIZED'}
        $script:Calls.Add('backend-stop'); $script:RestartIds.Add($request)
        try {Invoke-OwnedBackendRestart -RequestId $request;throw 'REENTRY_ACCEPTED'}
        catch {if ($_.Exception.Message -ne 'SERVICE_OPERATION_IN_PROGRESS') {throw}}
        $exact=$script:StopMode -eq 'exact';$rearmed=$script:StopMode -eq 'rearmed'
        $this.LastStop=[pscustomobject]@{RequestId=$request; BeforePid=$this.ChildPid; BeforeCreated=$this.ChildCreated;
            State=$(if($exact){'stopped'}elseif($rearmed){'blocked'}else{'unknown'});
            Reason=$(if($exact){'LIFESPAN_AND_EXACT_EXIT'}elseif($rearmed){'PREFLIGHT_REARMED'}else{'STOP_TIMEOUT'});
            ExactExit=$exact;Rearmed=$rearmed;PreflightStage=$(if($rearmed){'SCHEDULER_QUIESCENCE'}else{''})}
        $this.CanStartAfterStop=$exact;$this.Terminal=-not $rearmed;$this.Alive=-not $exact
        $task=[Threading.Tasks.TaskCompletionSource[object]]::new();$task.SetResult($this.LastStop);return $task.Task
    }
    return $result
}
$script:OwnedBackendSession=New-FakeOwned
$script:BackendProcess=$script:OwnedBackendSession.RunnerProcess
$original=$script:OwnedBackendSession
$script:RuntimeController | Add-Member ScriptMethod BeginAuthenticatedOwnedRestart {
    param($id,$identity)
    $script:Calls.Add('authenticated-intent')
    if ($identity.pid -ne $script:OwnedBackendSession.ChildPid -or $script:Timer.Enabled) {throw 'UNBOUND_APPROVAL'}
    return $script:RemoteIntentAccepted
}
$script:RuntimeController | Add-Member ScriptMethod CompleteOwnedRestart {
    param($id,$stop,$next,$verified)
    $script:Calls.Add('receipt')
    if ($id -ne $stop.RequestId) {throw 'REQUEST_ID_CHANGED'}
    $script:RemoteCompleted=($null -ne $verified -and $null -ne $next -and $verified.pid -eq $next.ChildPid)
    $script:RemoteStage=$stop.PreflightStage
}
$script:RuntimeController | Add-Member ScriptMethod BlockOwnedRestart {param($id,$reason);$script:Calls.Add('blocked')}
foreach ($statement in @($ast.EndBlock.Statements | Where-Object {
    $_.Extent.Text -match '^\$restartBackendItem\b' -or
    $_.Extent.Text -eq '[void]$script:Menu.MenuItems.Add($restartBackendItem)'
})) { . ([scriptblock]::Create($statement.Extent.Text)) }
if ($restartBackendItem.Text -ne 'Restart Backend') {throw 'RESTART_MENU_MISSING'}
"""


def test_tray_restart_then_fresh_remote_generation_and_another_local_cycle(tmp_path):
    result = _run_isolated_launcher(tmp_path, RESTART_SETUP + r"""
$restartBackendItem.PerformClick()
if ($script:LastBackendRestart.State -ne 'succeeded' -or -not $script:SafeStopAttempted) {throw 'LOCAL_FAILED_OR_LEGACY_UNLOCKED'}
$firstReceipt=$original.LastStop
$script:FreshRequest=[Guid]::NewGuid().ToString('D')
$script:RuntimeController | Add-Member -Force ScriptMethod TakePending {
    $id=$script:FreshRequest;$script:FreshRequest=$null;return $id
}
Invoke-OmiRuntimeControlTick
if (-not $script:RemoteCompleted -or $script:SpawnCount -ne 2) {throw 'FRESH_GENERATION_BLOCKED'}
$restartBackendItem.PerformClick()
if ($script:SpawnCount -ne 3 -or $script:RetiredBackendSessions.Count -ne 3 -or
    -not [object]::ReferenceEquals($firstReceipt,$original.LastStop) -or
    -not [object]::ReferenceEquals($frontend,$script:FrontendProcess)) {throw 'OWNER_OR_FRONTEND_LOST'}
foreach ($id in $script:RestartIds) {
    try {Invoke-OwnedBackendRestart -RequestId $id;throw 'DUPLICATE_EXECUTED'}
    catch {if ($_.Exception.Message -ne 'BACKEND_RESTART_NO_REPLAY') {throw}}
}
if ($script:SpawnCount -ne 3 -or [System.Windows.Forms.Application]::Exits -or
    -not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled) {throw 'REPLAY_OR_OWNER_RELEASE'}
""")
    assert result['calls'].count('backend-stop') == 3
    assert result['calls'].count('factory') == 3
    assert result['calls'].count('authenticated-intent') == result['calls'].count('receipt') == 1


@pytest.mark.parametrize('mode', ['rearmed', 'unknown'])
def test_restart_stop_refusal_never_starts_and_preserves_stage_and_remote_fence(tmp_path, mode):
    result = _run_isolated_launcher(tmp_path, RESTART_SETUP + f"$script:StopMode='{mode}'\n" + r"""
$id=[Guid]::NewGuid().ToString('D')
try {Restart-Backend -RequestId $id} catch {}
if ($script:SpawnCount -or -not [object]::ReferenceEquals($original,$script:OwnedBackendSession) -or
    $script:RemoteCompleted -or (Test-OmiRemoteRestartGeneration)) {throw 'UNCONFIRMED_RESTART_ESCAPED'}
if ($script:StopMode -eq 'rearmed' -and ($script:RemoteStage -ne 'SCHEDULER_QUIESCENCE' -or
    $script:LastBackendRestart.PreflightStage -ne 'SCHEDULER_QUIESCENCE')) {throw 'STAGE_LOST'}
try {Restart-Backend -RequestId $id} catch {}
Invoke-OmiRuntimeControlTick
if ($script:RestartIds.Count -ne 1) {throw 'UNKNOWN_REPLAY'}
""")
    assert result['calls'].count('backend-stop') == 1
    assert 'factory' not in result['calls']


@pytest.mark.parametrize('fault,spawned', [
    ('$script:Ready=$false', True), ('$script:StartupFailure=$true', True),
    ('$script:FactoryFailure=$true', False), ('$script:DisposeFailure=$true', False),
    ('$script:DriftDuringReadiness=$true', True),
])
def test_restart_failure_keeps_original_receipt_and_tracked_successor_without_retry(tmp_path, fault, spawned):
    result = _run_isolated_launcher(tmp_path, RESTART_SETUP + fault + r"""
$id=[Guid]::NewGuid().ToString('D')
try {Restart-Backend -RequestId $id} catch {}
if ($script:RemoteCompleted -or $script:LastBackendRestart.State -eq 'succeeded' -or
    -not $original.LastStop.ExactExit -or $script:RetiredBackendSessions.Count -ne 1) {throw 'FALSE_SUCCESS_OR_LOST_OLD'}
if (-not [object]::ReferenceEquals(EXPECTED,$script:OwnedBackendSession)) {throw 'TRACKED_SESSION_LOST'}
$attempts=$script:SpawnCount
try {Restart-Backend -RequestId $id} catch {}
Invoke-OmiRuntimeControlTick
try {Invoke-OwnedBackendRestart -RequestId ([Guid]::NewGuid().ToString('D'))} catch {}
if ($script:SpawnCount -ne $attempts -or $script:RestartIds.Count -ne 1 -or
    -not [object]::ReferenceEquals($frontend,$script:FrontendProcess)) {throw 'RETRY_OR_FRONTEND_MUTATION'}
""".replace('EXPECTED', '$script:CreatedSession' if spawned else '$original'))
    assert result['calls'].count('backend-stop') == 1
    assert result['calls'].count('receipt') == 1


@pytest.mark.parametrize('fault', ['$script:RemoteIntentAccepted=$false', '$script:WrongIdentity=$true',
                                  '$script:OwnsMutex=$false', "$script:DiskSource='changed'",
                                  '$script:OldReady=$false'])
def test_restart_preconditions_and_remote_intent_refusal_do_not_stop(tmp_path, fault):
    result = _run_isolated_launcher(tmp_path, RESTART_SETUP + fault + r"""
try {Restart-Backend -RequestId ([Guid]::NewGuid().ToString('D'))} catch {}
if ($script:SpawnCount -or $script:RestartIds.Count -or $script:RetiredBackendSessions.Count) {throw 'UNAUTHORIZED_SIDE_EFFECT'}
""")
    assert 'backend-stop' not in result['calls'] and 'factory' not in result['calls']


def test_manual_safe_stop_unknown_cannot_admit_remote_intent(tmp_path):
    result = _run_isolated_launcher(tmp_path, RESTART_SETUP + r"""
$restartBackendItem.PerformClick()
$script:StopMode='unknown'
try {Stop-Services -BackendOnly} catch {}
$attempts=$script:SpawnCount;$stops=$script:RestartIds.Count
try {Restart-Backend -RequestId ([Guid]::NewGuid().ToString('D'))} catch {}
Invoke-OmiRuntimeControlTick
if ((Test-OmiRemoteRestartGeneration) -or $script:SpawnCount -ne $attempts -or $script:RestartIds.Count -ne $stops) {throw 'UNKNOWN_MANUAL_STOP_RESTARTED'}
""")
    assert 'authenticated-intent' not in result['calls']



def test_controller_public_dispatch_cannot_mint_remote_intent(tmp_path):
    # Real OS-authenticated pipe admission is tested by test-omi-runtime-control.ps1.
    # Direct fixture Dispatch cannot attest the backend pipe peer.
    scenario = r"""
$dir=Split-Path $ast.Extent.File
Add-Type -Path @((Join-Path $dir 'OmiOwnedShutdown.cs'),(Join-Path $dir 'OmiRuntimeControl.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
$token='a'*64;$sha=[Security.Cryptography.SHA256]::Create()
try {$hash=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($token))).Replace('-','').ToLowerInvariant()}
finally {$sha.Dispose()}
$controller=[Omi.RuntimeControl.Controller]::new('STORE',$hash,'unbound-offline-fixture')
function Identity($pidValue,$created) {$value=[Omi.RuntimeControl.Identity]::new();$value.pid=$pidValue;$value.created_at=$created;return $value}
function Request($id,$ownerId,$preflight) {
    $doc=@{action='RestartBackend';request_id=$id;expected_owner_id=$ownerId;token=$token}
    if ($preflight) {
        $doc.backend_preflight=@{schema='omi.restart-preflight.v1';runtime_started=$true;
            registered_drain_state='NOT_REQUESTED';all_writers_drained=$false;unknown_writer_count=3}|ConvertTo-Json -Compress
    }
    return $controller.Dispatch(($doc|ConvertTo-Json -Compress))|ConvertFrom-Json
}
try {
    $old=Identity 100 '2026-10-16T01:00:00Z'
    $controller.Publish('{"restart":{"available":true}}',$old,$true)
    foreach($preflight in @($false,$true)) {
        $id=[Guid]::NewGuid().ToString('D')
        $result=Request $id $controller.OwnerId $preflight
        if ($result.state -ne 'blocked' -or $result.reason -ne 'BACKEND_PREFLIGHT_NOT_ATTESTED' -or
            $null -ne $controller.TakePending() -or $controller.BeginAuthenticatedOwnedRestart($id,$old)) {
            throw 'UNBOUND_DISPATCH_ADMITTED_RESTART'
        }
        if ((Request $id $controller.OwnerId $preflight).updated_at -ne $result.updated_at) {
            throw 'BLOCKED_UUID_REPLAYED'
        }
    }
    $current=Identity 200 '2026-10-16T02:00:00Z'
    $controller.Publish('{"restart":{"available":true}}',$current,$true)
    $id=[Guid]::NewGuid().ToString('D')
    if ((Request $id $controller.OwnerId $true).state -ne 'blocked') {throw 'GENERATION_WITHOUT_PIPE_ACCEPTED'}
    $controller.Publish('{"restart":{"available":false}}',$current,$true)
    if ((Request ([Guid]::NewGuid().ToString('D')) $controller.OwnerId $true).reason -ne 'ALL_WRITERS_DRAIN_UNAVAILABLE') {throw 'STOP_FENCE_BYPASSED'}
    if ((Request ([Guid]::NewGuid().ToString('D')) ([Guid]::NewGuid().ToString('D')) $true).reason -ne 'OWNER_MISMATCH') {throw 'WRONG_OWNER_ADMITTED'}
} finally {$controller.Dispose()}
""".replace('STORE', str(tmp_path / 'controller-store').replace("'", "''"))
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']

@pytest.mark.parametrize('fault', ['normal', 'identity-only', 'wrong-final-identity', 'stale-ready', 'rearmed'])
def test_controller_success_requires_full_readiness_final_identity_and_exact_stop(tmp_path, fault):
    # Controller/ProductionSession reducers with disposable retained processes.
    # Exercise real authenticated pipe admission; retained child/runner evidence is disposable.
    setup = CS_SETUP.replace("Add-Type -Path (Join-Path (Split-Path $ast.Extent.File) 'OmiOwnedShutdown.cs') -ReferencedAssemblies @('System.Web.Extensions','System.Core')",
        "Add-Type -Path @((Join-Path (Split-Path $ast.Extent.File) 'OmiOwnedShutdown.cs'),(Join-Path (Split-Path $ast.Extent.File) 'OmiRuntimeControl.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')")
    scenario=setup+r"""
$child=Start-Disposable '-B -c "import sys; sys.stdin.readline()"'
$runner=Start-Disposable '-B -c "import sys; sys.stdin.readline()"'
$token='a'*64;$sha=[Security.Cryptography.SHA256]::Create()
try {$hash=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($token))).Replace('-','').ToLowerInvariant()}
finally {$sha.Dispose()}
$pipeName='omi-disposable-' + [Guid]::NewGuid().ToString('N')
$controller=[Omi.RuntimeControl.Controller]::new('STORE',$hash,$pipeName)
try {
    $identity['child_pid']=$child.Id.ToString();$identity['child_created']=(Created $child)
    $identity['runner_pid']=$runner.Id.ToString();$identity['runner_created']=(Created $runner)
    Set-Field 'child' $child;Set-Field 'runner' $runner;Set-Field 'identity' $identity;Set-Field 'release' ('f'*64)
    Set-Field 'readinessVerifiedAt' ([DateTime]::UtcNow)
    if ('FAULT' -ne 'identity-only') {Set-Field 'startReadinessVerifiedAt' ([DateTime]::UtcNow)}
    if ('FAULT' -eq 'stale-ready') {Set-Field 'startReadinessVerifiedAt' ([DateTime]::UtcNow.AddSeconds(-10))}
    $before=[Omi.RuntimeControl.Identity]::new();$before.pid=$PID;$before.created_at=$owner.StartTime.ToUniversalTime().ToString('o')
    $controller.Publish('{"restart":{"available":true}}',$before,$true)
    $controller.Start()
    $id=[Guid]::NewGuid().ToString('D')
    $preflight=@{schema='omi.restart-preflight.v1';runtime_started=$true;
        registered_drain_state='NOT_REQUESTED';all_writers_drained=$false;unknown_writer_count=3}|ConvertTo-Json -Compress
    $request=@{action='RestartBackend';request_id=$id;expected_owner_id=$controller.OwnerId;token=$token;
        backend_preflight=$preflight}|ConvertTo-Json -Compress
    $client=[IO.Pipes.NamedPipeClientStream]::new('.', $pipeName, [IO.Pipes.PipeDirection]::InOut)
    try {
        $client.Connect(1500)
        $writer=[IO.StreamWriter]::new($client);$writer.AutoFlush=$true
        $reader=[IO.StreamReader]::new($client)
        $writer.WriteLine($request)
        $accepted=$reader.ReadLine()|ConvertFrom-Json
        if ($accepted.state -ne 'accepted' -or $null -ne $accepted.local_approval) {throw 'AUTHENTICATED_PIPE_NOT_ACCEPTED'}
    } finally {$client.Dispose()}
    if ($controller.TakePending() -ne $id -or -not $controller.BeginAuthenticatedOwnedRestart($id,$before)) {
        throw 'AUTHENTICATED_INTENT_NOT_CONSUMED'
    }
    $stopType=[Omi.OwnedShutdown.ProductionSession+StopEvidence]
    $stop=[Runtime.Serialization.FormatterServices]::GetUninitializedObject($stopType)
    foreach($entry in @{RequestId=$id;BeforePid=$before.pid;BeforeCreated=$before.created_at;State='stopped';
        Reason='LIFESPAN_AND_EXACT_EXIT';ExactExit=$true;Rearmed=('FAULT' -eq 'rearmed');PreflightStage='SCHEDULER_QUIESCENCE'}.GetEnumerator()) {
        $stopType.GetProperty($entry.Key).SetValue($stop,$entry.Value,$null)
    }
    $verified=[Omi.RuntimeControl.Identity]::new();$verified.pid=$session.ChildPid;$verified.created_at=$session.ChildCreated
    $controller.Publish('{"restart":{"available":true}}',$verified,$true)
    if ('FAULT' -eq 'wrong-final-identity') {$verified.pid=1}
    $controller.CompleteOwnedRestart($id,$stop,$session,$verified)
    $receipt=$controller.Dispatch($request)|ConvertFrom-Json
    if (($receipt.state -eq 'succeeded') -ne ('FAULT' -eq 'normal')) {throw 'FALSE_DURABLE_SUCCESS'}
    if ('FAULT' -eq 'rearmed' -and ($receipt.state -ne 'blocked' -or $receipt.preflight_stage -ne 'SCHEDULER_QUIESCENCE')) {throw 'REARM_STAGE_LOST'}
    if (($controller.Dispatch($request)|ConvertFrom-Json).updated_at -ne $receipt.updated_at) {throw 'RECEIPT_REPLAY'}
} finally {
    $controller.Dispose();$child.StandardInput.Close();$runner.StandardInput.Close()
    if (-not $child.WaitForExit(3000) -or -not $runner.WaitForExit(3000)) {throw 'FIXTURE_DID_NOT_EXIT'}
    $child.Dispose();$runner.Dispose()
}
"""
    scenario=scenario.replace('FAULT',fault).replace('STORE', str(tmp_path / 'controller-store').replace("'", "''"))
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']
