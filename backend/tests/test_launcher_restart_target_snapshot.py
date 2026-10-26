"""Restart target selection through real Launcher AST and source/schema gates.

Only disposable source files and an inspector double are used. No production
entrypoint, database, configuration, credential, endpoint or process is touched.
"""
import json
from pathlib import Path
import sys

import pytest

from test_launcher_backend_start import RESTART_SETUP
from test_runtime_launcher_recovery import _run_isolated_launcher


def setup_snapshot(tmp_path, *, compatible=True, owner="fixture-controller", drift=False):
    for name in ("backend/app", "scripts", ".venv"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend/app/example.py").write_text("# target\n", encoding="utf-8")
    (tmp_path / ".venv/pyvenv.cfg").write_text(
        f"executable = {sys.executable}\n", encoding="utf-8"
    )
    proof = dict(contract="omi.start-compatibility.v1", compatible=compatible,
                 backend_pid=100, owner_id=owner)
    # Exercise the actual fixed CheckStart invocation and PowerShell proof
    # validation, without importing OMI settings or opening any database.
    inspector = "import json, sys\nfrom pathlib import Path\n"
    inspector += "assert sys.argv[1:] == ['CheckStart', '--base-url', 'http://127.0.0.1:1']\n"
    if drift:
        inspector += "Path('backend/app/example.py').write_text('# changed during CheckStart')\n"
    inspector += f"print({json.dumps(json.dumps(proof))})\n"
    (tmp_path / "scripts/omi-schema-maintenance.py").write_text(inspector, encoding="utf-8")
    return RESTART_SETUP + r"""
$script:RepoRoot='ROOT'
$script:BackendBaseUrl='http://127.0.0.1:1'
$control=[Management.Automation.Language.Parser]::ParseFile(
    (Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1'),[ref]$null,[ref]$null)
foreach ($name in @('Get-OmiBackendApplicationRelease','Assert-OmiBackendApplicationRelease','Assert-OmiSchemaCompatibility')) {
    $node=$control.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$false)
    . ([scriptblock]::Create($node.Extent.Text))
}
$script:ApplicationRelease=Get-OmiBackendApplicationRelease
$original.ReleaseId='old-loaded-release'
$script:StopPin=$null
$original | Add-Member -Force ScriptMethod StopWithinDeadlineAsync {
    param($id,$pin,$deadline)
    if ($this.ReleaseId -cne $script:OldRelease -or
        -not [object]::ReferenceEquals($this,$original) -or $deadline.RemainingMilliseconds -gt 180000) {
        throw 'OLD_STOP_IDENTITY_OR_DEADLINE_CHANGED'
    }
    $script:StopPin=$pin
    return $this.StopForRestartAsync($id,$pin)
}
$script:RuntimeController | Add-Member -Force ScriptMethod CompleteOwnedRestart {
    param($id,$stop,$next,$verified,$beforeStopReason,$attempted)
    $script:Calls.Add('receipt')
    $script:BeforeStopReason=$beforeStopReason
    $script:RemoteCompleted=$null -ne $verified
}
""".replace("ROOT", str(tmp_path).replace("'", "''"))


@pytest.mark.parametrize("updated", [True, False])
@pytest.mark.parametrize("remote", [True, False])
def test_restart_uses_frozen_disk_target_and_retains_old_stop_identity(tmp_path, updated, remote):
    scenario = setup_snapshot(tmp_path)
    if not updated:
        scenario += "$original.ReleaseId=$script:ApplicationRelease\n"
    scenario += r"""
$script:OldRelease=$original.ReleaseId
$id=[Guid]::NewGuid().ToString('D')
Invoke-OwnedBackendRestart -RequestId $id REMOTE
if ($script:LastBackendRestart.State -ne 'succeeded' -or
    $script:StopPin -cne $script:ApplicationRelease -or
    $original.ReleaseId -cne $script:OldRelease -or
    $script:OwnedBackendSession.ReleaseId -cne $script:ApplicationRelease -or
    -not $original.LastStop.ExactExit -or $script:SpawnCount -ne 1 -or
    -not [object]::ReferenceEquals($frontend,$script:FrontendProcess)) {throw 'TARGET_NOT_ADOPTED'}
$count=$script:Calls.Count
try {Invoke-OwnedBackendRestart -RequestId $id REMOTE;throw 'REPLAY'}
catch {if ($_.Exception.Message -ne 'BACKEND_RESTART_NO_REPLAY') {throw}}
if ($script:Calls.Count -ne $count) {throw 'EXTRA_START'}
""".replace("REMOTE", "-RemoteRequest" if remote else "")
    result = _run_isolated_launcher(tmp_path, scenario)
    assert result["calls"].count("backend-stop") == 1
    assert result["calls"].count("factory") == 1
    assert result["calls"].count("authenticated-intent") == int(remote)


@pytest.mark.parametrize("fault,stops,starts", [
    ("schema-behind", 0, 0), ("schema-owner", 0, 0),
    ("source-during-schema", 0, 0), ("source-after-stop", 1, 0),
    ("source-during-readiness", 1, 1), ("loaded-lifecycle", 0, 0),
    ("lifecycle-during-schema", 0, 0), ("wrong-pid", 0, 0),
    ("controller-replaced", 0, 0), ("no-exact-exit", 1, 0),
    ("readiness-failed", 1, 1),
])
def test_refusal_never_adopts_drift_or_starts_an_extra_successor(tmp_path, fault, stops, starts):
    scenario = setup_snapshot(
        tmp_path, compatible=fault != "schema-behind",
        owner="foreign-owner" if fault == "schema-owner" else "fixture-controller",
        drift=fault == "source-during-schema",
    )
    scenario += "$script:OldRelease=$original.ReleaseId\n"
    scenario += {
        "source-after-stop": r"""
$original | Add-Member -Force ScriptMethod StopForRestartAsync {
    param($id,$pin)
    $task=$this.StopAsync($id)
    [IO.File]::AppendAllText((Join-Path $script:RepoRoot 'backend/app/example.py'),'# drift')
    return $task
}
""",
        "source-during-readiness": r"""
$script:BaseFactory=(Get-Item Function:New-OmiProductionOwnedBackend).ScriptBlock
function New-OmiProductionOwnedBackend {
    $value=& $script:BaseFactory
    $value | Add-Member -Force ScriptMethod WaitForStartReadinessAsync {
        param($budget)
        [IO.File]::AppendAllText((Join-Path $script:RepoRoot 'backend/app/example.py'),'# drift')
        $task=[Threading.Tasks.TaskCompletionSource[bool]]::new();$task.SetResult($true);return $task.Task
    }
    return $value
}
""",
        "loaded-lifecycle": "$script:DiskSource='different-launcher'\n",
        "lifecycle-during-schema": r"""
$script:CheckSchema=(Get-Item Function:Assert-OmiSchemaCompatibility).ScriptBlock
function Assert-OmiSchemaCompatibility {
    param($ExpectedRelease)
    & $script:CheckSchema -ExpectedRelease $ExpectedRelease
    $script:DiskSource='different-launcher'
}
""",
        "wrong-pid": "$script:WrongIdentity=$true\n",
        "controller-replaced": "$script:LoadedRuntimeController=[object]::new()\n",
        "no-exact-exit": "$script:StopMode='unknown'\n",
        "readiness-failed": "$script:Ready=$false\n",
    }.get(fault, "")
    scenario += r"""
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-OwnedBackendRestart -RequestId $id -RemoteRequest;throw 'FAULT_ACCEPTED'}
catch {if ($_.Exception.Message -eq 'FAULT_ACCEPTED') {throw}}
if ($script:LastBackendRestart.State -eq 'succeeded' -or $script:RemoteCompleted) {throw 'FALSE_SUCCESS'}
if ('FAULT' -in @('loaded-lifecycle','lifecycle-during-schema') -and
    $script:BeforeStopReason -ne 'SOURCE_ADOPTION_NOT_ATTESTED') {throw 'OWNER_UPDATE_DIAGNOSIS_LOST'}
if ('FAULT' -in @('schema-behind','schema-owner') -and
    $script:BeforeStopReason -ne 'RESTART_COMPATIBILITY_NOT_ATTESTED') {throw 'SCHEMA_GATE_LOST'}
if ('FAULT' -eq 'source-during-schema' -and
    $script:BeforeStopReason -ne 'RESTART_SOURCE_CHANGED') {throw 'PIN_DRIFT_LOST'}
$attempts=$script:SpawnCount
try {Invoke-OwnedBackendRestart -RequestId $id -RemoteRequest} catch {}
if ($script:SpawnCount -ne $attempts -or
    -not [object]::ReferenceEquals($frontend,$script:FrontendProcess)) {throw 'EXTRA_START_OR_FRONTEND_CHANGE'}
""".replace("FAULT", fault)
    result = _run_isolated_launcher(tmp_path, scenario)
    assert result["calls"].count("backend-stop") == stops
    assert result["calls"].count("factory") == starts


def test_successor_pin_stays_private_and_cutoff_keeps_original_owned_authority():
    source = (Path(__file__).resolve().parents[2] / "scripts/OmiOwnedShutdown.cs").read_text()
    stop = source.split("StopEvidence StopOnce(", 1)[1].split("public void Dispose()", 1)[0]
    assert 'Wire.Copy(identity, "REQUEST")' in stop
    assert 'command["target_release_id"] = targetRelease' in stop
    runner = source.split("static int RunProductionCore(", 1)[1]
    assert runner.index('request.Remove("target_release_id")') < runner.index('Wire.Same(identity, request, Wire.Identity)')
    assert runner.count("ProductionSession.RequireRelease(repo, targetRelease)") == 2
    bounded = source.split("async Task<StopEvidence> StopBounded(", 1)[1].split("void SaveCutoff", 1)[0]
    assert "Task.Delay(deadline.RemainingMilliseconds)" in bounded
    assert "ForceRetainedStop(requestId, deadline, evidence)" in bounded
    cutoff = source.split("StopEvidence ForceRetainedStop(", 1)[1].split("StopEvidence StopOnce(", 1)[0]
    assert "RetainedIdentityMatches()" in cutoff


@pytest.mark.parametrize("reason,next_action", [
    ("SOURCE_ADOPTION_NOT_ATTESTED", "Explicit_Launcher_update_required"),
    ("OWNER_NOT_ATTESTED", "Status_then_reconcile_retained_owner"),
    ("RESTART_COMPATIBILITY_NOT_ATTESTED", "CheckStart_then_explicit_SchemaUpgrade_or_approved_release"),
    ("RESTART_SOURCE_CHANGED", "CheckStart_then_explicit_SchemaUpgrade_or_approved_release"),
])
def test_controller_records_pre_stop_refusal_without_claiming_stop_or_start(tmp_path, reason, next_action):
    # A private disposable receipt store; do not start a pipe or mint intent.
    scenario = r"""
$dir=Split-Path $ast.Extent.File
Add-Type -Path @((Join-Path $dir 'OmiOwnedShutdown.cs'),(Join-Path $dir 'OmiRuntimeControl.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
$controller=[Omi.RuntimeControl.Controller]::new('STORE',$null,'unused-fixture-pipe')
try {
    $flags=[Reflection.BindingFlags]'Instance,NonPublic'
    $type=$controller.GetType()
    $receipt=[Omi.RuntimeControl.Receipt]::new()
    $receipt.request_id=[Guid]::NewGuid().ToString('D')
    $receipt.owner_id=$controller.OwnerId;$receipt.state='running';$receipt.reason='RUNNING'
    $type.GetMethod('Save',$flags).Invoke($controller,@($receipt))
    $type.GetField('active',$flags).SetValue($controller,$receipt.request_id)
    $controller.CompleteOwnedRestart($receipt.request_id,$null,$null,$null,'REASON',$false)
    $saved=$type.GetMethod('Read',$flags).Invoke($controller,@($receipt.request_id))
    if ($saved.state -ne 'blocked' -or $saved.reason -ne 'REASON' -or
        $saved.stop_outcome -ne 'NOT_ATTEMPTED' -or $saved.successor_outcome -ne 'NOT_ATTEMPTED' -or
        $saved.migration_outcome -ne 'NOT_ATTEMPTED' -or $saved.preflight_stage -ne 'BEFORE_STOP' -or
        $saved.next_action -ne 'NEXT_ACTION') {throw 'FALSE_LIFECYCLE_RECEIPT'}
} finally {$controller.Dispose()}
""".replace("STORE", str(tmp_path / "receipts").replace("'", "''"))
    scenario = scenario.replace("REASON", reason).replace("NEXT_ACTION", next_action)
    assert not _run_isolated_launcher(tmp_path, scenario)["calls"]
