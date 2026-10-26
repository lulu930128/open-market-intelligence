"""R1: real C# reducers and Launcher AST; no service, socket, ACL or DB IO."""
from pathlib import Path

import pytest

from test_launcher_backend_start import RESTART_SETUP
from test_owned_lifecycle_convergence import CS_SETUP
from test_runtime_launcher_recovery import _run_isolated_launcher


@pytest.mark.parametrize('fault', ['', 'child_pid', 'child_created', 'instance', 'port', 'release_id', 'owner'])
def test_old_loaded_readiness_ignores_new_disk_but_keeps_identity(tmp_path, fault):
    app = tmp_path / 'backend/app'
    app.mkdir(parents=True)
    (app / 'example.py').write_text('# new source', encoding='utf-8')
    scenario = CS_SETUP + r'''
$identity['child_pid']=$owner.Id.ToString();$identity['child_created']=(Created $owner)
$identity['runner_pid']=$owner.Id.ToString();$identity['runner_created']=(Created $owner)
Set-Field 'child' $owner;Set-Field 'runner' $owner;Set-Field 'identity' $identity
Set-Field 'repo' 'ROOT';Set-Field 'release' 'old-loaded-release'
$identity['release_id']='old-loaded-release'
$owned=[Collections.Generic.Dictionary[string,object]]::new()
foreach($key in $identity.Keys) {$owned[$key]=$identity[$key]}
if ('FAULT' -eq 'owner') {$identity['launcher_created']='wrong'}
elseif ('FAULT') {$owned['FAULT']='wrong'}
$serving=[Collections.Generic.Dictionary[string,object]]::new()
$serving['runtime_started']=$true;$serving['owned_start']=$owned
$value=[Collections.Generic.Dictionary[string,object]]::new();$value['serving_backend']=$serving
$ok=$type.GetMethod('VerifyLoadedReadiness',$flags).Invoke($session,@($value))
if ($ok -ne ('FAULT' -eq '') -or $session.StartReadinessVerified) {throw 'PHASE_IDENTITY_BROKEN'}
if ([Omi.OwnedShutdown.ProductionSession]::ApplicationRelease('ROOT') -eq 'old-loaded-release') {throw 'INVALID_FIXTURE'}
'''.replace('ROOT', str(tmp_path)).replace('FAULT', fault)
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


@pytest.mark.parametrize('mutation', ['edit', 'add', 'delete', 'abort-protocol'])
def test_before_prepare_refusal_is_not_terminal_and_uuid_is_retained(tmp_path, mutation):
    app = tmp_path / 'backend/app'
    app.mkdir(parents=True)
    (app / 'example.py').write_text('# old', encoding='utf-8')
    scenario = CS_SETUP + r'''
$identity['child_pid']=$owner.Id.ToString();$identity['child_created']=(Created $owner)
$identity['runner_pid']=$owner.Id.ToString();$identity['runner_created']=(Created $owner)
$identity['restart_abort_protocol']='1'
Set-Field 'child' $owner;Set-Field 'runner' $owner;Set-Field 'identity' $identity
Set-Field 'repo' 'ROOT';Set-Field 'stopGate' ([object]::new())
Set-Field 'stops' ([Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new())
$pin=[Omi.OwnedShutdown.ProductionSession]::ApplicationRelease('ROOT')
MUTATION
$id=[Guid]::NewGuid().ToString('D')
$result=$session.StopForRestartAsync($id,$pin).GetAwaiter().GetResult()
if ($result.State -ne 'blocked' -or -not $result.StopNotSent -or $result.Rearmed -or
    $result.ExactExit -or $session.Terminal -or -not $session.Alive -or
    $result.PreflightStage -ne 'BEFORE_PREPARE') {throw 'LOCAL_REFUSAL_STRANDED_OWNER'}
if (-not [object]::ReferenceEquals($result,$session.StopForRestartAsync($id,$pin).GetAwaiter().GetResult())) {throw 'UUID_REPLAY'}
'''.replace('ROOT', str(tmp_path)).replace('MUTATION', {
        'edit': f"[IO.File]::AppendAllText('{app / 'example.py'}','# changed')",
        'add': f"[IO.File]::WriteAllText('{app / 'added.py'}','# added')",
        'delete': f"[IO.File]::Delete('{app / 'example.py'}')",
        'abort-protocol': "$identity.Remove('restart_abort_protocol') | Out-Null",
    }[mutation])
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


