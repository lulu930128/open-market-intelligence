"""Source-only lifecycle classification, status and exact-stop start fixtures.

No Launcher entrypoint, settings, credentials, live DB or runtime endpoints.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_launcher_backend_start import START_SETUP
from test_launcher_restart_target_snapshot import setup_snapshot
from test_runtime_launcher_recovery import _run_isolated_launcher

ROOT = Path(__file__).resolve().parents[2]
LOAD_PUBLISH = r"""
$controlAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1'),[ref]$null,[ref]$null)
$publish=$controlAst.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Publish-OmiRuntimeControlStatus'},$false)
. ([scriptblock]::Create($publish.Extent.Text))
$script:RuntimeController | Add-Member ScriptMethod Publish {
    param($json,$identity,$attested)
    $script:Published=$json | ConvertFrom-Json
}
"""


@pytest.mark.parametrize("changed,lifecycle_changed,application_changed", [
    ("backend/app/example.py", False, True),
    ("backend/alembic/versions/new.py", False, False),
    ("backend/alembic/env.py", False, False),
    ("scripts/omi-launcher.ps1", True, False),
    ("scripts/omi-runtime-control.ps1", True, False),
    ("scripts/OmiRuntimeControl.cs", True, False),
    ("scripts/OmiOwnedShutdown.cs", True, False),
    ("scripts/apply-omi-update.ps1", True, False),
    ("backend/owned_backend_entry.py", True, False),
])
def test_actual_digest_classifies_source(tmp_path, changed, lifecycle_changed, application_changed):
    body = (ROOT / "scripts/omi-runtime-control.ps1").read_text(encoding="utf-8-sig").split(
        "function Get-OmiLifecycleSourceId {", 1)[1].split("\nfunction ", 1)[0]
    names = re.findall(r"'((?:scripts/|backend/|\.venv/)[^']+)'", body)
    for name in [*names, "backend/app/example.py", "backend/alembic/env.py",
                 "backend/alembic/versions/new.py"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# fixture\n")
    scenario = START_SETUP + r"""
