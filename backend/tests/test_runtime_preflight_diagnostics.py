"""Read-only diagnostics must never become restart authority."""
from types import SimpleNamespace
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app import runtime as owner
from app import runtime_control as control
from app.db.admission import SqliteAdmission
from test_runtime_control import call, authorized, payload  # noqa: F401


WIRE_FIELDS = {"schema", "registered_drain_state", "runtime_started",
               "all_writers_drained", "unknown_writer_count"}


@pytest.fixture
def runtime(monkeypatch):
    result = owner.RuntimeCoordinator(schema_lock=object(), background_lock=object(),
                                      drain_owned_sessions=True, drain_engine_connections=True)
    result.started = True
    monkeypatch.setitem(sys.modules, "_omi_owned_release", SimpleNamespace(verified=True))
    monkeypatch.setattr(owner, "sqlite_admission", SqliteAdmission())
    monkeypatch.setattr(owner.job_service, "observe_job_quiescence",
                        lambda: {"reason": "IDLE", "unfinished_future_count": 0})
    monkeypatch.setattr(result, "stop", lambda **kw: pytest.fail("no stop"))
    monkeypatch.setattr(result, "prepare_owned_restart", lambda **kw: pytest.fail("no prepare"))
    monkeypatch.setattr(result, "commit_owned_restart", lambda: pytest.fail("no commit"))
    return result


def test_idle_and_capable_are_not_drain_proof(runtime):
    report = runtime.restart_preflight()
    diagnostics = runtime.restart_diagnostics()
    assert diagnostics["owned_restart_capability"]["state"] == ""
    assert diagnostics["unknown_writer_count_basis"] == "unattested_scope_categories"
    assert report["unknown_writer_count"] == len(owner.UNATTESTED_WRITERS)
    assert diagnostics["unknown_writer_categories"] == list(owner.UNATTESTED_WRITERS)
    assert report["registered_drain_state"] == "NOT_REQUESTED"
    assert report["all_writers_drained"] is False
    assert diagnostics["owner_observations"]["jobs"]["reason"] == "IDLE"
    assert runtime.http_admission.accepting and runtime._stop_task is None


@pytest.mark.parametrize("bootstrap,unknown,expected", [
    (False, False, "OWNED_BOOTSTRAP_REQUIRED"),
    (True, True, "ALL_WRITERS_DRAIN_UNAVAILABLE"),
])
def test_capability_blocker_remains_explicit(runtime, monkeypatch, bootstrap, unknown, expected):
    monkeypatch.setitem(sys.modules, "_omi_owned_release", SimpleNamespace(verified=bootstrap))
    runtime.http_ownership_unknown = unknown
    report = runtime.restart_preflight()
    assert runtime.restart_diagnostics()["owned_restart_capability"]["state"] == expected
    assert report["all_writers_drained"] is False


def test_pending_or_native_lease_observation_does_not_grant_authority(runtime, monkeypatch):
    monkeypatch.setattr(owner.job_service, "observe_job_quiescence",
                        lambda: {"reason": "UNRESOLVED_ENQUEUE", "unresolved_enqueues": 1})
    runtime._restart_guard = object()
    runtime._restart_preparing = True
    report = runtime.restart_diagnostics()
    assert report["owner_observations"]["native_writer_lease_retained"]
    assert report["owner_observations"]["prepare_in_progress"]
    assert report["owner_observations"]["jobs"]["unresolved_enqueues"] == 1
    assert runtime.restart_preflight()["all_writers_drained"] is False
    assert runtime._restart_committed is False


def test_existing_status_read_forwards_diagnostics_without_new_control_route(runtime, monkeypatch):
    def status_only(action, **kwargs):
        assert action == "Status"
        return control.unknown_status()
    monkeypatch.setattr(control, "launcher_request", status_only)
    response = call(runtime=runtime)
    assert response.status_code == 200
    serving = response.json()["serving_backend"]
    assert serving["readiness"] == "UNATTESTED"
    assert serving["writer_preflight"] == runtime.restart_preflight()
    assert serving["writer_diagnostics"] == runtime.restart_diagnostics()
    assert call(runtime=runtime, headers={"Origin": "https://example.invalid"}).status_code == 403
    assert runtime.http_admission.accepting and runtime._restart_guard is None


def test_post_uses_exact_bounded_wire_and_never_reads_diagnostics(runtime, monkeypatch, authorized):
    """Exercise the real POST serializer seam without contacting a launcher."""
    monkeypatch.setattr(runtime, "restart_diagnostics",
                        lambda: pytest.fail("POST must not read GET-only diagnostics"))
    reports = []
    def dispatch(action, **kwargs):
        assert action == "RestartBackend"
        report = kwargs["backend_preflight"]
        assert set(report) == WIRE_FIELDS
        assert len(json.dumps(report)) <= 1024
        reports.append(report)
        return {"request_id": kwargs["request_id"], "state": "blocked",
                "reason": "FIXTURE_NO_RESTART"}
    monkeypatch.setattr(control, "launcher_request", dispatch)
    response = call("POST", "/restart-backend", headers=authorized,
                    json=payload(), runtime=runtime)
    assert response.status_code == 409
    assert reports == [runtime.restart_preflight()]


def test_exact_wire_with_actual_csharp_parser(runtime, tmp_path):
    """Compile the unchanged parser; no constructor, pipe, store, or lifecycle IO."""
    executable = shutil.which("powershell.exe")
    if not executable:
        pytest.skip("Windows PowerShell required for actual C# parser")
    report = runtime.restart_preflight()
    assert set(report) == WIRE_FIELDS
    wire = json.dumps(report, separators=(",", ":"))
    assert len(wire) < 1024
    cases = [wire, wire.ljust(1024), wire.ljust(1025),
             json.dumps({**report, "owner_observations": {}}),
             json.dumps({k: v for k, v in report.items() if k != "runtime_started"})]
    inputs = tmp_path / "wire.json"
    inputs.write_text(json.dumps(cases), encoding="utf-8")
    script = tmp_path / "parse.ps1"
    script.write_text(r"""
param([string]$Repo, [string]$Inputs)
$ErrorActionPreference = 'Stop'
Add-Type -Path @((Join-Path $Repo 'scripts/OmiRuntimeControl.cs'), (Join-Path $Repo 'scripts/OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions', 'System.Core', 'System.Windows.Forms')
$type = [Omi.RuntimeControl.Controller]
# Test-only parser object: bypass construction to avoid store/pipe initialization.
$parser = [System.Runtime.Serialization.FormatterServices]::GetUninitializedObject($type)
$flags = [System.Reflection.BindingFlags]'Instance,NonPublic'
$type.GetField('json', $flags).SetValue($parser, (New-Object System.Web.Script.Serialization.JavaScriptSerializer))
$method = $type.GetMethod('ParsePreflight', $flags)
$cases = Get-Content -LiteralPath $Inputs -Raw -Encoding UTF8 | ConvertFrom-Json
$results = @(foreach ($case in $cases) {
    $null -ne $method.Invoke($parser, [object[]]@([string]$case))
})
ConvertTo-Json -InputObject $results -Compress
""", encoding="utf-8")
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-File", str(script),
         "-Repo", str(Path(__file__).resolve().parents[2]), "-Inputs", str(inputs)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert json.loads(result.stdout) == [True, True, False, False, False]
