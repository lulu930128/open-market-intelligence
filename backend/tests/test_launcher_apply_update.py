"""Full update stays in the existing Launcher and schema-maintenance owners."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from uuid import uuid4

import pytest

from test_runtime_launcher_recovery import _run_isolated_launcher
from test_schema_maintenance import maintenance
from app.db.migrations import get_head_revision


@pytest.mark.parametrize("mode", ["update", "ordinary", "other-request", "completed"])
def test_full_update_does_not_require_unrelated_machine_command_lines(tmp_path, mode):
    scenario = r'''
$definition=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-OmiFailedStartProcessExclusion'},$false)
. ([scriptblock]::Create($definition.Extent.Text))
$id=[Guid]::NewGuid().ToString('D')
$script:UpdateRequestId=$id
$script:UpdateOperation=@{request_id=$id;status='running'}
if ('MODE' -eq 'ordinary') {$script:UpdateOperation=$null}
if ('MODE' -eq 'other-request') {$id=[Guid]::NewGuid().ToString('D')}
if ('MODE' -eq 'completed') {$script:UpdateOperation.status='succeeded'}
function Get-CimInstance {
    return @([pscustomobject]@{ProcessId=$PID;CommandLine='fixture-owner'},
        [pscustomobject]@{ProcessId=7;CommandLine=$null})
}
$allowed=$false
try {Assert-OmiFailedStartProcessExclusion -RequestId $id;$allowed=$true}
catch {if ($_.Exception.Message -ne 'FAILED_START_PROCESS_OBSERVATION_UNKNOWN') {throw}}
if ($allowed -ne ('MODE' -eq 'update')) {throw 'UPDATE_SCOPE_NOT_PRESERVED'}
'''.replace('MODE', mode)
    assert not _run_isolated_launcher(tmp_path, scenario)['calls']


def test_hidden_launcher_forwards_only_uuid_update_intent(tmp_path):
    entry = Path(__file__).resolve().parents[2] / "scripts/start-omi-launcher-hidden.vbs"
    source = entry.read_text(encoding="utf-8-sig")
    assert 'shell.Run command, 0, False' in source
    (tmp_path / "omi-launcher.ps1").write_text("# Never executed by this fixture\n")
    script = tmp_path / entry.name
    script.write_text(source.replace('shell.Run command, 0, False', 'WScript.Echo command'), encoding="utf-8")
    cscript = str(Path(os.environ["SystemRoot"]) / "System32/cscript.exe")
    request = str(uuid4())
    result = subprocess.run([cscript, "//NoLogo", str(script), "/UpdateRequestId:" + request],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("-UpdateRequestId " + request)
    invalid = subprocess.run([cscript, "//NoLogo", str(script), "/UpdateRequestId:not-a-uuid"],
                             capture_output=True, text=True, timeout=10)
    assert invalid.returncode == 2 and not invalid.stdout


@pytest.mark.parametrize("mode", ["at-head", "behind", "worker-failed", "start-unconfirmed", "readiness-failed"])
def test_latest_source_update_startup_reports_independent_phases(tmp_path, mode):
    scenario = r'''
Add-Type -Path @((Join-Path (Split-Path $ast.Extent.File) 'OmiRuntimeControl.cs'),(Join-Path (Split-Path $ast.Extent.File) 'OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
$definition=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-OmiUpdateStartup'},$false)
. ([scriptblock]::Create($definition.Extent.Text))
$script:RuntimeController=[object]::new();$script:Factory=0;$script:Apply=0
$script:LastSchemaOperation=$null;$id=[Guid]::NewGuid().ToString('D')
function Initialize-ServiceEnvironment {}
function Get-OmiBackendApplicationRelease {return 'latest-disk-source'}
function Publish-OmiRuntimeControlStatus {$script:Calls.Add('publish:'+ $script:UpdateOperation.phase)}
function Start-Backend {
    $script:Factory++
    $script:OwnedBackendSession=[pscustomobject]@{CanRecoverFailedStart=('MODE' -ne 'start-unconfirmed');
        StartupFailure=$null;Alive=$true;Terminal=$false;ChildPid=123;ChildCreated='birth';ReleaseId='latest-disk-source'}
    $script:OwnedBackendSession|Add-Member ScriptMethod RefreshStartupExit {return $true}
    $script:OwnedBackendSession|Add-Member ScriptMethod WaitForStartReadinessAsync {
        param($budget)
        $task=[Threading.Tasks.TaskCompletionSource[bool]]::new();$task.SetResult('MODE' -ne 'readiness-failed');return $task.Task
    }
    if ('MODE' -in @('behind','worker-failed','start-unconfirmed')) {
        $script:OwnedBackendSession.StartupFailure='OWNED_START_EXIT_CONFIRMED'
        throw 'OWNED_START_EXIT_CONFIRMED'
    }
}
function Invoke-OmiConfiguredSchemaUpgrade {
    param($RequestId)
    if ($RequestId -cne $id) {throw 'WRONG_UPDATE_INTENT'}
    $script:Apply++
    $script:LastSchemaOperation=@{request_id=$id;migration_outcome='COMMITTED';schema_revision_observed='20300101_0199'}
    if ('MODE' -eq 'worker-failed') {
        $script:LastSchemaOperation.migration_outcome='NOT_ATTEMPTED'
        $script:LastSchemaOperation.failed_phase='APPLY_STOPPED'
        $script:LastSchemaOperation.worker_failure_code='SCHEMA_LOCK_BUSY'
        throw 'SCHEMA_APPLY_UNCONFIRMED'
    }
    $script:OwnedBackendSession.StartupFailure=$null
}
function Assert-OmiManualBackendStartOwner {}
function Assert-OmiSchemaCompatibility {
    param($ExpectedRelease)
    if ($ExpectedRelease -cne 'latest-disk-source') {throw 'BORROWED_OLD_RELEASE'}
    $script:RestartCompatibilityObservation=@{SchemaRevision='20300101_0199';SchemaHead='20300101_0199'}
}
function Get-OmiOwnedBackendIdentity {return @{pid=123;created_at='birth'}}
function Start-Frontend {$script:Calls.Add('frontend')}
Invoke-OmiUpdateStartup -RequestId $id
if ($script:Factory -ne 1 -or $script:Apply -ne [int]('MODE' -in @('behind','worker-failed'))) {throw 'UNREQUESTED_RETRY'}
$script:UpdateOperation | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'OUTPUT' -Encoding UTF8
'''
    output = tmp_path / "update.json"
    _run_isolated_launcher(tmp_path, scenario.replace("MODE", mode).replace("OUTPUT", str(output)))
    result = json.loads(output.read_text(encoding="utf-8-sig"))
    assert result["target_release_id"] == "latest-disk-source"
    assert result["status"] == ("succeeded" if mode in {"at-head", "behind"} else "failed")
    if mode in {"at-head", "behind"}:
        assert result["schema_revision_observed"] == result["schema_head"] == "20300101_0199"
        assert result["migration_outcome"] == ("COMMITTED" if mode == "behind" else "NOT_NEEDED")
        assert result["backend_readiness"] == "VERIFIED"
    else:
        assert result["backend_readiness"] == "UNVERIFIED"
        assert result["failure_code"] == {
            "worker-failed": "SCHEMA_LOCK_BUSY", "start-unconfirmed": "OWNED_START_EXIT_CONFIRMED",
            "readiness-failed": "BACKEND_START_READINESS_UNCONFIRMED",
        }[mode]
        assert result["failed_phase"] == {
            "worker-failed": "APPLY_STOPPED", "start-unconfirmed": "STARTING_BACKEND",
            "readiness-failed": "VERIFYING_BACKEND",
        }[mode]


def test_existing_worker_upgrades_0093_to_dynamic_source_head_without_backup(tmp_path):
    database = tmp_path / "maintenance.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES ('20261025_0093')")
        db.execute("CREATE TABLE preserved_fixture (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO preserved_fixture VALUES (1, 'preserve')")
    backup = tmp_path / "before.db"
    receipt = maintenance.apply_stopped(database=database, schema_lock_path=tmp_path / "schema.lock",
        receipt_path=tmp_path / "apply.jsonl", request_id=str(uuid4()),
        expected_source=maintenance.maintenance_source_id())
    assert receipt["status"] == "SUCCEEDED"
    assert receipt["migration"] == "COMMITTED"
    assert receipt["after_revision"] == get_head_revision()
    assert receipt["backup"] == "NOT_REQUESTED"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == get_head_revision()
        assert db.execute("SELECT value FROM preserved_fixture").fetchone()[0] == "preserve"
    assert not backup.exists()
    assert not list(tmp_path.glob('*.restore-check'))