$script:RepoRoot='ROOT'
. (Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1')
$lifecycle=Get-OmiLifecycleSourceId
$application=Get-OmiBackendApplicationRelease
$schema=Get-OmiSchemaSourceRelease
[IO.File]::AppendAllText((Join-Path $script:RepoRoot 'CHANGED'),'# changed')
if (((Get-OmiLifecycleSourceId) -cne $lifecycle) -ne LIFE -or
    ((Get-OmiBackendApplicationRelease) -cne $application) -ne APP) {throw 'SOURCE_CLASSIFICATION_WRONG'}
if ('CHANGED' -like 'backend/alembic/*' -and (Get-OmiSchemaSourceRelease) -ceq $schema) {throw 'SCHEMA_DRIFT_LOST'}
# Missing required source is typed UNKNOWN, never the exception's local path.
[IO.File]::Delete((Join-Path $script:RepoRoot 'scripts/omi-launcher.ps1'))
try {Get-OmiLifecycleSourceId;throw 'MISSING_ACCEPTED'}
catch {if ($_.Exception.Message -cne 'SOURCE_DIGEST_UNKNOWN') {throw 'RAW_DIGEST_ERROR'}}
""".replace("ROOT", str(tmp_path)).replace("CHANGED", changed)
    scenario = scenario.replace("LIFE", "$true" if lifecycle_changed else "$false")
    scenario = scenario.replace("APP", "$true" if application_changed else "$false")
    assert not _run_isolated_launcher(tmp_path, scenario)["calls"]


@pytest.mark.parametrize("fault,reason", [
    ("application", None), ("lifecycle", "SOURCE_ADOPTION_NOT_ATTESTED"),
    ("unreadable", "SOURCE_DIGEST_UNKNOWN"), ("endpoint", "OWNER_NOT_ATTESTED"),
    ("owner", "OWNER_NOT_ATTESTED"),
    ("known-schema", "RESTART_COMPATIBILITY_NOT_ATTESTED"),
])
def test_status_matches_known_admission_and_does_not_run_inspector(tmp_path, fault, reason):
    scenario = START_SETUP + LOAD_PUBLISH + r"""
$original.Alive=$true;$original.Terminal=$false;$original.LastStop=$null
function Assert-OmiSchemaCompatibility {throw 'STATUS_MUST_NOT_SPAWN_INSPECTOR'}
""" + {
        "application": "$script:ApplicationRelease='new-application'\n",
        "lifecycle": "$script:DiskSource='changed-launcher'\n",
        "unreadable": "function Get-OmiLifecycleSourceId {throw 'SOURCE_DIGEST_UNKNOWN'}\n",
        "endpoint": "$script:BackendPort=8401\n",
        "owner": "$script:LoadedRuntimeController=[object]::new()\n",
        "known-schema": r"""
$script:RestartCompatibilityObservation=[pscustomobject]@{Session=$original;TargetRelease='fixture-release';SchemaSource='fixture-schema';State='INCOMPATIBLE';Reason='RESTART_COMPATIBILITY_NOT_ATTESTED'}
""",
    }[fault] + r"""
Publish-OmiRuntimeControlStatus
$r=$script:Published.restart
if ($r.available -ne AVAILABLE) {throw 'FALSE_AVAILABILITY'}
if ('REASON' -and ($r.reason -cne 'REASON' -or 'REASON' -cnotin $r.blockers)) {throw 'MISSING_REASON'}
if ('FAULT' -eq 'lifecycle' -and $r.update_action -cne 'ApplyUpdate') {throw 'UPDATE_ACTION_MISSING'}
if ('FAULT' -eq 'application' -and ($r.update_action -or $r.diagnostics.target_release_id -cne 'new-application')) {throw 'APPLICATION_MISCLASSIFIED'}
if ('FAULT' -eq 'unreadable' -and $r.diagnostics.source -cne 'UNKNOWN') {throw 'UNKNOWN_LOST'}
"""
    scenario = scenario.replace("AVAILABLE", "$true" if reason is None else "$false")
    scenario = scenario.replace("REASON", reason or "").replace("FAULT", fault)
    assert not _run_isolated_launcher(tmp_path, scenario)["calls"]


@pytest.mark.parametrize("fault", ["none", "schema-behind", "source-during-check", "no-stop", "schema-after-check"])
def test_manual_start_selects_current_disk_and_pins_one_operation(tmp_path, fault):
    scenario = setup_snapshot(tmp_path, compatible=fault != "schema-behind", drift=fault == "source-during-check")
    inspector = tmp_path / "scripts/omi-schema-maintenance.py"
    inspector.write_text(inspector.read_text(encoding="utf-8").replace(
        "['CheckStart', '--base-url', 'http://127.0.0.1:1']", "['CheckStart']"), encoding="utf-8")
    scenario += r"""
$original.Alive=$false;$original.Terminal=$true;$original.CanStartAfterStop=$true
$script:SafeStopAttempted=$true
$script:SchemaDigest='schema-initial'
function Get-OmiSchemaSourceRelease {return $script:SchemaDigest}
"""
    if fault == "no-stop":
        scenario += "$original.CanStartAfterStop=$false\n"
    if fault == "schema-after-check":
        scenario += r"""
$script:RealCheck=(Get-Item Function:Assert-OmiSchemaCompatibility).ScriptBlock
function Assert-OmiSchemaCompatibility {
    param($ExpectedRelease)
    & $script:RealCheck -ExpectedRelease $ExpectedRelease
    $script:SchemaDigest='schema-drift'
}
"""
    scenario += r"""
$id=[Guid]::NewGuid().ToString('D')
try {Invoke-BackendStartRequest -RequestId $id;if ('FAULT' -ne 'none') {throw 'FAULT_ACCEPTED'}}
catch {if ('FAULT' -eq 'none' -or $_.Exception.Message -eq 'FAULT_ACCEPTED') {throw}}
if ('FAULT' -eq 'none') {
    if ($script:OwnedBackendSession.ReleaseId -cne $script:ApplicationRelease -or
        $original.ReleaseId -cne 'old-loaded-release' -or $script:SpawnCount -ne 1) {throw 'OLD_RELEASE_PINNED'}
} elseif ($script:SpawnCount -or $script:RetiredBackendSessions.Count) {throw 'UNSAFE_RETIRE_OR_START'}
$attempts=$script:SpawnCount
try {Invoke-BackendStartRequest -RequestId $id;throw 'UUID_REPLAY'}
catch {if ($_.Exception.Message -ne 'BACKEND_START_NO_REPLAY') {throw}}
if ($script:SpawnCount -ne $attempts -or $script:BackendStartSchemaPin) {throw 'OPERATION_PIN_OR_REPLAY_LEAK'}
""".replace("FAULT", fault)
    result = _run_isolated_launcher(tmp_path, scenario)
    assert "backend-stop" not in result["calls"]


def test_router_preserves_owner_classification_and_fails_closed_on_missing_digest(monkeypatch):
    from app import runtime_control as control
    from app.routers.runtime_control import status

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={},
                              app=SimpleNamespace(state=SimpleNamespace()))

    def observe():
        return json.loads(status(request).body)

    owner = {"schema": control.SCHEMA, "owner_id": "fixture", "restart": {
        "available": False, "reason": "SOURCE_ADOPTION_NOT_ATTESTED",
        "blockers": ["SOURCE_ADOPTION_NOT_ATTESTED"], "update_action": "ApplyUpdate"}}
    monkeypatch.setattr(control, "launcher_request", lambda *_: json.loads(json.dumps(owner)))
    monkeypatch.setattr(control, "bundle_id", lambda: "changed-application-bundle")
    assert observe()["restart"] == owner["restart"]
    owner["restart"] = {"available": True, "reason": "AUTHENTICATED_REMOTE_INTENT_REQUIRED", "blockers": []}
    assert observe()["restart"]["available"] is True
    monkeypatch.setattr(control, "bundle_id", lambda: None)
    result = observe()
    assert result["source"]["observation"] == "UNKNOWN"
    assert result["restart"]["available"] is False
    assert result["restart"]["reason"] == "SOURCE_DIGEST_UNKNOWN"


@pytest.mark.parametrize("reason,state,action", [
    ("SOURCE_ADOPTION_NOT_ATTESTED", "blocked", "Explicit_ApplyUpdate_required"),
    ("SOURCE_DIGEST_UNKNOWN", "unknown", "Restore_source_readability_then_Status_no_automatic_retry"),
    ("RESTART_COMPATIBILITY_NOT_ATTESTED", "blocked", "CheckStart_then_explicit_SchemaUpgrade_or_approved_release"),
])
def test_manual_start_receipt_retains_typed_preflight_refusal(tmp_path, reason, state, action):
    scenario = r"""
$dir=Split-Path $ast.Extent.File
Add-Type -Path @((Join-Path $dir 'OmiOwnedShutdown.cs'),(Join-Path $dir 'OmiRuntimeControl.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
$controller=[Omi.RuntimeControl.Controller]::new('STORE',$null,'unused-fixture')
try {
    $flags=[Reflection.BindingFlags]'Instance,NonPublic'
    $type=$controller.GetType()
    $receipt=[Omi.RuntimeControl.Receipt]::new()
    $receipt.request_id=[Guid]::NewGuid().ToString('D');$receipt.owner_id=$controller.OwnerId
    $receipt.action='StartBackend';$receipt.actor='authenticated_pipe_client'
    $receipt.requester=[Omi.RuntimeControl.Identity]::new()
    $receipt.requester.pid=$PID;$receipt.requester.created_at=[DateTime]::UtcNow.ToString('o')
    $receipt.state='running';$receipt.reason='RUNNING'
    $null=$type.GetMethod('Save',$flags).Invoke($controller,@($receipt))
    $type.GetField('active',$flags).SetValue($controller,$receipt.request_id)
    $controller.CompleteRemoteOperation($receipt.request_id,$false,'PREVIOUSLY_STOPPED','NOT_ATTEMPTED','NOT_ATTEMPTED',$null,'REASON')
    $saved=$type.GetMethod('Read',$flags).Invoke($controller,@($receipt.request_id))
    if ($saved.state -cne 'STATE' -or $saved.reason -cne 'REASON' -or $saved.next_action -cne 'NEXT_ACTION' -or
        $saved.preflight_stage -cne 'BEFORE_START' -or $saved.stop_outcome -cne 'PREVIOUSLY_STOPPED' -or
        $saved.successor_outcome -cne 'NOT_ATTEMPTED') {throw 'FALSE_START_RECEIPT'}
} finally {$controller.Dispose()}
""".replace("STORE", str(tmp_path / "receipts"))
    scenario = scenario.replace("REASON", reason).replace("STATE", state).replace("NEXT_ACTION", action)
    assert not _run_isolated_launcher(tmp_path, scenario)["calls"]
