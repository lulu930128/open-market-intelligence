from __future__ import annotations

import base64
from datetime import date
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_RUNNER = REPO_ROOT / "scripts" / "run-service-logged.ps1"
LAUNCHER = REPO_ROOT / "scripts" / "omi-launcher.ps1"
HIDDEN_LAUNCHER = REPO_ROOT / "scripts" / "start-omi-launcher-hidden.vbs"
BIND_FAILURE_EXIT_CODE = 78


def _powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None:
        pytest.skip("Windows PowerShell is required for launcher recovery tests.")
    return executable


def test_service_runner_classifies_backend_bind_failure_without_retry(tmp_path: Path) -> None:
    powershell = _powershell()
    # Only the runner needs PowerShell. Keep its synthetic child independent of
    # nested Windows PowerShell initialization (which can fail with 8009001d).
    child = tmp_path / "bind_failure_child.py"
    child.write_text(
        "print(\"ERROR: [Errno 13] error while attempting to bind on address "
        "('127.0.0.1', 8400): [WinError 10013]\")\nraise SystemExit(1)\n",
        encoding="utf-8",
    )
    encoded_arguments = base64.b64encode(
        json.dumps(
            [str(child)],
            ensure_ascii=False,
        ).encode("utf-8")
    ).decode("ascii")

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SERVICE_RUNNER),
            "-ServiceName",
            "backend",
            "-RepoRoot",
            str(tmp_path),
            "-WorkingDirectory",
            str(tmp_path),
            "-FilePath",
            sys.executable,
            "-ArgumentsJsonBase64",
            encoded_arguments,
            "-LauncherPid",
            "0",
            "-MaxRestartAttempts",
            "3",
            "-RestartBackoffSecondsCsv",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    log_path = tmp_path / "logs" / "backend" / date.today().isoformat() / "backend.log"
    log_text = log_path.read_text(encoding="utf-8-sig")
    assert result.returncode == BIND_FAILURE_EXIT_CODE
    assert log_text.count("Service child started.") == 1
    assert "Service bind failure classified for launcher port recovery." in log_text
    assert "Service restart scheduled." not in log_text


def test_launcher_rebuilds_frontend_after_bounded_backend_port_reselection() -> None:
    launcher_text = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "$script:BackendBindFailureExitCode = 78" in launcher_text
    assert "$script:MaxBackendPortRecoveryAttempts = 3" in launcher_text
    assert "function Invoke-BackendBindFailureRecovery" in launcher_text
    recovery_body = launcher_text.split(
        "function Invoke-BackendBindFailureRecovery", 1
    )[1].split("function Stop-BackendService", 1)[0]
    assert "Find-AvailableBackendPort" in recovery_body
    assert "Update-BackendServiceUrls" in recovery_body
    assert "Stop-FrontendService" in recovery_body
    assert "Start-Backend" in recovery_body
    assert "Start-Frontend" in recovery_body


def test_launcher_uses_stable_frontend_bundling_and_bounded_health_recovery() -> None:
    launcher_text = LAUNCHER.read_text(encoding="utf-8-sig")

    assert '$script:FrontendDevBundlerArgument = "--webpack"' in launcher_text
    assert "$script:FrontendHealthRecoveryGraceSeconds = 30" in launcher_text
    assert "$script:FrontendHealthStableResetSeconds = 600" in launcher_text
    assert "$script:MaxFrontendHealthRecoveryAttempts = 1" in launcher_text

    start_body = launcher_text.split("function Start-Frontend", 1)[1].split(
        "function Start-Services", 1
    )[0]
    assert "$script:FrontendDevBundlerArgument" in start_body
    assert "-Arguments $frontendArguments" in start_body

    recovery_body = launcher_text.split(
        "function Invoke-FrontendHealthRecovery", 1
    )[1].split("function Stop-Services", 1)[0]
    assert "Stop-FrontendService" in recovery_body
    assert "Clear-FrontendDevOutput" in recovery_body
    assert "Start-Frontend" in recovery_body

    timer_body = launcher_text.split("$script:Timer.add_Tick({", 1)[1].split(
        "$script:ActivationTimer =", 1
    )[0]
    assert "$frontendProc -and (-not $script:IsPackagedRelease)" in timer_body
    assert "Invoke-FrontendHealthRecovery" in timer_body


