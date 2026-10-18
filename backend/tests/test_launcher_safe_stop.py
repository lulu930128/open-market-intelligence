"""Launcher routing only: never execute its entrypoint or control live processes.

These doubles check ordering/reentrancy, not drain or exit proof. The real
Runtime/Uvicorn and disposable Runner tests supply those separate surfaces.
"""
from test_runtime_launcher_recovery import _run_isolated_launcher

import pytest


SETUP = r"""
Add-Type 'namespace System.Windows.Forms { public static class Application {
    public static int Exits; public static void Exit() { Exits++; }
    public static void DoEvents() { }
} }'
foreach ($name in @('Stop-BackendService', 'Stop-Services', 'Stop-FrontendService', 'Assert-FrontendSafeStopAvailable', 'Exit-Launcher')) {
    $definition = $ast.Find({ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $false)
    . ([scriptblock]::Create($definition.Extent.Text))
}
function New-TestTimer {
    $timer = [pscustomobject]@{ Enabled = $true }
    $timer | Add-Member ScriptMethod Stop { $this.Enabled = $false }
    $timer | Add-Member ScriptMethod Start { $this.Enabled = $true }
    return $timer
}
function Show-Message { param($Message) $script:Messages.Add($Message) }
function Stop-ProcessTree { throw 'FORCE_FALLBACK_FORBIDDEN' }
function Stop-BackendPortOwners { throw 'PORT_KILL_FORBIDDEN' }
function Stop-FrontendPortOwners { throw 'PORT_KILL_FORBIDDEN' }
function Get-ListeningProcessIdsOnPort { return @() }
function Test-TcpPortBindable { return $true }
$script:Timer = New-TestTimer
$script:ActivationTimer = New-TestTimer
$script:NotifyIcon = [pscustomobject]@{ Visible = $true }
$script:OwnsMutex = $true
$script:LauncherExitReady = $false
$script:ServiceStopInProgress = $false
$script:SafeStopAttempted = $false
$script:OwnedBackendStartAttempted = $true
$script:BackendProcess = New-TestProcess
$script:FrontendProcess = $null
$script:StopResult = [pscustomobject]@{ RequestId = ''; State = 'stopped'; ExactExit = $true;
    Reason = 'LIFESPAN_AND_EXACT_EXIT'; Rearmed = $false; PreflightStage = '' }
$script:OwnedBackendSession = [pscustomobject]@{ RunnerProcess = $script:BackendProcess;
    Terminal = $false; Alive = $true; LastStop = $null }
$script:OwnedBackendSession | Add-Member ScriptMethod StopAsync {
    param($RequestId)
    $script:Calls.Add('backend-stop')
    if ($script:Timer.Enabled -or $script:ActivationTimer.Enabled) { throw 'TIMERS_NOT_PAUSED' }
    if ($script:ProbeReentrancy) {
        try { Stop-Services; throw 'REENTRANT_STOP_ACCEPTED' }
        catch { if ($_.Exception.Message -ne 'SAFE_STOP_IN_PROGRESS') { throw } }
        Exit-Launcher -Reason 'reentrant'
        Invoke-ServiceStartRequest -Reason 'reentrant'
    }
    $script:StopResult.RequestId = $RequestId
    $this.Terminal = -not $script:StopResult.Rearmed
    $this.LastStop = $script:StopResult
    $task = [Threading.Tasks.TaskCompletionSource[object]]::new()
    $task.SetResult($script:StopResult)
    return $task.Task
}
"""


