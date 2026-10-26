"""Failed-start recovery uses disposable handles and the real owner reducers only."""
import pytest

from test_owned_lifecycle_convergence import CS_SETUP
from test_runtime_launcher_recovery import _run_isolated_launcher
from test_launcher_backend_start import START_SETUP


RECOVERY_CS = CS_SETUP + r'''
$child=Start-Disposable '-B -c "import time; time.sleep(.15); raise SystemExit(1)"'
$runner=Start-Disposable '-B -c "import time; time.sleep(.2); raise SystemExit(79)"'
try {
    $identity['child_pid']=$child.Id.ToString(); $identity['child_created']=(Created $child)
    $identity['runner_pid']=$runner.Id.ToString(); $identity['runner_created']=(Created $runner)
    $identity['journal']='JOURNAL'
    Set-Field 'child' $child; Set-Field 'runner' $runner; Set-Field 'identity' $identity
    Set-Field 'stopGate' ([object]::new())
    Set-Field 'stops' ([Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new())
    $wire=$type.Assembly.GetType('Omi.OwnedShutdown.Wire')
    $wire.GetMethod('PrivateDirectory').Invoke($null,@('JOURNAL',$true))
    $receipt=[Collections.Generic.Dictionary[string,string]]::new($identity)
    $receipt['state']='START_FAILED'; $receipt['reason']='OWNED_START_EXIT_CONFIRMED'
    $receipt['child_exact_exit']='true'; $receipt['child_exit_code']='1'
    $persist=[Omi.OwnedShutdown.Runner].GetMethod('Persist',[Reflection.BindingFlags]'Static,NonPublic')
    $persist.Invoke($null,@('JOURNAL','startup-failure.json',$receipt))
    if (-not $type.GetMethod('ConfirmStartupExit',$flags).Invoke($session,@($receipt))) { throw 'FIXTURE_NOT_CONFIRMED' }
    $before=[IO.File]::ReadAllBytes('JOURNAL/startup-failure.json')
    if ($session.CanStartAfterStop -or $session.LastStop) { throw 'FAILURE_IS_NOT_STOP' }
    FAULT
    if ($session.CanRecoverFailedStart -ne EXPECTED) { throw 'FAILED_START_RECOVERY_GATE' }
    CHECK
} finally {
    if (-not $child.WaitForExit(4000) -or -not $runner.WaitForExit(4000)) { throw 'FIXTURE_EXIT_UNKNOWN' }
    $child.Dispose(); $runner.Dispose()
}
'''


def test_failed_start_has_separate_recovery_authority(tmp_path):
    script = RECOVERY_CS.replace('JOURNAL', str(tmp_path / 'journal')).replace('FAULT', '').replace('EXPECTED', '$true').replace('CHECK', '')
    assert not _run_isolated_launcher(tmp_path, script)['calls']


@pytest.mark.parametrize('mode', ['child-live', 'runner-live', 'child-zero'])
def test_recovery_requires_both_exact_terminal_exits(tmp_path, mode):
    script = RECOVERY_CS.replace('FAULT', '').replace('EXPECTED', '$false').replace('CHECK', '')
    if mode == 'child-zero':
        script = script.replace('SystemExit(1)', 'SystemExit(0)').replace("['child_exit_code']='1'", "['child_exit_code']='0'")
    else:
        script = script.replace('time.sleep(.15)' if mode == 'child-live' else 'time.sleep(.2)', 'time.sleep(3)')
        script = script.replace("if (-not $type.GetMethod('ConfirmStartupExit',$flags).Invoke($session,@($receipt))) { throw 'FIXTURE_NOT_CONFIRMED' }", r'''
    Set-Field 'failedStartupReceipt' $receipt
    Set-Field '<StartupFailure>k__BackingField' 'OWNED_START_EXIT_CONFIRMED'
    Set-Field '<StartupExitConfirmed>k__BackingField' $true
    Set-Field 'terminal' $true
''')
    assert not _run_isolated_launcher(tmp_path, script.replace('JOURNAL', str(tmp_path / 'journal')))['calls']