def test_launcher_compiles_taskbar_listener_against_runtime_winforms_assemblies() -> None:
    launcher_text = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "[System.Windows.Forms.Application].Assembly.Location" in launcher_text
    assert "[System.Windows.Forms.Message].Assembly.Location" in launcher_text
    assert "Add-Type -ReferencedAssemblies $winFormsReferences" in launcher_text
    assert 'Add-Type -ReferencedAssemblies @("System.Windows.Forms")' not in launcher_text


def test_launcher_separates_run_from_activation_and_preserves_control_priority() -> None:
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert '$script:RunEventName = "OpenMarketIntelligenceLauncherRun"' in source
    assert '$script:ActivationEventName = "OpenMarketIntelligenceLauncherActivate"' in source
    mapping = source.split("$requestedEventName = switch ($LauncherAction)", 1)[1].split(
        "$requestedAction =", 1
    )[0]
    for action, event in (
        ("Run", "RunEventName"),
        ("Activate", "ActivationEventName"),
        ("RestartServices", "RestartEventName"),
        ("Exit", "ExitEventName"),
    ):
        assert f'"{action}" {{ $script:{event} }}' in mapping
    assert "default" not in mapping
    assert "$script:RunEvent = New-Object System.Threading.EventWaitHandle(" in source
    assert "$script:RunEvent.Dispose()" in source

    timer = source.split("$script:ActivationTimer.add_Tick({", 1)[1].split("\n})", 1)[0]
    assert timer.index("$script:ExitEvent.WaitOne(0)") < timer.index(
        "$script:RestartEvent.WaitOne(0)"
    ) < timer.index("$script:RunEvent.WaitOne(0)") < timer.index(
        "$script:ActivationEvent.WaitOne(0)"
    )
    assert 'Invoke-ServiceStartRequest -Reason "secondary-run"' in timer
    activation = timer.split("$script:ActivationEvent.WaitOne(0)) {", 1)[1]
    assert activation.strip() == 'Restore-TrayIcon -Reason "secondary-launch"\n    }'
    # Activate without an owner must also remain free of service startup.
    assert 'if ($LauncherAction -in @("Activate", "Exit", "RestartServices"))' in source
    assert '[string]$LauncherAction = "Run"' in source
    assert "-LauncherAction" not in HIDDEN_LAUNCHER.read_text(encoding="utf-8-sig")


def _run_secondary_launcher(
    tmp_path: Path, *, run_state: str
) -> tuple[int, dict]:
    launcher_path = str(LAUNCHER).replace("'", "''")
    harness = tmp_path / "secondary-launcher-test.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{launcher_path}', [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {{ throw ($parseErrors | Out-String) }}
$script:RunState = '{run_state}'
"""
        + r"""