BACKEND_ONLY_TRAY_SETUP = SETUP + r"""
# Build only this item's real AST statements with an in-memory MenuItem double.
# No WinForms UI, launcher entrypoint, named handles, or live IO is executed.
Add-Type 'namespace System.Windows.Forms { public class MenuItem {
    public string Text; public event System.Action Click;
    public void PerformClick() { Click(); }
} }'
$script:Menu = [pscustomobject]@{ MenuItems = [Collections.Generic.List[object]]::new() }
$itemStatements = @($ast.EndBlock.Statements | Where-Object {
    $_.Extent.Text -match '^\$safeStopBackendItem\b' -or
    $_.Extent.Text -eq '[void]$script:Menu.MenuItems.Add($safeStopBackendItem)'
})
if ($itemStatements.Count -ne 4) { throw 'BACKEND_ONLY_MENU_WIRING_MISSING' }
foreach ($statement in $itemStatements) { . ([scriptblock]::Create($statement.Extent.Text)) }
if ($script:Menu.MenuItems.Count -ne 1 -or $safeStopBackendItem.Text -ne 'Safe Stop Backend' -or
    -not [object]::ReferenceEquals($script:Menu.MenuItems[0], $safeStopBackendItem)) {
    throw 'BACKEND_ONLY_MENU_NOT_REACHABLE'
}
function Stop-FrontendService { $script:Calls.Add('forbidden-frontend-stop'); throw 'FRONTEND_MUST_NOT_BE_TOUCHED' }
function Stop-LegacyBackendService { $script:Calls.Add('forbidden-legacy-stop'); throw 'FORCE_FALLBACK_FORBIDDEN' }
function Stop-Process { $script:Calls.Add('forbidden-force'); throw 'FORCE_FALLBACK_FORBIDDEN' }
function taskkill { $script:Calls.Add('forbidden-taskkill'); throw 'FORCE_FALLBACK_FORBIDDEN' }
$script:FrontendProcess = New-TestProcess
$frontend = $script:FrontendProcess
$backend = $script:BackendProcess
$session = $script:OwnedBackendSession
$script:RestartEvent = [pscustomobject]@{ Resets = 0 }
$script:RestartEvent | Add-Member ScriptMethod Reset { $this.Resets++ }
$script:ExitEvent = [pscustomobject]@{ Resets = 0 }
$script:ExitEvent | Add-Member ScriptMethod Reset { $this.Resets++ }
function Assert-BackendOnlyOwnerRetained {
    if ([System.Windows.Forms.Application]::Exits -or $script:LauncherExitReady -or
        $script:IsShuttingDown -or $script:ServiceStopInProgress -or -not $script:OwnsMutex -or
        -not $script:NotifyIcon.Visible -or -not $script:SafeStopAttempted -or
        -not [object]::ReferenceEquals($frontend, $script:FrontendProcess) -or
        -not [object]::ReferenceEquals($backend, $script:BackendProcess) -or
        -not [object]::ReferenceEquals($session, $script:OwnedBackendSession)) { throw 'OWNER_OR_UI_LOST' }
}
"""


def test_backend_only_tray_success_retains_frontend_and_serializes_actions(tmp_path):
    result = _run_isolated_launcher(tmp_path, BACKEND_ONLY_TRAY_SETUP + r"""
$script:ProbeReentrancy = $true
$safeStopBackendItem.PerformClick()
Assert-BackendOnlyOwnerRetained
if (-not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled -or
    -not $script:BackendStopExpected -or $script:LastServiceStopError) { throw 'STOP_STATE_LOST' }
$evidence = $script:OwnedBackendSession.LastStop
$safeStopBackendItem.PerformClick()
if (-not [object]::ReferenceEquals($evidence, $script:OwnedBackendSession.LastStop)) { throw 'BACKEND_REPLAYED' }
if ($script:RunResetCount -ne 2 -or $script:RestartEvent.Resets -ne 2 -or
    $script:ExitEvent.Resets -ne 2) { throw 'EVENTS_NOT_COALESCED' }
""")
    assert result['calls'] == ['backend-stop', 'restore']
    assert sum('Backend stopped. Any running Frontend/UI services remain running' in line
               for line in result['logs']) == 2


