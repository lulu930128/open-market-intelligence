from pathlib import Path
import subprocess

from test_runtime_launcher_recovery import _powershell
from test_runtime_launcher_recovery import _run_isolated_launcher
from test_launcher_backend_start import START_SETUP
import pytest
import json

from test_schema_maintenance import database, maintenance


def test_existing_controller_offline_pipe_commands(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/tests/test-omi-offline-control.ps1"
    result = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-File", str(script),
                             "-FixtureRoot", str(tmp_path / "private-store")],
                            capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OFFLINE_CONTROL_PASS" in result.stdout


@pytest.mark.parametrize("action", ["StartBackend", "RecoverFailedStart", "SchemaUpgrade"])
def test_original_launcher_dispatches_once_with_remote_fence(tmp_path, action):
    scenario = START_SETUP + r'''
Add-Type 'namespace System.Windows.Forms {
 public enum DialogResult {Yes,No} public enum MessageBoxButtons {YesNo} public enum MessageBoxIcon {Warning}
 public static class MessageBox {public static DialogResult Show(string text,string title,MessageBoxButtons buttons,MessageBoxIcon icon) {throw new System.Exception("LOCAL_DIALOG_FORBIDDEN");}}
}'
$script:RuntimeControlInProgress=$true
$script:ObservedAction=$null
$script:RuntimeController | Add-Member ScriptMethod BeginRemoteOperation {param($id);return $true}
$script:RuntimeController | Add-Member ScriptMethod CompleteRemoteOperation {
    param($id,$verified,$stop,$migration,$successor,$after)
    if (-not $verified -or $successor -ne 'VERIFIED') {throw 'COMPLETION_NOT_VERIFIED'}
    $script:Calls.Add('completed')
}
function Invoke-BackendStartRequest {param($RequestId,[switch]$RemoteRequest,[switch]$FailedStartRecovery)
    if (-not $RemoteRequest -or -not $script:RuntimeControlInProgress) {throw 'REMOTE_FENCE_MISSING'}
    $script:ObservedAction=if ($FailedStartRecovery) {'RecoverFailedStart'} else {'StartBackend'}
    $script:RestartReadyBackendSession=$script:OwnedBackendSession
}
function Invoke-OmiConfiguredSchemaUpgrade {param($RequestId,[switch]$RemoteRequest)
    if (-not $RemoteRequest -or -not $script:RuntimeControlInProgress) {throw 'REMOTE_FENCE_MISSING'}
    $script:ObservedAction='SchemaUpgrade';$script:RestartReadyBackendSession=$script:OwnedBackendSession
    $script:LastSchemaOperation=@{request_id=$RequestId;migration_outcome='COMMITTED';successor_outcome='VERIFIED'}
}
Invoke-OmiRemoteControlOperation -RequestId ([Guid]::NewGuid().ToString('D')) -Action 'ACTION'
if ($script:ObservedAction -ne 'ACTION' -or ($script:Calls | Where-Object {$_ -eq 'completed'}).Count -ne 1) {throw 'WRONG_DISPATCH'}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("ACTION", action))


def test_unavailable_schema_selector_never_reports_previous_commit(tmp_path):
    scenario = START_SETUP + r'''