# Execute only the secondary branch, with all event IO and UI replaced.
# Never evaluate the launcher entrypoint or open any real named event/mutex.
$secondary = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -eq '-not $script:OwnsMutex'
}, $false)
if ($null -eq $secondary) { throw 'Missing secondary launcher branch' }
$body = $secondary.Extent.Text.Replace(
    '[System.Threading.EventWaitHandle]::OpenExisting(', '(Open-TestControlEvent '
)
$script:OwnsMutex = $false
$LauncherAction = 'Run'
$script:RunEventName = 'test-run'
$script:RestartEventName = 'test-restart'
$script:ActivationEventName = 'test-activation'
$script:AppDisplayName = 'test-launcher'
$script:Calls = [System.Collections.Generic.List[string]]::new()
$script:Logs = [System.Collections.Generic.List[string]]::new()
$script:Messages = [System.Collections.Generic.List[string]]::new()
$script:Mutex = [pscustomobject]@{}
$script:Mutex | Add-Member ScriptMethod Dispose { $script:Calls.Add('dispose:mutex') }
function Write-LauncherLog { param($Message, $Level) $script:Logs.Add($Message) }
function Show-Message { param($Message) $script:Messages.Add($Message) }
function Open-TestControlEvent {
    param($Name)
    $script:Calls.Add("open:$Name")
    if ($Name -eq 'test-run' -and $script:RunState -eq 'missing') {
        throw 'Test event missing'
    }
    if ($Name -notin @('test-run', 'test-restart')) { throw "Unexpected event: $Name" }
    $handle = [pscustomobject]@{ Name = $Name }
    $handle | Add-Member ScriptMethod Set {
        $script:Calls.Add("set:$($this.Name)")
        if ($this.Name -eq 'test-run') {
            if ($script:RunState -eq 'set-throws') { throw 'Test signal failed' }
            if ($script:RunState -eq 'set-false') { return $false }
        }
        return $true
    }
    $handle | Add-Member ScriptMethod Dispose { $script:Calls.Add("dispose:$($this.Name)") }
    return $handle
}
try { & ([scriptblock]::Create($body)) }
finally {
    [pscustomobject]@{
        calls = @($script:Calls.ToArray())
        logs = @($script:Logs.ToArray())
        messages = @($script:Messages.ToArray())
    } | ConvertTo-Json -Depth 4 -Compress
}
""",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode in (0, 2), result.stdout + result.stderr
    return result.returncode, json.loads(result.stdout)


@pytest.mark.parametrize("run_state", ["missing", "set-throws", "set-false"])
def test_secondary_run_reports_signal_failure_without_restart(tmp_path: Path, run_state: str) -> None:
    code, result = _run_secondary_launcher(tmp_path, run_state=run_state)
    run_calls = ["open:test-run"]
    if run_state != "missing":
        run_calls += ["set:test-run", "dispose:test-run"]
    assert code == 2
    assert result["calls"] == run_calls + ["dispose:mutex"]
    assert len(result["messages"]) == 1
    assert "does not expose the requested 'Run' control event" in result["messages"][0]
    assert "Exit Launcher" in result["messages"][0]
    assert any(
        "did not expose the required control event" in log
        for log in result["logs"]
    )


def test_secondary_run_uses_run_event_without_restart(tmp_path: Path) -> None:
    code, result = _run_secondary_launcher(tmp_path, run_state="available")
    assert code == 0
    assert result["calls"] == ["open:test-run", "set:test-run", "dispose:test-run", "dispose:mutex"]
    assert result["messages"] == []
    assert not any("fallback" in log for log in result["logs"])


def test_launcher_explicit_start_and_restart_share_recovery_reset() -> None:
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    restart = source.split("function Restart-Services {", 1)[1].split("\nfunction ", 1)[0]
    request = source.split("function Invoke-ServiceStartRequest {", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "Reset-ServiceRecoveryState" in restart
    assert "Reset-ServiceRecoveryState" in request
    assert "$script:FrontendHealthRecoveryAttempts = 0" not in restart + request
    assert "$script:BackendPortRecoveryAttempts = 0" not in restart + request
    assert restart.index("Reset-ServiceRecoveryState") < restart.index(
        "Stop-Services"
    ) < restart.index("Start-Services")
    assert '$startItem.add_Click({ Invoke-ServiceStartRequest -Reason "tray-start" })' in source
    assert "$restartItem.add_Click({ Restart-Services })" in source
    assert "$stopItem.add_Click({ Stop-Services })" in source
    assert request.index("Restore-TrayIcon") < request.index("Get-BackendHealth")
    assert "finally {" in request
    assert "$script:ServiceStartRequestInProgress = $false" in request
    automatic_timer = source.split("$script:Timer.add_Tick({", 1)[1].split(
        "$script:ActivationTimer =", 1
    )[0]
    assert "Invoke-ServiceStartRequest" not in automatic_timer
    assert "Reset-ServiceRecoveryState" not in automatic_timer


# Parse the complete launcher, but load only these functions. Never dot-source
# its entrypoint: these tests must not acquire the real mutex/events, create a
# tray, contact endpoints, or start/stop the user's services.
ISOLATED_LAUNCHER_FUNCTIONS = (
    "Test-ProcessRunning",
    "Test-TrackedServiceStarting",
    "Reset-ServiceRecoveryState",
    "Restart-Services",
    "Invoke-ServiceStartRequest",
)

LAUNCHER_TEST_DOUBLES = r"""
$script:Calls = [System.Collections.Generic.List[string]]::new()
$script:Messages = [System.Collections.Generic.List[string]]::new()
$script:BackendMatches = $true
$script:BackendReady = $false
$script:FrontendHealthy = $false
$script:BackendProcess = $null
$script:FrontendProcess = $null
$script:LastStatusText = 'API stopped; UI stopped'
$script:BackendStopExpected = $false
$script:BackendRecoveryInProgress = $false
$script:FrontendHealthRecoveryInProgress = $false
$script:ServiceStartRequestInProgress = $false
$script:IsShuttingDown = $false
$script:ServiceStartupGraceSeconds = 120
$script:BackendPortRecoveryAttempts = 3
$script:MaxFrontendHealthRecoveryAttempts = 1
$script:FrontendHealthRecoveryAttempts = 1
$script:FrontendHealthRecoveryGraceSeconds = 30
$script:FrontendHealthUnhealthySinceUtc = [DateTime]::UtcNow.AddMinutes(-5)
$script:FrontendHealthHealthySinceUtc = [DateTime]::UtcNow.AddMinutes(-10)
$script:FrontendHealthRecoveryExhaustedLogged = $true
$script:FrontendHealthRecoveryAdoptedLogged = $true
$script:RunResetCount = 0
$script:RunEvent = [pscustomobject]@{}
$script:RunEvent | Add-Member ScriptMethod Reset { $script:RunResetCount += 1 }