@pytest.mark.parametrize('scenario,code', [
    ("$script:StopResult.State='blocked'; $script:StopResult.ExactExit=$false; $script:StopResult.Rearmed=$true", 'BACKEND_SAFE_STOP_PREFLIGHT_REARMED'),
    ("$script:StopResult.State='unknown'; $script:StopResult.ExactExit=$false", 'BACKEND_SAFE_STOP_UNKNOWN'),
    ("$script:StopResult.State='unknown'; $script:StopResult.ExactExit=$false; $script:StopResult.Reason='STOP_TIMEOUT'", 'BACKEND_SAFE_STOP_TIMEOUT'),
    ("$script:StopResult.ExactExit=$false", 'BACKEND_SAFE_STOP_UNKNOWN'),
    ("$script:StopResult.Reason='LIFECYCLE_FAILED'", 'BACKEND_SAFE_STOP_UNKNOWN'),
])
def test_backend_only_tray_failure_preserves_owner_and_shows_fixed_error(tmp_path, scenario, code):
    result = _run_isolated_launcher(tmp_path, BACKEND_ONLY_TRAY_SETUP + '\n' + scenario + r"""
$script:ActivationTimer.Enabled = $false
$safeStopBackendItem.PerformClick()
Assert-BackendOnlyOwnerRetained
if (-not $script:Timer.Enabled -or $script:ActivationTimer.Enabled -or
    $script:RunResetCount -ne 1 -or $script:RestartEvent.Resets -ne 1 -or
    $script:ExitEvent.Resets -ne 1) { throw 'TIMER_OR_EVENT_STATE_LOST' }
$first = $script:StopResult.RequestId
if ($script:StopResult.Rearmed) {
    if ($script:BackendStopExpected -or $session.Terminal) { throw 'REARM_NOT_PRESERVED' }
    $script:StopResult.Rearmed = $false
    $script:StopResult.State = 'unknown'
    $safeStopBackendItem.PerformClick()
    if ($script:StopResult.RequestId -eq $first) { throw 'EXPLICIT_REARM_NOT_ROUTED' }
    $first = $script:StopResult.RequestId
}
$safeStopBackendItem.PerformClick()
Assert-BackendOnlyOwnerRetained
if ($script:StopResult.RequestId -ne $first) { throw 'UNKNOWN_UUID_REPLACED' }
""")
    assert result['calls'] == ['backend-stop'] * (2 if 'Rearmed=$true' in scenario else 1)
    assert code in result['logs']  # Exact UI error, not just a log substring.
    assert not any('Backend stopped' in line for line in result['logs'])


def test_backend_only_tray_reentry_and_runtime_operation_are_rejected(tmp_path):
    result = _run_isolated_launcher(tmp_path, BACKEND_ONLY_TRAY_SETUP + r"""
$script:ServiceStopInProgress = $true
$safeStopBackendItem.PerformClick()
$script:ServiceStopInProgress = $false
$script:RuntimeControlInProgress = $true
$safeStopBackendItem.PerformClick()
if (-not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled -or
    $script:SafeStopAttempted -or [System.Windows.Forms.Application]::Exits) { throw 'BUSY_STATE_CHANGED' }
""")
    assert not result['calls']
    assert result['logs'] == ['SAFE_STOP_IN_PROGRESS', 'SERVICE_OPERATION_IN_PROGRESS']


@pytest.mark.parametrize('scenario,code', [
    ("$script:OwnsMutex = $false", 'BACKEND_SAFE_STOP_OWNER_NOT_ATTESTED'),
    ("$script:OwnedBackendSession = $null", 'BACKEND_SAFE_STOP_OWNED_CHANNEL_REQUIRED'),
    ("$script:OwnedBackendSession.Alive = $false", 'BACKEND_SAFE_STOP_OWNER_NOT_ATTESTED'),
    ("$script:BackendProcess = New-TestProcess", 'BACKEND_SAFE_STOP_OWNER_NOT_ATTESTED'),
    ("$script:StopResult.State='blocked'; $script:StopResult.ExactExit=$false; $script:StopResult.Rearmed=$true", 'BACKEND_SAFE_STOP_PREFLIGHT_REARMED'),
    ("$script:StopResult.State='unknown'; $script:StopResult.ExactExit=$false", 'BACKEND_SAFE_STOP_UNKNOWN'),
    ("$script:StopResult.State='unknown'; $script:StopResult.ExactExit=$false; $script:StopResult.Reason='STOP_TIMEOUT'", 'BACKEND_SAFE_STOP_TIMEOUT'),
    ("$script:StopResult.ExactExit=$false", 'BACKEND_SAFE_STOP_UNKNOWN'),
])
def test_refusal_restores_launcher_and_never_touches_frontend(tmp_path, scenario, code):
    result = _run_isolated_launcher(tmp_path, SETUP + '\n' + scenario + r"""
function Stop-FrontendService { throw 'FRONTEND_MUST_NOT_BE_TOUCHED' }
$retained = $script:BackendProcess
$mutexHeld = $script:OwnsMutex
Exit-Launcher -Reason 'test-exit'
if ([System.Windows.Forms.Application]::Exits -ne 0 -or $script:LauncherExitReady -or
    $script:IsShuttingDown -or $script:ServiceStopInProgress -or $script:OwnsMutex -ne $mutexHeld -or
    -not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled -or -not $script:NotifyIcon.Visible -or
    -not [object]::ReferenceEquals($retained, $script:BackendProcess)) { throw 'OWNER_OR_UI_LOST' }
""")
    assert any('LAUNCHER_EXIT_BLOCKED' in line and code in line for line in result['logs'])


