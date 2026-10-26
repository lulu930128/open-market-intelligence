"""Offline retained-process/receipt reducers; never launch OMI or use its store.

Synthetic children provide OS exit evidence only. Runtime writer/rearm authority
is exercised separately against real RuntimeCoordinator + temporary SQLite.
"""
from pathlib import Path
import sys

import pytest

from test_runtime_launcher_recovery import _run_isolated_launcher


CS_SETUP = r"""
Add-Type -Path (Join-Path (Split-Path $ast.Extent.File) 'OmiOwnedShutdown.cs') -ReferencedAssemblies @('System.Web.Extensions','System.Core')
$type = [Omi.OwnedShutdown.ProductionSession]
$flags = [Reflection.BindingFlags]'Instance,NonPublic'
$session = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($type)
function Set-Field($name, $value) { $type.GetField($name, $flags).SetValue($session, $value) }
function Start-Disposable($arguments) {
    $info = [Diagnostics.ProcessStartInfo]::new('PYTHON', $arguments)
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true; $info.RedirectStandardOutput = $true
    $p = [Diagnostics.Process]::Start($info); $null = $p.Handle
    return $p
}
function Created($process) { return $process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() }
$identity = [Collections.Generic.Dictionary[string,string]]::new()
$owner = [Diagnostics.Process]::GetCurrentProcess()
foreach ($entry in @{ instance=[Guid]::NewGuid().ToString('D'); nonce=('a'*64); launcher_pid=$owner.Id.ToString(); launcher_created=(Created $owner);
    host='127.0.0.1'; port='65431'; release_id='offline' }.GetEnumerator()) { $identity[$entry.Key] = $entry.Value }
""".replace('PYTHON', getattr(sys, '_base_executable', sys.executable).replace("'", "''"))


@pytest.mark.parametrize('fault', ['', 'child-survives', 'runner-code', 'child-code', 'wrong-uuid', 'no-proof', 'no-child'])
def test_confirmed_startup_failure_requires_bound_receipt_and_retained_exits(tmp_path, fault):
    scenario = CS_SETUP + r"""
$child = Start-Disposable '-B -c "import time; time.sleep(CHILD_DELAY); raise SystemExit(13)"'
$runner = Start-Disposable '-B -c "import time; time.sleep(.15); raise SystemExit(RUNNER_CODE)"'
try {
    $identity['runner_pid']=$runner.Id.ToString(); $identity['runner_created']=(Created $runner)
    if ($fault -ne 'no-child') {
        $identity['child_pid']=$child.Id.ToString(); $identity['child_created']=(Created $child)
        Set-Field 'child' $child
    }
    Set-Field 'runner' $runner; Set-Field 'identity' $identity
    $receipt = [Collections.Generic.Dictionary[string,string]]::new($identity)
    $receipt['state']='START_FAILED'; $receipt['reason']='OWNED_START_EXIT_CONFIRMED'
    $receipt['child_exact_exit']='true'; $receipt['child_exit_code']='13'; $receipt['child_started']='false'
    if ($fault -eq 'wrong-uuid') { $receipt['instance']=[Guid]::NewGuid().ToString('D') }
    if ($fault -eq 'no-proof') { $receipt.Remove('child_exact_exit') | Out-Null }
    if ($fault -eq 'child-code') { $receipt['child_exit_code']='0' }
    $confirmed = $type.GetMethod('ConfirmStartupExit', $flags).Invoke($session, @($receipt))
    if ($confirmed -ne ($fault -in @('','no-child')) -or $null -ne $session.LastStop) { throw 'STARTUP_EXIT_PROOF_BROKEN' }
    if ($confirmed -and (-not $session.StartupExitConfirmed -or $session.StartupFailure -ne 'OWNED_START_EXIT_CONFIRMED')) { throw 'STARTUP_FAILURE_RECEIPT_LOST' }
} finally {
    if (-not $child.WaitForExit(4000) -or -not $runner.WaitForExit(4000)) { throw 'DISPOSABLE_DID_NOT_EXIT' }
    $child.Dispose(); $runner.Dispose()
}
"""
    scenario = f"$fault='{fault}'\n" + scenario.replace('CHILD_DELAY', '2' if fault == 'child-survives' else '.1').replace('RUNNER_CODE', '0' if fault == 'runner-code' else '79')
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


@pytest.mark.parametrize('fault', ['', 'request-id', 'deadline', 'expired', 'nonce', 'proof'])
def test_runner_and_session_share_strict_rearm_receipt_validation(tmp_path, fault):
    scenario = CS_SETUP + r"""
$wire = $type.Assembly.GetType('Omi.OwnedShutdown.Wire')
foreach ($name in @('runner_pid','runner_created','child_pid','child_created')) { $identity[$name]='1' }
$identity['request_id']=[Guid]::NewGuid().ToString('D')
$identity['deadline']=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString()
if ($fault -ne 'expired') { $identity['deadline']=([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()+5000).ToString() }
$receipt=[Collections.Generic.Dictionary[string,string]]::new($identity)
$receipt['state']='PREFLIGHT_REARMED'; $receipt['rearmed']='true'
switch ($fault) {
    'request-id' { $receipt['request_id']=[Guid]::NewGuid().ToString('D') }
    'deadline' { $receipt['deadline']='1' }
    'nonce' { $receipt['nonce']='wrong' }
    'proof' { $receipt.Remove('rearmed') | Out-Null }
}
$valid=$wire.GetMethod('Rearmed').Invoke($null,@($identity,$receipt))
if ($valid -ne ($fault -eq '')) { throw 'UNAUTHENTICATED_REARM' }
$budget=$wire.GetMethod('Remaining').Invoke($null,@([long]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()+60000),[Diagnostics.Stopwatch]::StartNew(),[long]60000,[int]120000))
if ($budget -lt 55000) { throw 'LIFESPAN_BUDGET_TRUNCATED' }
"""
    assert not _run_isolated_launcher(tmp_path, f"$fault='{fault}'\n" + scenario)['calls']