function Write-LauncherLog { param($Message, $Level) $script:Messages.Add($Message) }
function Restore-TrayIcon { param($Reason) $script:Calls.Add('restore') }
function Get-ExpectedBackendPython { 'test-python' }
function Get-BackendHealth { [pscustomobject]@{ runtime = 'test-runtime' } }
function Test-BackendHealthMatchesExpected { param($Health, $ExpectedPythonPath) $script:BackendMatches }
function Test-HttpOk { param($Url) $script:BackendReady }
function Test-FrontendOk { $script:FrontendHealthy }
function Start-Sleep { param($Seconds) }
function Stop-Services { $script:Calls.Add('stop') }
function Start-Services {
    $script:Calls.Add('start')
    $script:LastStatusText = $null
    $script:BackendStopExpected = $false
    $script:BackendProcess = New-TestProcess
    $script:FrontendProcess = New-TestProcess
}
function New-TestProcess {
    param([int]$AgeSeconds = 0, [bool]$Exited = $false)
    $process = [pscustomobject]@{
        StartTime = [DateTime]::UtcNow.AddSeconds(-$AgeSeconds)
        HasExited = $Exited
    }
    $process | Add-Member ScriptMethod Refresh {}
    return $process
}
"""


def _run_isolated_launcher(
    tmp_path: Path,
    scenario: str,
    *,
    functions: tuple[str, ...] = ISOLATED_LAUNCHER_FUNCTIONS,
) -> dict:
    launcher_path = str(LAUNCHER).replace("'", "''")
    names = ", ".join(f"'{name}'" for name in functions)
    harness = tmp_path / "launcher-isolated-test.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{launcher_path}', [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {{ throw ($parseErrors | Out-String) }}
foreach ($name in @({names})) {{
    $definition = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }}, $false)
    if ($null -eq $definition) {{ throw "Missing launcher function: $name" }}
    . ([scriptblock]::Create($definition.Extent.Text))
}}
"""
        + LAUNCHER_TEST_DOUBLES
        + "\n"
        + scenario
        + r"""
[pscustomobject]@{
    calls = @($script:Calls.ToArray())
    logs = @($script:Messages.ToArray())
    guarded = $script:ServiceStartRequestInProgress
    run_resets = $script:RunResetCount
    backend_attempts = $script:BackendPortRecoveryAttempts
    frontend_attempts = $script:FrontendHealthRecoveryAttempts
    unhealthy_since = $script:FrontendHealthUnhealthySinceUtc
    healthy_since = $script:FrontendHealthHealthySinceUtc
    exhausted_logged = $script:FrontendHealthRecoveryExhaustedLogged
    adopted_logged = $script:FrontendHealthRecoveryAdoptedLogged
} | ConvertTo-Json -Depth 4 -Compress
""",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("scenario", "calls", "decision"),
    [
        pytest.param(
            "$script:BackendReady = $true; $script:FrontendHealthy = $true",
            ["restore"], "services healthy", id="healthy-adopted-services",
        ),
        pytest.param(
            "$script:BackendProcess = New-TestProcess; $script:FrontendProcess = New-TestProcess; "
            "$script:LastStatusText = 'API starting; UI starting'; "
            "$script:FrontendHealthRecoveryAttempts = 0; $script:FrontendHealthRecoveryExhaustedLogged = $false",
            ["restore"], "services starting", id="normal-startup",
        ),
        pytest.param(
            "$script:BackendReady = $true; $script:FrontendProcess = New-TestProcess; "
            "$script:LastStatusText = 'API OK; UI starting'; "
            "$script:FrontendHealthRecoveryExhaustedLogged = $false; "
            "$script:FrontendHealthUnhealthySinceUtc = [DateTime]::UtcNow",
            ["restore"], "services starting", id="final-auto-attempt-still-starting",
        ),
        pytest.param(
            "$script:FrontendHealthy = $true; $script:BackendProcess = New-TestProcess; "
            "$script:LastStatusText = 'API starting; UI OK'",
            ["restore"], "services starting", id="healthy-frontend-with-old-exhaustion-record",
        ),
        pytest.param("", ["restore", "start"], "Start-Services", id="both-stopped"),
        pytest.param(
            "$script:BackendProcess = New-TestProcess -Exited $true; "
            "$script:FrontendProcess = New-TestProcess -Exited $true",
            ["restore", "start"], "Start-Services", id="both-tracked-exited",
        ),
        pytest.param(
            "$script:BackendReady = $true; $script:BackendProcess = New-TestProcess -AgeSeconds 600; "
            "$script:FrontendProcess = New-TestProcess -AgeSeconds 600; "
            "$script:LastStatusText = 'API OK; UI starting'",
            ["restore", "stop", "start"], "Restart-Services", id="frontend-exhausted-alive",
        ),
        pytest.param(
            "$script:BackendReady = $true; $script:BackendProcess = New-TestProcess; "
            "$script:FrontendProcess = New-TestProcess; "
            "$script:LastStatusText = 'API OK; UI starting'; "
            "$script:FrontendHealthRecoveryExhaustedLogged = $false",
            ["restore", "stop", "start"], "Restart-Services", id="exhausted-before-timer-logs",
        ),
        pytest.param(
            "$script:BackendProcess = New-TestProcess; $script:FrontendProcess = New-TestProcess; "
            "$script:FrontendHealthRecoveryAttempts = 0; $script:FrontendHealthRecoveryExhaustedLogged = $false",
            ["restore", "stop", "start"], "Restart-Services", id="last-status-stopped",
        ),
        pytest.param(
            "$script:BackendProcess = New-TestProcess; "
            "$script:FrontendProcess = New-TestProcess -Exited $true; "
            "$script:LastStatusText = 'API starting; UI starting'",
            ["restore", "stop", "start"], "Restart-Services", id="one-tracked-exited",
        ),
        pytest.param(
            "$script:BackendProcess = New-TestProcess -AgeSeconds 600; "
            "$script:FrontendProcess = New-TestProcess -AgeSeconds 600; "
            "$script:LastStatusText = 'API starting; UI starting'; $script:FrontendHealthy = $true; "
            "$script:FrontendHealthRecoveryAttempts = 0; $script:FrontendHealthRecoveryExhaustedLogged = $false",
            ["restore", "stop", "start"], "Restart-Services", id="backend-stuck-alive",
        ),
        pytest.param(
            "$script:BackendReady = $true; $script:FrontendHealthy = $true; $script:BackendMatches = $false; "
            "$script:BackendProcess = New-TestProcess -AgeSeconds 600",
            ["restore", "stop", "start"], "Restart-Services", id="wrong-backend-identity",
        ),
    ],
)
def test_launcher_explicit_start_decisions(
    tmp_path: Path, scenario: str, calls: list[str], decision: str
) -> None:
    result = _run_isolated_launcher(tmp_path, scenario + '\nInvoke-ServiceStartRequest -Reason "test-run"')
    assert result["calls"] == calls
    assert any(decision in message for message in result["logs"])
    assert result["guarded"] is False
    assert result["run_resets"] == 1
    if "start" in calls:
        assert result["backend_attempts"] == result["frontend_attempts"] == 0
        assert result["unhealthy_since"] is result["healthy_since"] is None
        assert result["exhausted_logged"] is result["adopted_logged"] is False
        assert sum("recovery rearmed" in message for message in result["logs"]) == 1
    else:
        assert result["backend_attempts"] == 3