def test_unknown_is_not_resent_and_rearmed_requires_later_explicit_action(tmp_path):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
$script:StopResult.State='blocked'; $script:StopResult.ExactExit=$false; $script:StopResult.Rearmed=$true
try { Stop-Services } catch { }
if ($script:BackendStopExpected -or $script:OwnedBackendSession.Terminal) { throw 'REARM_NOT_PRESERVED' }
$first = $script:StopResult.RequestId
$script:StopResult.State='unknown'; $script:StopResult.Rearmed=$false
try { Stop-Services } catch { }
$unknown = $script:StopResult.RequestId
if ($unknown -eq $first) { throw 'NEW_EXPLICIT_ACTION_REUSED_REFUSED_UUID' }
Exit-Launcher -Reason 'unknown-replay'
if ($script:StopResult.RequestId -ne $unknown) { throw 'UNKNOWN_UUID_REPLACED' }
""")
    assert result['calls'].count('backend-stop') == 2


def test_completed_stop_routes_frontend_after_backend_and_exit_only_after_both(tmp_path):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
$script:ProbeReentrancy = $true
function Stop-FrontendService {
    param([switch]$RequireSafeStop)
    if (-not $RequireSafeStop -or $script:OwnedBackendSession.LastStop.State -ne 'stopped') { throw 'ORDER_OR_SAFE_FLAG_LOST' }
    if ([System.Windows.Forms.Application]::Exits) { throw 'LAUNCHER_EXITED_EARLY' }
    $script:Calls.Add('frontend-stop')
}
Stop-Services
if ($script:IsShuttingDown -or [System.Windows.Forms.Application]::Exits) { throw 'STOP_EXITED_LAUNCHER' }
Exit-Launcher -Reason 'after-stop'
if ([System.Windows.Forms.Application]::Exits -ne 1 -or -not $script:LauncherExitReady) { throw 'EXIT_NOT_ROUTED' }
""")
    assert result['calls'] == ['backend-stop', 'restore', 'frontend-stop', 'frontend-stop']


def test_frontend_without_safe_channel_refuses_before_backend_and_retains_both(tmp_path):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
$script:FrontendProcess = New-TestProcess
$frontend = $script:FrontendProcess
Exit-Launcher -Reason 'frontend-blocked'
if ([System.Windows.Forms.Application]::Exits -or -not $script:Timer.Enabled -or
    -not [object]::ReferenceEquals($frontend, $script:FrontendProcess)) { throw 'FRONTEND_OR_OWNER_LOST' }