@pytest.mark.parametrize('fault', ['', 'no-proof', 'wrong-id', 'wrong-child', 'wrong-action', 'expired', 'unknown'])
def test_post_prepare_abort_requires_same_generation_ack_and_never_sends_stop(tmp_path, fault):
    scenario = CS_SETUP + r'''
$identity['child_pid']=$owner.Id.ToString();$identity['child_created']=(Created $owner)
$identity['runner_pid']=$owner.Id.ToString();$identity['runner_created']=(Created $owner)
$request=[Collections.Generic.Dictionary[string,string]]::new($identity)
$request['request_id']=[Guid]::NewGuid().ToString('D')
$deadline=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()+10000
$request['deadline']=$deadline.ToString();$request['action']='STOP'
$ack=[Collections.Generic.Dictionary[string,string]]::new($request)
$ack['action']='ABORT_PREPARE';$ack['state']='PREFLIGHT_REARMED';$ack['rearmed']='true'
switch('FAULT') {
    'no-proof' {$ack.Remove('rearmed') | Out-Null}
    'wrong-id' {$ack['request_id']=[Guid]::NewGuid().ToString('D')}
    'wrong-child' {$ack['child_created']='wrong'}
    'wrong-action' {$ack['action']='STOP'}
    'expired' {$request['deadline']='1';$ack['deadline']='1'}
    'unknown' {$ack['state']='REARM_UNKNOWN'}
}
$sent=[IO.MemoryStream]::new();$writer=[IO.StreamWriter]::new($sent)
$bytes=[Text.Encoding]::UTF8.GetBytes(($ack | ConvertTo-Json -Compress)+"`n")
$received=[IO.MemoryStream]::new($bytes,$false);$reader=[IO.StreamReader]::new($received)
$method=[Omi.OwnedShutdown.Runner].GetMethod('AbortPreparedRestart',[Reflection.BindingFlags]'Static,NonPublic')
$ok=$false
try {$method.Invoke($null,@($writer,$reader,$request,$owner,$owner,$deadline,[Diagnostics.Stopwatch]::StartNew(),[long]10000));$ok=$true}
catch {if ($_.Exception.ToString() -notmatch 'RESTART_REARM_NOT_ATTESTED') {throw}}
if ($ok -ne ('FAULT' -eq '')) {throw 'ABORT_FALSE_PROOF'}
$writer.Flush();$sent.Position=0;$frame=([IO.StreamReader]::new($sent)).ReadToEnd() | ConvertFrom-Json
if ($frame.action -ne 'ABORT_PREPARE' -or $frame.target_release_id -or $frame.request_id -ne $request['request_id']) {throw 'UNSAFE_FRAME'}
'''.replace('FAULT', fault)
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


@pytest.mark.parametrize('phase', ['readiness', 'after-stop', 'after-start'])
def test_launcher_freezes_successor_release_at_each_boundary(tmp_path, phase):
    fault = {
        'readiness': "$original | Add-Member -Force ScriptMethod VerifyReadiness {$script:ApplicationRelease='changed';return $true}",
        'after-stop': "$original | Add-Member -Force ScriptMethod StopForRestartAsync {param($id,$pin);$task=$this.StopAsync($id);$script:ApplicationRelease='changed';return $task}",
        'after-start': "$script:BaseFactory=(Get-Item Function:New-OmiProductionOwnedBackend).ScriptBlock; function New-OmiProductionOwnedBackend {$value=& $script:BaseFactory;$value.ReleaseId='wrong';return $value}",
    }[phase]
    result = _run_isolated_launcher(tmp_path, RESTART_SETUP + fault + r'''
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedBackendRestart -RequestId $id} catch {}
if ($script:LastBackendRestart.State -eq 'succeeded') {throw 'SOURCE_DRIFT_ACCEPTED'}
$count=$script:Calls.Count
try {Invoke-OwnedBackendRestart -RequestId $id} catch {}
if ($script:Calls.Count -ne $count) {throw 'DRIFT_UUID_REPLAY'}
''')
    assert result['calls'].count('backend-stop') == (phase != 'readiness')
    assert result['calls'].count('factory') == (phase == 'after-start')