@pytest.mark.parametrize("guard", ["ServiceStartRequestInProgress", "BackendRecoveryInProgress", "FrontendHealthRecoveryInProgress"])
def test_launcher_coalesces_run_during_recovery(tmp_path: Path, guard: str) -> None:
    result = _run_isolated_launcher(
        tmp_path, f'$script:{guard} = $true\nInvoke-ServiceStartRequest -Reason "test-run"'
    )
    assert result["calls"] == ["restore"]
    assert any("recovery in progress" in message for message in result["logs"])
    assert result["backend_attempts"] == 3
    assert result["run_resets"] == 0


def test_launcher_repeated_run_after_recovery_does_not_restart_starting_services(tmp_path: Path) -> None:
    result = _run_isolated_launcher(
        tmp_path,
        'Invoke-ServiceStartRequest -Reason "first-run"\nInvoke-ServiceStartRequest -Reason "second-run"',
    )
    assert result["calls"] == ["restore", "start", "restore"]
    assert any("services starting" in message for message in result["logs"])
    assert result["guarded"] is False


@pytest.mark.parametrize("failure", ["Start-Services", "Stop-Services", "Get-BackendHealth"])
def test_launcher_recovery_guard_releases_on_failure(tmp_path: Path, failure: str) -> None:
    result = _run_isolated_launcher(
        tmp_path,
        "$script:BackendProcess = New-TestProcess -AgeSeconds 600\n"
        f"function {failure} {{ throw 'isolated failure' }}\n"
        'Invoke-ServiceStartRequest -Reason "test-run"',
    )
    assert result["guarded"] is False
    assert result["run_resets"] == 1
    assert any("Explicit service start failed" in message for message in result["logs"])