$evidence = $script:OwnedBackendSession.LastStop
Exit-Launcher -Reason 'frontend-still-blocked'
if (-not [object]::ReferenceEquals($evidence, $script:OwnedBackendSession.LastStop)) { throw 'BACKEND_REPLAYED' }
""")
    assert result['calls'].count('backend-stop') == 0
    assert any('FRONTEND_SAFE_STOP_UNAVAILABLE' in line for line in result['logs'])


def test_restart_and_unapproved_cleanup_cannot_bypass_safe_stop(tmp_path):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
try { Restart-Services; throw 'TRAY_RESTART_ACCEPTED' }
catch { if ($_.Exception.Message -ne 'OWNED_RESTART_NOT_AVAILABLE_FROM_TRAY') { throw } }
$cleanup = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $node.Member.Value -eq 'add_ApplicationExit'
}, $true)
& $cleanup.Arguments[0].ScriptBlock.GetScriptBlock()
if (-not $script:OwnsMutex -or -not $script:Timer.Enabled) { throw 'UNAPPROVED_CLEANUP' }
""")
    assert not result['calls']


def test_production_stop_invalid_owner_is_terminal_and_never_replayed(tmp_path):
    result = _run_isolated_launcher(tmp_path, r"""
Add-Type -Path (Join-Path (Split-Path (Split-Path $ast.Extent.File)) 'scripts/OmiOwnedShutdown.cs') -ReferencedAssemblies @('System.Web.Extensions','System.Core')
$type = [Omi.OwnedShutdown.ProductionSession]
$session = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($type)
$flags = [Reflection.BindingFlags]'Instance,NonPublic'
$type.GetField('stopGate', $flags).SetValue($session, [object]::new())
$type.GetField('stops', $flags).SetValue($session, [Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new())
$id = [Guid]::NewGuid().ToString('D')
$result = $session.Stop($id)
if ($result.ExactExit -or $result.Reason -ne 'OWNER_NOT_ATTESTED' -or -not $session.Terminal) { throw 'INVALID_OWNER_ACCEPTED' }
if (-not [object]::ReferenceEquals($result, $session.Stop($id)) -or
    -not [object]::ReferenceEquals($result, $session.Stop([Guid]::NewGuid().ToString('D')))) { throw 'TERMINAL_REPLAY' }
""")
    assert not result['calls']


@pytest.mark.parametrize('confirmed', [True, False])
def test_failed_startup_exit_is_not_safe_stop_and_unknown_retains_owner(tmp_path, confirmed):
    scenario = SETUP + r"""
$script:OwnedBackendSession.Terminal = $true
$script:OwnedBackendSession.Alive = $false
$script:OwnedBackendSession | Add-Member NoteProperty StartupExitConfirmed CONFIRMED
Exit-Launcher -Reason 'startup-failure'
if ($null -ne $script:OwnedBackendSession.LastStop) { throw 'FABRICATED_SAFE_STOP' }
if ([System.Windows.Forms.Application]::Exits -ne EXPECTED) { throw 'STARTUP_EXIT_RULE_BROKEN' }
"""
    result = _run_isolated_launcher(tmp_path, scenario.replace('CONFIRMED', '$true' if confirmed else '$false').replace('EXPECTED', '1' if confirmed else '0'))
    assert 'backend-stop' not in result['calls']
    assert not any('Backend safe stop result.' in line or line.startswith('Services stopped;') for line in result['logs'])
    if confirmed:
        assert any('OWNED_START_EXIT_CONFIRMED' in line for line in result['logs'])


@pytest.mark.parametrize('confirmed', [True, False])
def test_backend_only_click_distinguishes_failed_startup_exit_from_safe_stop(tmp_path, confirmed):
    scenario = BACKEND_ONLY_TRAY_SETUP + r"""
$script:OwnedBackendSession.Terminal=$true
$script:OwnedBackendSession.Alive=$false
$script:OwnedBackendSession | Add-Member NoteProperty StartupExitConfirmed CONFIRMED
$script:OwnedBackendSession | Add-Member NoteProperty StartupFailure 'OWNED_START_UNKNOWN'
$script:OwnedBackendSession | Add-Member ScriptMethod RefreshStartupExit { return $this.StartupExitConfirmed }
$safeStopBackendItem.PerformClick()
Assert-BackendOnlyOwnerRetained
if ($null -ne $script:OwnedBackendSession.LastStop) { throw 'STARTUP_FAILURE_BECAME_STOP_RECEIPT' }
"""
    result = _run_isolated_launcher(tmp_path, scenario.replace('CONFIRMED', '$true' if confirmed else '$false'))
    assert not result['calls']
    assert not any('Backend stopped' in line for line in result['logs'])
    if confirmed:
        assert 'OWNED_START_EXIT_CONFIRMED: Backend startup failed and both owned processes exited; no Safe Stop was executed.' in result['logs']
    else:
        assert 'BACKEND_SAFE_STOP_UNKNOWN' in result['logs']
        assert not any('OWNED_START_EXIT_CONFIRMED' in line for line in result['logs'])