@pytest.mark.parametrize('fault', [
    "Set-Field 'child' $null", "Set-Field 'runner' $null",
    "$identity['child_created']='recycled'", "$identity['runner_created']='recycled'",
    "$identity['launcher_created']='other-owner'", "$identity['launcher_pid']='0'",
    "Set-Field 'terminal' $false", "Set-Field '<StartupFailure>k__BackingField' 'OWNED_START_UNKNOWN'",
    "Set-Field '<StartupExitConfirmed>k__BackingField' $false",
    "Set-Field 'failedStartupReceipt' $null", "Set-Field 'retirementAttempted' $true",
    "Set-Field 'failedStartRecoveryAttempted' $true", "Set-Field 'cutoffStarted' $true",
    "Set-Field 'readinessVerifiedAt' ([DateTime]::UtcNow)",
    "$proof=$type.GetField('failedStartupReceipt',$flags).GetValue($session);$proof['child_exit_code']='unknown'",
    "$proof=$type.GetField('failedStartupReceipt',$flags).GetValue($session);$proof['instance']='replayed'",
    "$proof=$type.GetField('failedStartupReceipt',$flags).GetValue($session);$proof['child_exact_exit']='false'",
    "[IO.File]::Move('JOURNAL/startup-failure.json','JOURNAL/preserved.json')",
    "[IO.File]::WriteAllText('JOURNAL/startup-failure.json','{}')",
    "$lock=[IO.File]::Open('JOURNAL/startup-failure.json','Open','ReadWrite','None')",
])
def test_failed_start_recovery_unknowns_refuse(tmp_path, fault):
    check = r'''
    try { $session.RetireFailedStart([Guid]::NewGuid().ToString('D'),'unused'); throw 'UNSAFE_RETIRE' }
    catch { if ($_.Exception.Message -notmatch 'FAILED_START_RECOVERY_NOT_ATTESTED') { throw } }
    if ($lock) { $lock.Dispose() }
    if (-not $session.StartupFailure -or $session.LastStop) { throw 'ORIGINAL_FAILURE_LOST' }
'''
    script = RECOVERY_CS.replace('FAULT', fault).replace('EXPECTED', '$false').replace('CHECK', check).replace('JOURNAL', str(tmp_path / 'journal'))
    assert not _run_isolated_launcher(tmp_path, script)['calls']


@pytest.mark.parametrize('mode', ['success', 'old-uuid', 'source-drift', 'journal-conflict'])
def test_retirement_consumes_once_preserves_failure_and_persisted_bytes(tmp_path, mode):
    app = tmp_path / 'backend/app'
    app.mkdir(parents=True)
    (app / 'fixture.py').write_text('# isolated source\n')
    check = r'''
    Set-Field 'repo' 'ROOT'
    $pin=[Omi.OwnedShutdown.ProductionSession]::ApplicationRelease('ROOT')
    $id=[Guid]::NewGuid().ToString('D')
    if ('MODE' -eq 'old-uuid') { $id=$identity['instance'] }
    if ('MODE' -eq 'source-drift') { [IO.File]::AppendAllText('ROOT/backend/app/fixture.py','# drift') }
    if ('MODE' -eq 'journal-conflict') { [IO.File]::WriteAllText('JOURNAL/failed-start-recovery.json','existing') }
    try {
        $session.RetireFailedStart($id,$pin)
        if ('MODE' -ne 'success') { throw 'UNSAFE_RETIRE' }
    } catch {
        if ('MODE' -eq 'success') { throw }
        if ('MODE' -eq 'source-drift' -and $_.Exception.Message -notmatch 'RESTART_SOURCE_CHANGED') { throw }
        if ('MODE' -eq 'old-uuid' -and $_.Exception.Message -notmatch 'FAILED_START_RECOVERY_REPLAY') { throw }
    }
    if ('MODE' -in @('success','journal-conflict')) {
        if ($session.CanRecoverFailedStart) { throw 'REPLAY_ENABLED' }
        try { $session.RetireFailedStart([Guid]::NewGuid().ToString('D'),$pin);throw 'REPLAY' }
        catch { if ($_.Exception.Message -notmatch 'FAILED_START_RECOVERY_NOT_ATTESTED') { throw } }
    }
    if ($session.StartupFailure -ne 'OWNED_START_EXIT_CONFIRMED' -or $session.LastStop -or
        [Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes('JOURNAL/startup-failure.json'))) { throw 'EVIDENCE_CHANGED' }
'''
    # Successful retirement closes handles; the independent fixture cleanup must
    # use the OS evidence collected before retirement, not reopen by PID.
    script = RECOVERY_CS.replace('FAULT', '').replace('EXPECTED', '$true').replace('CHECK', check)
    script = script.replace("if (-not $child.WaitForExit(4000)", "if ('MODE' -ne 'success' -and -not $child.WaitForExit(4000)")
    script = script.replace("-or -not $runner.WaitForExit(4000)", "-or ('MODE' -ne 'success' -and -not $runner.WaitForExit(4000))")
    script = script.replace('MODE', mode).replace('ROOT', str(tmp_path)).replace('JOURNAL', str(tmp_path / 'journal'))
    assert not _run_isolated_launcher(tmp_path, script)['calls']