def test_launcher_restart_is_forced_even_when_healthy(tmp_path: Path) -> None:
    result = _run_isolated_launcher(
        tmp_path, "$script:BackendReady = $true; $script:FrontendHealthy = $true\nRestart-Services"
    )
    assert result["calls"] == ["stop", "start"]
    assert result["backend_attempts"] == result["frontend_attempts"] == 0


def test_launcher_start_services_clears_previous_stopped_status(tmp_path: Path) -> None:
    result = _run_isolated_launcher(
        tmp_path,
        r"""
# Replace the test double with just the actual Start-Services function.
$start = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-Services'
}, $false)
. ([scriptblock]::Create($start.Extent.Text))
function Initialize-ServiceEnvironment {}
function Start-Backend { $script:BackendProcess = New-TestProcess; $script:Calls.Add('backend-start') }
function Start-Frontend { $script:FrontendProcess = New-TestProcess; $script:Calls.Add('frontend-start') }
function Show-Message { throw 'Unexpected start failure' }
Invoke-ServiceStartRequest -Reason 'first-run'
Invoke-ServiceStartRequest -Reason 'second-run'
""",
    )
    assert result["calls"] == ["restore", "backend-start", "frontend-start", "restore"]
    assert any("services starting" in message for message in result["logs"])


def test_launcher_stop_then_run_rearms_services_without_exiting(tmp_path: Path) -> None:
    result = _run_isolated_launcher(
        tmp_path,
        r"""
$stop = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Stop-Services'
}, $false)
. ([scriptblock]::Create($stop.Extent.Text))
function Stop-FrontendService { $script:FrontendProcess = $null; $script:Calls.Add('frontend-stop') }
function Stop-BackendService {
    $script:BackendStopExpected = $true
    $script:BackendProcess = $null
    $script:Calls.Add('backend-stop')
}
$script:BackendProcess = New-TestProcess
$script:FrontendProcess = New-TestProcess
Stop-Services
if ($script:IsShuttingDown) { throw 'Stop must not exit the owner' }
Invoke-ServiceStartRequest -Reason 'run-after-stop'
""",
    )
    assert result["calls"] == ["frontend-stop", "backend-stop", "restore", "start"]
    assert result["backend_attempts"] == result["frontend_attempts"] == 0