Add-Type 'namespace System.Windows.Forms {
 public enum DialogResult {Yes,No} public enum MessageBoxButtons {YesNo} public enum MessageBoxIcon {Warning}
 public static class MessageBox {public static DialogResult Show(string text,string title,MessageBoxButtons buttons,MessageBoxIcon icon) {throw new System.Exception("LOCAL_DIALOG_FORBIDDEN");}}
}'
$script:LastSchemaOperation=@{request_id=[Guid]::NewGuid().ToString('D');migration_outcome='COMMITTED';successor_outcome='VERIFIED'}
$script:RuntimeController | Add-Member ScriptMethod BeginRemoteOperation {param($id);return $true}
$script:RuntimeController | Add-Member ScriptMethod CompleteRemoteOperation {
    param($id,$verified,$stop,$migration,$successor,$after)
    if ($verified -or $migration -ne 'NOT_ATTEMPTED' -or $successor -ne 'NOT_ATTEMPTED') {throw 'HISTORICAL_COMMIT_BORROWED'}
    $script:Calls.Add('cancelled')
}
function Invoke-OmiConfiguredSchemaUpgrade {param($RequestId,[switch]$RemoteRequest);throw 'SCHEMA_CONFIGURED_TARGET_UNAVAILABLE'}
try {Invoke-OmiRemoteControlOperation -RequestId ([Guid]::NewGuid().ToString('D')) -Action 'SchemaUpgrade';throw 'EXPECTED_REFUSAL'}
catch {if ($_.Exception.Message -ne 'SCHEMA_CONFIGURED_TARGET_UNAVAILABLE') {throw}}
if (-not $script:Calls.Contains('cancelled')) {throw 'MISSING_RECEIPT'}
'''
    _run_isolated_launcher(tmp_path, scenario)


@pytest.mark.parametrize("fault", ["none", "selector-absent", "unknown-transaction", "busy"])
def test_remote_schema_uses_configured_sqlite_target_and_existing_fences(tmp_path, database, fault):
    lock = database.parent / "schema.lock"
    lock.touch()
    proof = maintenance.start_compatibility(database_url=f"sqlite:///{database.as_posix()}",
                                            lock_path=lock, upgrade=True)
    before = database.read_bytes()
    scenario = START_SETUP + r'''
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-OmiConfiguredSchemaUpgrade'},$false)
. ([scriptblock]::Create($definition.Extent.Text))
$script:RuntimeControlInProgress=$true
$script:FactoryCalls=0
$script:ExpectedTarget='PROOF'|ConvertFrom-Json
$script:Mode='FAULT'
function Get-OmiBackendApplicationRelease {return 'fixture-release'}
function Assert-OmiSchemaCompatibility {param($ExpectedRelease,[switch]$Upgrade,[switch]$PassThru)
    if (-not $Upgrade -or -not $PassThru) {throw 'SELECTOR_GRAMMAR'}
    if ($script:Mode -eq 'selector-absent') {return $null}
    return $script:ExpectedTarget
}
function Invoke-OwnedSchemaUpgrade {param($RequestId,$DatabasePath,$SchemaLockPath,[switch]$RemoteRequest)
    if (-not $RemoteRequest -or $DatabasePath -cne $script:ExpectedTarget.configured_target.database_path -or
        $SchemaLockPath -cne $script:ExpectedTarget.configured_target.schema_lock_path) {throw 'CALLER_PATH_SELECTED'}
    if ($script:Mode -eq 'busy') {throw 'SERVICE_OPERATION_IN_PROGRESS'}
    $script:FactoryCalls++
}
if ($script:Mode -eq 'unknown-transaction') {
    $script:SchemaRecoveryFence=@{Path='unknown';TerminalHash=$null;NoEffects=$false;WorkerSettled=$false}
}
$errorCode=$null
try {Invoke-OmiConfiguredSchemaUpgrade -RequestId ([Guid]::NewGuid().ToString('D')) -RemoteRequest}
catch {$errorCode=$_.Exception.Message}
$expected=@{'selector-absent'='SCHEMA_CONFIGURED_TARGET_UNAVAILABLE';'unknown-transaction'='SCHEMA_MAINTENANCE_RECONCILIATION_REQUIRED';'busy'='SERVICE_OPERATION_IN_PROGRESS'}[$script:Mode]
if ($errorCode -cne $expected -or $script:FactoryCalls -ne $(if ($script:Mode -eq 'none') {1} else {0})) {throw "CONFIGURED_GATE_FAILED $errorCode"}
'''
    _run_isolated_launcher(tmp_path, scenario.replace("PROOF", json.dumps(proof).replace("'", "''")).replace("FAULT", fault))
    assert database.read_bytes() == before


def test_remote_dispatch_and_schema_selector_have_no_dialog_or_actor_wire():
    root = Path(__file__).resolve().parents[2]
    control = (root / "scripts/omi-runtime-control.ps1").read_text(encoding="utf-8-sig")
    remote = control.split("function Invoke-OmiRemoteControlOperation {", 1)[1].split("\nfunction ", 1)[0]
    launcher = (root / "scripts/omi-launcher.ps1").read_text(encoding="utf-8-sig")
    selector = launcher.split("function Invoke-OmiConfiguredSchemaUpgrade {", 1)[1].split("\nfunction ", 1)[0]
    assert "BeginRemoteOperation($RequestId)" in remote
    for forbidden in ("MessageBox", "OpenFileDialog", "launcher_local_operator", "BeginLocalOperation"):
        assert forbidden not in remote + selector