RECOVERY_PS = START_SETUP + r'''
Add-Type -Path (Join-Path (Split-Path $ast.Extent.File) 'OmiOwnedShutdown.cs') -ReferencedAssemblies @('System.Web.Extensions','System.Core')
foreach ($name in @('Start-OmiBackendAfterFailedStart','Assert-OmiFailedStartProcessExclusion')) {
    $definition=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$false)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:OwnedBackendRestartRequests=[Collections.Generic.HashSet[string]]::new()
$script:FailedStartRecoveryAttempted=$false
$original.StartupFailure='OWNED_START_EXIT_CONFIRMED';$original.StartupExitConfirmed=$true
$original.CanStartAfterStop=$false; $original.LastStop=$null; $receipt=$null
$original | Add-Member NoteProperty CanRecoverFailedStart $true
$original | Add-Member ScriptMethod RetireFailedStart {
    param($id,$pin)
    if (-not $script:FailedStartRecoveryAttempted -or -not $script:ServiceStartRequestInProgress -or
        -not [object]::ReferenceEquals($this,$script:RetiredBackendSessions[0])) { throw 'RETIRE_NOT_SERIALIZED' }
    if ($pin -cne 'application-pin') { throw 'UNPINNED' }
    $script:Calls.Add('retire-failed');$this.CanRecoverFailedStart=$false
    if ($script:DisposeFailure) { throw 'DISPOSE_FAILED' }
}
function Get-OmiBackendApplicationRelease { return 'application-pin' }
function Assert-OmiBackendApplicationRelease { param($ExpectedRelease) if ($ExpectedRelease -cne 'application-pin') {throw 'RESTART_SOURCE_CHANGED'} }
$script:RecoveryBaseFakeOwned=(Get-Item Function:New-FakeOwned).ScriptBlock
function New-FakeOwned {
    $result=& $script:RecoveryBaseFakeOwned
    $result | Add-Member -Force NoteProperty ReleaseId 'application-pin'
    return $result
}
function Get-CimInstance { return @([pscustomobject]@{ProcessId=$PID;CommandLine='fixture-owner'}) + @($script:OtherProcesses | Where-Object { $null -ne $_ }) }
foreach ($statement in @($ast.EndBlock.Statements | Where-Object {
    $_.Extent.Text -match '^\$recoverFailedBackendItem\b' -or
    $_.Extent.Text -eq '[void]$script:Menu.MenuItems.Add($recoverFailedBackendItem)'
})) { . ([scriptblock]::Create($statement.Extent.Text)) }
function Assert-RecoveryResources {
    Assert-StartResources
    if ($original.StartupFailure -ne 'OWNED_START_EXIT_CONFIRMED') { throw 'FAILURE_CLEARED' }
}
'''