def test_session_rearm_allows_only_separate_explicit_stop_and_preserves_original(tmp_path):
    child = tmp_path / 'child.py'
    child.write_text('import time\ntime.sleep(3)\n', encoding='utf-8')
    runner = tmp_path / 'receipt_runner.py'
    runner.write_text('''import json, sys
for state in ['PREFLIGHT_REARMED', 'UNKNOWN']:
    value=json.loads(sys.stdin.readline())
    value.update(state=state, reason='PREFLIGHT_REARMED' if state == 'PREFLIGHT_REARMED' else 'ACK_MISMATCH', rearmed='true')
    print(json.dumps(value), flush=True)
''', encoding='utf-8')
    scenario = CS_SETUP + r"""
$child=Start-Disposable '-B "CHILD"'
$runner=Start-Disposable '-B "RUNNER"'
try {
    $identity['runner_pid']=$runner.Id.ToString(); $identity['runner_created']=(Created $runner)
    $identity['child_pid']=$child.Id.ToString(); $identity['child_created']=(Created $child)
    Set-Field 'child' $child; Set-Field 'runner' $runner; Set-Field 'identity' $identity
    Set-Field 'stopGate' ([object]::new())
    Set-Field 'stops' ([Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new())
    $firstId=[Guid]::NewGuid().ToString('D'); $nextId=[Guid]::NewGuid().ToString('D')
    $first=$session.Stop($firstId)
    if (-not $first.Rearmed -or $session.Terminal -or $first.ExactExit) { throw 'REARM_NOT_RESUMABLE' }
    if (-not [object]::ReferenceEquals($first,$session.Stop($firstId))) { throw 'REFUSAL_REPLAYED' }
    $next=$session.Stop($nextId)
    if ($next.RequestId -ne $nextId -or $next.Reason -ne 'ACK_MISMATCH' -or -not $session.Terminal) { throw 'SEPARATE_STOP_FAILED' }
    if (-not [object]::ReferenceEquals($first,$session.Stop($firstId)) -or
        -not [object]::ReferenceEquals($next,$session.Stop([Guid]::NewGuid().ToString('D')))) { throw 'ORIGINAL_EVIDENCE_OVERWRITTEN' }
} finally {
    $runner.StandardInput.Close()
    if (-not $runner.WaitForExit(4000) -or -not $child.WaitForExit(4000)) { throw 'DISPOSABLE_DID_NOT_EXIT' }
    $runner.Dispose(); $child.Dispose()
}
""".replace('CHILD', str(child)).replace('RUNNER', str(runner))
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


def test_production_runner_retains_failure_and_session_specific_log_order():
    source = (Path(__file__).resolve().parents[2] / 'scripts/OmiOwnedShutdown.cs').read_text()
    production = source.split('static int RunProductionCore(', 1)[1]
    assert 'instance.ToString("N") + ".log"' in production
    assert production.index('starting["child_created"]') < production.index('Wire.Send(child.StandardInput, boot)')
    failure = production.split('if (!readyPublished &&', 1)[1]
    assert 'child.ExitCode.ToString()' in failure and 'startup-failure.json' in failure
    assert 'Wire.Rearmed(request, ack)' in production and 'Wire.Rearmed(request, drain)' in production
    assert 'seen.Add(request["request_id"])' in production
    assert 'child.StandardInput.Close()' in production
    assert 'Wire.Remaining(deadline, clock, budget, 120000)' in production


def test_startup_unknown_revalidates_only_original_handles_after_both_exit(tmp_path):
    scenario = CS_SETUP + r"""
$child=Start-Disposable '-B -c "import time; time.sleep(.3); raise SystemExit(13)"'
$runner=Start-Disposable '-B -c "import time; time.sleep(.5); raise SystemExit(79)"'
try {
    $identity['runner_pid']=$runner.Id.ToString(); $identity['runner_created']=(Created $runner)
    $identity['child_pid']=$child.Id.ToString(); $identity['child_created']=(Created $child)
    Set-Field 'child' $child; Set-Field 'runner' $runner; Set-Field 'identity' $identity
    Set-Field '<StartupFailure>k__BackingField' 'OWNED_START_UNKNOWN'
    Set-Field 'terminal' $true
    if ($session.RefreshStartupExit()) { throw 'ALIVE_IS_NOT_EXITED' }
    if (-not $child.WaitForExit(3000) -or -not $runner.WaitForExit(3000)) { throw 'DISPOSABLE_DID_NOT_EXIT' }
    $created=$identity['child_created']; $identity['child_created']='wrong'
    if ($session.RefreshStartupExit()) { throw 'WRONG_CREATION_ACCEPTED' }
    $identity['child_created']=$created
    if (-not $session.RefreshStartupExit() -or $null -ne $session.LastStop) { throw 'EXACT_EXIT_NOT_CONVERGED' }
} finally { $child.Dispose(); $runner.Dispose() }
"""
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']