def test_frontend_race_after_preflight_does_not_claim_full_exit(tmp_path):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
$script:Checks = 0
function Assert-FrontendSafeStopAvailable {
    $script:Checks++
    if ($script:Checks -gt 1) { throw 'FRONTEND_SAFE_STOP_UNAVAILABLE' }
}
Exit-Launcher -Reason 'frontend-race'
if ([System.Windows.Forms.Application]::Exits -or -not $script:OwnedBackendSession.LastStop.ExactExit -or
    $script:Checks -ne 2) { throw 'RACE_FALSE_SUCCESS' }
""")
    assert result['calls'] == ['backend-stop', 'restore']
    assert any('FRONTEND_SAFE_STOP_UNAVAILABLE' in line for line in result['logs'])


@pytest.mark.parametrize('failed', [True, False])
def test_start_services_requires_successful_backend_before_frontend(tmp_path, failed):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
$definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-Services' }, $false)
. ([scriptblock]::Create($definition.Extent.Text))
function Start-Backend { $script:Calls.Add('start-backend'); FAILURE }
function Start-Frontend { $script:Calls.Add('start-frontend') }
Start-Services
""".replace('FAILURE', "throw 'OWNED_START_UNKNOWN'" if failed else 'return'))
    assert result['calls'] == (['start-backend'] if failed else ['start-backend', 'start-frontend'])


@pytest.mark.parametrize('fault', ['startup-failed', 'child-lost', 'terminal'])
def test_repeated_start_cannot_mistake_failed_runner_for_started_backend(tmp_path, fault):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
$definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-Backend' }, $false)
. ([scriptblock]::Create($definition.Extent.Text))
FAULT
try { Start-Backend; throw 'FAILED_RUNNER_ADOPTED' }
catch { if ($_.Exception.Message -ne 'EXPECTED') { throw } }
""".replace('FAULT', {
        'startup-failed': "$script:OwnedBackendSession | Add-Member NoteProperty StartupFailure 'OWNED_START_UNKNOWN'",
        'child-lost': '$script:OwnedBackendSession.Alive=$false',
        'terminal': '$script:OwnedBackendSession.Terminal=$true',
    }[fault]).replace('EXPECTED', 'OWNED_START_UNKNOWN' if fault == 'startup-failed' else 'OWNED_START_NO_AUTOMATIC_REPLAY'))
    assert not result['calls']


@pytest.mark.parametrize('state', ['stopped', 'unknown', 'rearmed', 'startup-exited'])
def test_original_timer_publishes_status_without_dequeue_after_stop(tmp_path, state):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
. (Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1')
function Get-OmiOwnedBackendIdentity { return [pscustomobject]@{pid=42; created_at='same-child'} }
$script:OwnedBackendSession | Add-Member NoteProperty RestartBlocker ''
$script:OwnedBackendSession | Add-Member NoteProperty StartupExitConfirmed ($state -eq 'startup-exited')
$script:OwnedBackendSession.Terminal = $state -ne 'rearmed'
$script:StopResult.ExactExit = $state -eq 'stopped'
$script:OwnedBackendSession.LastStop = $script:StopResult
$script:SafeStopAttempted = $true
$script:RuntimeControlLastPublish = [DateTime]::MinValue
$script:RuntimeController = [pscustomobject]@{}
$script:RuntimeController | Add-Member ScriptMethod Publish {
    param($json, $identity, $attested)
    $status = $json | ConvertFrom-Json
    $expected = if ($state -in @('stopped','startup-exited')) { 'stopped' } elseif ($state -eq 'rearmed') { 'observed' } else { 'unknown' }
    if ($status.backend.status -ne $expected -or $status.restart.available -or
        ($state -ne 'rearmed' -and ($attested -or $null -ne $identity))) { throw 'FALSE_STATUS_PROOF' }
    $script:Calls.Add('published')
}
$script:RuntimeController | Add-Member ScriptMethod TakePending { $script:Calls.Add('dequeued'); throw 'DESTRUCTIVE_DISPATCH' }
$script:RunEvent = $null
$script:ExitEvent = $null
$script:RestartEvent = $null
$timer = $ast.Find({ param($node) $node -is [Management.Automation.Language.InvokeMemberExpressionAst] -and
    $node.Member.Value -eq 'add_Tick' -and $node.Expression.Extent.Text -eq '$script:ActivationTimer' }, $true)
& $timer.Arguments[0].ScriptBlock.GetScriptBlock()
""".replace(". (Join-Path", f"$state = '{state}'\n. (Join-Path", 1))
    assert result['calls'] == ['published']