@pytest.mark.parametrize('fault,expected', [
    ('', 1), ("$script:OwnsMutex=$false", 0),
    ("$script:RuntimeController.OwnerId='other-owner'", 0),
    ("$script:DiskSource='changed'", 0), ("$script:BackendPort=8401", 0),
    ("$original.CanRecoverFailedStart=$false", 0),
    ("$script:FailedStartRecoveryAttempted=$true", 1),
    ("$script:ManualBackendStartAttemptedSession=$original", 0),
    ("$script:ServiceStopInProgress=$true", 0),
    ("$script:RuntimeControlInProgress=$true", 0),
    ("$script:BackendRecoveryInProgress=$true", 0),
    ("$script:Bindable=$false", 0),
    ("function Get-ListeningProcessIdsOnPort { return @(777) }", 0),
    ("function Get-CimInstance { throw 'ACCESS_DENIED' }", 0),
    ("function Get-CimInstance { return @() }", 0),
    ("$script:OtherProcesses=@([pscustomobject]@{ProcessId=7;CommandLine=$null})", 0),
    ("$script:OtherProcesses=@([pscustomobject]@{ProcessId=7;CommandLine='python owned_backend_entry.py'})", 0),
    ("$script:OtherProcesses=@([pscustomobject]@{ProcessId=7;CommandLine='uvicorn app.main:app --port 8500'})", 0),
    ("$script:DisposeFailure=$true", 0), ("$script:FactoryFailure=$true", 1),
    ("$script:Ready=$false", 1), ("$script:StartupFailure=$true", 1),
    ("$script:PublishFailure=$true", 1), ("$script:DriftDuringReadiness=$true", 1),
    ("$script:ProbeStartReentrancy=$true", 1),
    ("function Assert-OmiFailedStartProcessExclusion { if ($script:FailedStartRecoveryAttempted) {throw 'OTHER_BACKEND_AFTER_RETIREMENT'} }", 0),
])
def test_manual_recovery_single_flight_and_fail_closed(tmp_path, fault, expected):
    scenario = RECOVERY_PS + '\n' + fault + r'''
$recoverFailedBackendItem.PerformClick()
Assert-RecoveryResources
if ($script:SpawnCount -ne EXPECTED) { throw 'UNEXPECTED_FACTORY_COUNT' }
if ($script:FailedStartRecoveryAttempted -and -not $script:ServiceStopInProgress -and -not $script:RuntimeControlInProgress -and -not $script:BackendRecoveryInProgress) {
    $recoverFailedBackendItem.PerformClick()
    if ($script:SpawnCount -ne EXPECTED) { throw 'FAILED_RECOVERY_REPLAYED' }
}
if (-not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled) { throw 'TIMERS_LOST' }
'''.replace('EXPECTED', str(expected))
    result = _run_isolated_launcher(tmp_path, scenario)
    succeeded = any(line.startswith('Backend recovery verified.') for line in result['logs'])
    assert succeeded is (fault in ('', '$script:ProbeStartReentrancy=$true', '$script:FailedStartRecoveryAttempted=$true')), result['logs']


def test_original_restart_uuid_cannot_be_reused_for_recovery(tmp_path):
    scenario = RECOVERY_PS + r'''
$id=[Guid]::NewGuid().ToString('D');$null=$script:OwnedBackendRestartRequests.Add($id)
$script:ServiceStartRequestInProgress=$true
try { Start-OmiBackendAfterFailedStart -RequestId $id;throw 'REPLAY' }
catch { if ($_.Exception.Message -ne 'FAILED_START_RECOVERY_REPLAY') {throw} }
if ($script:SpawnCount -or $script:FailedStartRecoveryAttempted -or $script:RetiredBackendSessions.Count) {throw 'REPLAY_MUTATED'}
'''
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


def test_concurrent_csharp_retirement_has_exactly_one_winner(tmp_path):
    app = tmp_path / 'backend/app'
    app.mkdir(parents=True)
    (app / 'fixture.py').write_text('# isolated source\n')
    check = r'''
    Set-Field 'repo' 'ROOT'
    $pin=[Omi.OwnedShutdown.ProductionSession]::ApplicationRelease('ROOT')
    Add-Type -ReferencedAssemblies System.Core -TypeDefinition @'
using System;
using System.Threading;
using System.Threading.Tasks;
public static class RecoveryRace {
    public static int Run(object session, string pin) {
        int wins=0;
        Action action=()=>{try {
            session.GetType().GetMethod("RetireFailedStart").Invoke(session, new object[]{Guid.NewGuid().ToString("D"),pin});
            Interlocked.Increment(ref wins);
        } catch(System.Reflection.TargetInvocationException) {}};
        Task.WaitAll(Task.Run(action),Task.Run(action));
        return wins;
    }
}
'@
    if ([RecoveryRace]::Run($session,$pin) -ne 1 -or $session.CanRecoverFailedStart -or $session.LastStop) { throw 'CONCURRENT_RETIREMENT' }
    if ([Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes('JOURNAL/startup-failure.json'))) { throw 'RECEIPT_MUTATED' }
'''
    script = RECOVERY_CS.replace('FAULT', '').replace('EXPECTED', '$true').replace('CHECK', check)
    script = script.replace("    if (-not $child.WaitForExit(4000) -or -not $runner.WaitForExit(4000)) { throw 'FIXTURE_EXIT_UNKNOWN' }", '')
    assert not _run_isolated_launcher(tmp_path, script.replace('JOURNAL', str(tmp_path / 'journal')).replace('ROOT', str(tmp_path)))['calls']