def test_launcher_reentrant_start_is_coalesced(tmp_path: Path) -> None:
    result = _run_isolated_launcher(
        tmp_path,
        r"""
function Start-Services {
    $script:Calls.Add('start')
    Invoke-ServiceStartRequest -Reason 'reentrant-run'
}
Invoke-ServiceStartRequest -Reason 'first-run'
""",
    )
    assert result["calls"] == ["restore", "start", "restore"]
    assert result["guarded"] is False
    assert any("recovery in progress" in message for message in result["logs"])


def test_launcher_guard_releases_even_when_event_cleanup_fails(tmp_path: Path) -> None:
    result = _run_isolated_launcher(
        tmp_path,
        r"""
$script:RunEvent | Add-Member -Force ScriptMethod Reset { throw 'test event disposed' }
try { Invoke-ServiceStartRequest -Reason 'test-run' }
catch { if ($_.Exception.Message -notmatch 'test event disposed') { throw } }
""",
    )
    assert result["guarded"] is False


@pytest.mark.parametrize(
    ("pending", "expected"),
    [
        (("Exit", "Restart", "Run", "Activation"), "exit"),
        (("Restart", "Run", "Activation"), "restart"),
        (("Run", "Activation"), "explicit-start"),
        (("Activation",), "restore"),
    ],
)
def test_launcher_control_timer_routes_only_highest_priority_event(
    tmp_path: Path, pending: tuple[str, ...], expected: str
) -> None:
    signals = "\n".join(f"[void]$script:{name}Event.Set()" for name in pending)
    result = _run_isolated_launcher(
        tmp_path,
        r"""
function Exit-Launcher { param($Reason) $script:Calls.Add('exit') }
function Restart-Services { $script:Calls.Add('restart') }
function Invoke-ServiceStartRequest { param($Reason) $script:Calls.Add('explicit-start') }
# All events are unnamed and isolated from the running launcher owner.
$script:ExitEvent = [System.Threading.EventWaitHandle]::new($false, 'AutoReset')
$script:RestartEvent = [System.Threading.EventWaitHandle]::new($false, 'AutoReset')
$script:RunEvent = [System.Threading.EventWaitHandle]::new($false, 'AutoReset')
$script:ActivationEvent = [System.Threading.EventWaitHandle]::new($false, 'AutoReset')
try {
"""
        + signals
        + r"""
    $tick = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and
        $node.Expression.Extent.Text -eq '$script:ActivationTimer' -and $node.Member.Value -eq 'add_Tick'
    }, $true)
    & $tick.Arguments[0].ScriptBlock.GetScriptBlock()
}
finally {
    $script:ExitEvent.Dispose()
    $script:RestartEvent.Dispose()
    $script:RunEvent.Dispose()
    $script:ActivationEvent.Dispose()
}
""",
    )
    assert result["calls"] == [expected]