def test_runner_pin_is_private_and_checked_on_both_sides_of_prepare():
    source = (Path(__file__).resolve().parents[2] / 'scripts/OmiOwnedShutdown.cs').read_text()
    runner = source.split('static int RunProductionCore(', 1)[1]
    assert runner.index('request.Remove("target_release_id")') < runner.index('var result =')
    first, second = [i for i in range(len(runner)) if runner.startswith('ProductionSession.RequireRelease(repo, targetRelease)', i)]
    assert first < runner.index('Wire.Send(child.StandardInput, prepare)') < second
    assert second < runner.index('AbortPreparedRestart(child.StandardInput') < runner.index('Wire.Send(child.StandardInput, request)')
    readiness = source.split('bool VerifyReadiness(int timeout)', 1)[1].split('public Task<bool> WaitForStartReadinessAsync', 1)[0]
    assert 'ApplicationRelease' not in readiness
    startup = source.split('public Task<bool> WaitForStartReadinessAsync', 1)[1].split('public bool CanStartAfterStop', 1)[0]
    assert startup.count('ApplicationRelease(repo) == release') == 2


@pytest.mark.parametrize('mode', ['not-sent', 'rearmed', 'unknown', 'bad-proof'])
@pytest.mark.parametrize('previous_fence', [False, True])
def test_launcher_restores_only_proven_live_generation(tmp_path, mode, previous_fence):
    scenario = RESTART_SETUP + r'''
$script:SafeStopAttempted=PREVIOUS
if ($script:SafeStopAttempted) {$script:RestartReadyBackendSession=$original}
$prior=$script:RestartReadyBackendSession
$original | Add-Member -Force ScriptMethod StopForRestartAsync {
    param($id,$pin)
    $proof='MODE' -ne 'unknown'
    $this.Terminal=-not $proof
    $result=[pscustomobject]@{RequestId=$id;BeforePid=$this.ChildPid;BeforeCreated=$this.ChildCreated;
        State=$(if($proof){'blocked'}else{'unknown'});ExactExit=$false;
        StopNotSent=('MODE' -eq 'not-sent' -or 'MODE' -eq 'bad-proof');Rearmed=('MODE' -eq 'rearmed');
        Reason=$(if('MODE' -eq 'rearmed'){'PREFLIGHT_REARMED'}elseif($proof){'RESTART_SOURCE_CHANGED'}else{'STOP_TIMEOUT'});
        PreflightStage=$(if('MODE' -eq 'rearmed'){'RESTART_SOURCE_CHANGED'}else{'BEFORE_PREPARE'})}
    if ('MODE' -eq 'bad-proof') {$result.BeforeCreated='wrong'}
    $task=[Threading.Tasks.TaskCompletionSource[object]]::new();$task.SetResult($result);return $task.Task
}
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedBackendRestart -RequestId $id} catch {}
$proven='MODE' -in @('not-sent','rearmed')
if ($script:SafeStopAttempted -ne $(if($proven){PREVIOUS}else{$true}) -or
    ((Test-OmiRemoteRestartGeneration) -ne $proven) -or $script:SpawnCount) {throw 'FENCE_RESTORATION_BROKEN'}
if ($proven -and -not [object]::ReferenceEquals($prior,$script:RestartReadyBackendSession)) {throw 'GENERATION_LOST'}
try {Invoke-OwnedBackendRestart -RequestId $id;throw 'REPLAY'} catch {if ($_.Exception.Message -ne 'BACKEND_RESTART_NO_REPLAY') {throw}}
'''.replace('MODE', mode).replace('PREVIOUS', '$true' if previous_fence else '$false')
    assert 'factory' not in _run_isolated_launcher(tmp_path, scenario)['calls']