@pytest.mark.parametrize('fault', ['', 'interpreter', 'pid', 'creation', 'root', 'owner'])
def test_owned_health_is_bound_to_retained_base_python_and_identity(tmp_path, fault):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
foreach ($name in @('Test-BackendHealthMatchesExpected', 'ConvertTo-NormalizedPath')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $false)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:RepoRoot = 'C:\test-omi'
$script:BackendReload = $false
$script:IsPackagedRelease = $false
$session = $script:OwnedBackendSession
$session | Add-Member NoteProperty PythonExecutable 'C:\trusted-base\python.exe'
$session | Add-Member NoteProperty ChildPid 42
$session | Add-Member NoteProperty ChildCreated 'exact-creation'
function Get-OmiOwnedBackendIdentity { return [pscustomobject]@{pid=42; created_at='exact-creation'} }
$health = [pscustomobject]@{runtime=[pscustomobject]@{project_root='C:\test-omi'; python_executable='C:\trusted-base\python.exe'; pid=42; created_at='exact-creation'}}
FAULT
$ok = Test-BackendHealthMatchesExpected $health 'C:\test-omi\.venv\Scripts\python.exe'
if ($ok -ne EXPECTED) { throw 'INTERPRETER_OR_OWNER_MISMATCH' }
""".replace('FAULT', {
        '': '', 'interpreter': "$health.runtime.python_executable='C:\\wrong\\python.exe'",
        'pid': '$health.runtime.pid=43', 'creation': "$health.runtime.created_at='wrong'",
        'root': "$health.runtime.project_root='C:\\wrong'", 'owner': '$session.Alive=$false',
    }[fault]).replace('EXPECTED', '$false' if fault else '$true'))
    assert not result['calls']


@pytest.mark.parametrize('reload', [True, False])
def test_legacy_and_reload_health_keep_original_interpreter_validation(tmp_path, reload):
    result = _run_isolated_launcher(tmp_path, SETUP + r"""
foreach ($name in @('Test-BackendHealthMatchesExpected', 'ConvertTo-NormalizedPath')) {
    $definition=$ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name },$false)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:BackendReload=RELOAD
$script:RepoRoot='C:\test-omi'
if (-not $script:BackendReload) { $script:OwnedBackendSession=$null }
function Get-OmiOwnedBackendIdentity { throw 'LEGACY_MUST_USE_ORIGINAL_CHECK' }
$health=[pscustomobject]@{runtime=[pscustomobject]@{project_root=$script:RepoRoot; python_executable='C:\base\python.exe'}}
if (Test-BackendHealthMatchesExpected $health 'C:\test-omi\.venv\Scripts\python.exe') { throw 'ARBITRARY_BASE_ACCEPTED' }
$health.runtime.python_executable='C:\test-omi\.venv\Scripts\python.exe'
if (-not (Test-BackendHealthMatchesExpected $health $health.runtime.python_executable)) { throw 'LEGACY_CHECK_CHANGED' }
""".replace('RELOAD', '$true' if reload else '$false'))
    assert not result['calls']