@pytest.mark.parametrize('fault', ['', 'pid', 'created', 'uuid', 'reason', 'stage', 'no-proof', 'exact', 'unknown'])
def test_controller_before_prepare_receipt_uses_fixed_bound_proof(tmp_path, fault):
    # No Controller constructor/store/ACL. Exercise its actual receipt reducer
    # and serializer; durable filesystem ACL/write-through IO is not performed.
    scenario = r'''
$dir=Split-Path $ast.Extent.File
Add-Type -Path @((Join-Path $dir 'OmiOwnedShutdown.cs'),(Join-Path $dir 'OmiRuntimeControl.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
$receipt=[Omi.RuntimeControl.Receipt]::new()
$receipt.request_id=[Guid]::NewGuid().ToString('D');$receipt.state='unknown';$receipt.reason='LIFECYCLE_FAILED'
$receipt.before=[Omi.RuntimeControl.Identity]::new();$receipt.before.pid=123;$receipt.before.created_at='2026-10-19T00:00:00Z'
$stopType=[Omi.OwnedShutdown.ProductionSession+StopEvidence]
$stop=[Activator]::CreateInstance($stopType,$true)
foreach($entry in @{RequestId=$receipt.request_id;BeforePid=123;BeforeCreated=$receipt.before.created_at;
    State='blocked';Reason='RESTART_SOURCE_CHANGED';StopNotSent=$true;ExactExit=$false;Rearmed=$false;
    PreflightStage='BEFORE_PREPARE'}.GetEnumerator()) {$stopType.GetProperty($entry.Key).SetValue($stop,$entry.Value,$null)}
switch('FAULT') {
    'pid' {$stopType.GetProperty('BeforePid').SetValue($stop,999,$null)}
    'created' {$stopType.GetProperty('BeforeCreated').SetValue($stop,'wrong',$null)}
    'uuid' {$stopType.GetProperty('RequestId').SetValue($stop,[Guid]::NewGuid().ToString('D'),$null)}
    'reason' {$stopType.GetProperty('Reason').SetValue($stop,'arbitrary',$null)}
    'stage' {$stopType.GetProperty('PreflightStage').SetValue($stop,'AFTER_STOP',$null)}
    'no-proof' {$stopType.GetProperty('StopNotSent').SetValue($stop,$false,$null)}
    'exact' {$stopType.GetProperty('ExactExit').SetValue($stop,$true,$null)}
    'unknown' {$stopType.GetProperty('State').SetValue($stop,'unknown',$null)}
}
$method=[Omi.RuntimeControl.Controller].GetMethod('ApplyBeforePrepareRefusal',[Reflection.BindingFlags]'Static,NonPublic')
$ok=$method.Invoke($null,@($receipt,$stop))
$roundtrip=$receipt | ConvertTo-Json -Depth 8 | ConvertFrom-Json
if ($ok -ne ('FAULT' -eq '') -or $roundtrip.state -ne $(if($ok){'blocked'}else{'unknown'}) -or
    $roundtrip.reason -ne $(if($ok){'RESTART_SOURCE_CHANGED'}else{'LIFECYCLE_FAILED'})) {throw 'FALSE_RECEIPT'}
'''.replace('FAULT', fault)
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']
    source = (Path(__file__).resolve().parents[2] / 'scripts/OmiRuntimeControl.cs').read_text()
    reasons = source.split('readonly HashSet<string> reasons', 1)[1].split('};', 1)[0]
    assert '"RESTART_SOURCE_CHANGED"' in reasons
    assert '"RESTART_ABORT_PROTOCOL_UNAVAILABLE"' in reasons
