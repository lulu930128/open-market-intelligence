"""Cold admission and Run routing: real AST, mocked OS/process boundaries only.

Never execute the Launcher entrypoint, production factory spawn, env setup,
named events, HTTP, CIM, private receipts, providers or database.
"""
import pytest

from test_launcher_safe_stop import SETUP
from test_launcher_frontend_lifecycle import COORDINATION_SETUP, load_functions
from test_runtime_launcher_recovery import _run_isolated_launcher


COLD_SETUP = SETUP + load_functions(('Start-Backend', 'Start-Services')) + r"""
. (Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1')
$script:OwnedBackendStartAttempted=$false
$script:OwnedBackendSession=$null
$script:BackendProcess=$null
$script:FrontendProcess=$null
$script:FrontendRunnerIdentity=$null
$script:BackendReload=$false
$script:IsPackagedRelease=$false
$script:BackendDir='fixture-backend'
$script:BackendHost='127.0.0.1'; $script:BackendPort=43121
$script:FrontendHost='127.0.0.1'; $script:FrontendPort=43122
$script:Mutex=[pscustomobject]@{SafeWaitHandle=[pscustomobject]@{IsClosed=$false;IsInvalid=$false}}
$script:RuntimeController=[pscustomobject]@{OwnerId='fixture-owner'}
$script:LoadedLifecycleSourceId='loaded'; $script:DiskSource='changed'
$script:FactoryCalls=0
$script:RealFactory=(Get-Item Function:New-OmiProductionOwnedBackend).ScriptBlock
function New-OmiProductionOwnedBackend {
    $script:FactoryCalls++
    # The real pre-spawn factory is safe here only while source mismatches.
    if ($script:DiskSource -eq $script:LoadedLifecycleSourceId) {throw 'FIXTURE_SPAWN_UNKNOWN'}
    & $script:RealFactory
}
function Get-OmiLifecycleSourceId {return $script:DiskSource}
function Test-Path {return $true}
function Get-FrontendProcessSnapshot {return @()}
function Initialize-ServiceEnvironment {}
function Start-LoggedService {throw 'LEGACY_SPAWN_FORBIDDEN'}
function Select-AvailableBackendPortForStart {throw 'LEGACY_PORT_CLEANUP_FORBIDDEN'}
function Start-Process {throw 'PROCESS_CONTROL_FORBIDDEN'}
function Stop-Process {throw 'PROCESS_CONTROL_FORBIDDEN'}
function taskkill {throw 'PROCESS_CONTROL_FORBIDDEN'}
"""


def test_cold_source_refusal_stays_before_attempt_and_allows_proven_empty_exit(tmp_path):
    result = _run_isolated_launcher(tmp_path, COLD_SETUP + r"""
for ($i=0;$i -lt 2;$i++) {
    try {Start-Backend;throw 'START_ACCEPTED'}
    catch {if ($_.Exception.Message -ne 'SOURCE_ADOPTION_NOT_ATTESTED') {throw}}
    if ($script:OwnedBackendStartAttempted -or $null -ne $script:OwnedBackendSession) {
        throw 'RED_PREFLIGHT_CONSUMED_COLD_ATTEMPT'
    }
}
if ($script:FactoryCalls) {throw 'FACTORY_ENTERED_BEFORE_ADMISSION'}
Exit-Launcher -Reason 'cold-refusal'
if (-not $script:LauncherExitReady -or [System.Windows.Forms.Application]::Exits -ne 1) {
    throw 'PROVEN_EMPTY_EXIT_BLOCKED'
}
""")
    assert any('OWNED_COLD_START_NOT_ATTEMPTED' in line for line in result['logs'])


def test_run_degraded_reaches_single_owned_full_restart(tmp_path):
    result = _run_isolated_launcher(tmp_path, COORDINATION_SETUP + r"""
function Test-FrontendOk {return $script:Calls.Contains('frontend-restart')}
$script:LastStatusText='API OK; UI degraded'
Invoke-ServiceStartRequest -Reason 'cold-audit-run'
$r=$script:LastFullServiceRestart
if ($null -eq $r -or $r.State -ne 'succeeded') {throw 'RED_RUN_NESTED_RESTART_BLOCKED'}
if ($script:RestartIds.Count -ne 1 -or $script:RestartIds[0] -cne $r.RequestId -or
    $script:ServiceStartRequestInProgress -or -not $script:SafeStopAttempted -or
    -not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled) {throw 'OPERATION_EVIDENCE_LOST'}
""")
    assert result['calls'].count('backend-stop') == 1
    assert result['calls'].count('frontend-restart') == 1
    assert result['calls'].index('backend-stop') < result['calls'].index('frontend-restart')


@pytest.mark.parametrize('fault,reason', [
    ("$script:DiskSource='changed'", 'SOURCE_ADOPTION_NOT_ATTESTED'),
    ('$script:RuntimeController=$null', 'Controller unavailable'),
    ('function Get-ListeningProcessIdsOnPort {return @(444)}', 'FIXED_PORT_NOT_FREE'),
    ('function Test-TcpPortBindable {return $false}', 'FIXED_PORT_NOT_BINDABLE'),
    ("function Get-ListeningProcessIdsOnPort {throw 'PORT_OBSERVATION_UNAVAILABLE'}", 'PORT_OBSERVATION_UNAVAILABLE'),
])
def test_cold_refusal_reason_visible_and_no_factory_attempt(tmp_path, fault, reason):
    result = _run_isolated_launcher(tmp_path, COLD_SETUP + "$script:DiskSource='loaded'\n" + fault + r"""
Start-Services
if ($script:OwnedBackendStartAttempted -or $script:FactoryCalls -or $null -ne $script:OwnedBackendSession) {
    throw 'PREFLIGHT_CONSUMED_ATTEMPT'
}
""")
    assert any(f'Backend failed to start: {reason}.' in line for line in result['logs'])


def test_explicit_retry_after_preflight_resolution_has_one_factory_attempt(tmp_path):
    _run_isolated_launcher(tmp_path, COLD_SETUP + r"""
try {Start-Backend} catch {if ($_.Exception.Message -ne 'SOURCE_ADOPTION_NOT_ATTESTED') {throw}}
$script:DiskSource='loaded'
function New-OmiProductionOwnedBackend {
    if (-not $script:OwnedBackendStartAttempted) {throw 'UNLATCHED_FACTORY'}
    $script:FactoryCalls++
    return [pscustomobject]@{RunnerProcess=[pscustomobject]@{Id=123;HasExited=$false};ChildPid=456}
}
function Publish-OmiRuntimeControlStatus {}
Start-Backend
if (-not $script:OwnedBackendStartAttempted -or $script:FactoryCalls -ne 1 -or
    $script:OwnedBackendSession.ChildPid -ne 456) {throw 'COLD_RECOVERY_FAILED'}
""")


@pytest.mark.parametrize('factory', ['throws', 'source-race', 'null', 'retained-unknown'])
def test_factory_boundary_never_unlocks_even_when_no_session_returns(tmp_path, factory):
    action = {
        'throws': "throw 'FIXTURE_SPAWN_UNKNOWN'",
        'source-race': "$script:DiskSource='changed'; & $script:RealFactory",
        'null': 'return $null',
        'retained-unknown': "return [pscustomobject]@{RunnerProcess=$null;StartupFailure='OWNED_START_UNKNOWN';Terminal=$true;Alive=$false}",
    }[factory]
    _run_isolated_launcher(tmp_path, COLD_SETUP + r"""
$script:DiskSource='loaded'
function New-OmiProductionOwnedBackend {
    $script:FactoryCalls++
    if (-not $script:OwnedBackendStartAttempted) {throw 'UNLATCHED_FACTORY'}
    FACTORY
}
function Publish-OmiRuntimeControlStatus {}
$firstReason=$null
try {Start-Backend} catch {$firstReason=$_.Exception.Message}
if (-not $firstReason) {throw 'AMBIGUOUS_FACTORY_REPORTED_SUCCESS'}
if (-not $script:OwnedBackendStartAttempted -or $script:FactoryCalls -ne 1) {throw 'FACTORY_NOT_CONSUMED'}
try {Start-Backend; throw 'REPLAY_ACCEPTED'}
catch {if ($_.Exception.Message -notin @('OWNED_START_NO_AUTOMATIC_REPLAY','OWNED_START_UNKNOWN')) {throw}}
Exit-Launcher -Reason 'ambiguous-factory'
if ($script:FactoryCalls -ne 1 -or $script:LauncherExitReady -or
    [System.Windows.Forms.Application]::Exits -or -not $script:LastServiceStopError) {throw 'UNKNOWN_UNLOCKED'}
""".replace('FACTORY\n', action + '\n'))


@pytest.mark.parametrize('fault', [
    '$script:OwnsMutex=$false',
    '$script:Mutex=$null',
    '$script:Mutex.SafeWaitHandle.IsClosed=$true',
    '$script:OwnedBackendStartAttempted=$true',
    '$script:OwnedBackendStartAttempted=$null',
    '$script:BackendProcess=New-TestProcess',
    '$script:BackendProcess=New-TestProcess -Exited $true',
    '$script:RetiredBackendSessions=@([pscustomobject]@{})',
    '$script:ManualBackendStartAttemptedSession=[pscustomobject]@{}',
    '$script:FrontendProcess=New-TestProcess',
    '$script:FrontendRunnerIdentity=[pscustomobject]@{}',
    '$script:FrontendStopUnconfirmed=$true',
    "$script:LastFrontendStop=[pscustomobject]@{State='unknown'}",
    'function Get-FrontendProcessSnapshot {return @([pscustomobject]@{ParentProcessId=$PID;ProcessId=123})}',
    "function Get-FrontendProcessSnapshot {throw 'CIM_UNAVAILABLE'}",
    'function Get-ListeningProcessIdsOnPort {param($Port) if ($Port -eq 43121) {return @(444)}}',
    'function Get-ListeningProcessIdsOnPort {param($Port) if ($Port -eq 43122) {return @(444)}}',
    "function Get-ListeningProcessIdsOnPort {throw 'PORT_OBSERVATION_UNAVAILABLE'}",
    'function Test-TcpPortBindable {param($Port) return $Port -ne 43121}',
    'function Test-TcpPortBindable {param($Port) return $Port -ne 43122}',
    '$script:BackendReload=$true',
    '$script:IsPackagedRelease=$true',
])
def test_empty_session_is_not_proof_of_safe_exit(tmp_path, fault):
    _run_isolated_launcher(tmp_path, COLD_SETUP + fault + r"""
Exit-Launcher -Reason 'no-empty-proof'
if ($script:LauncherExitReady -or [System.Windows.Forms.Application]::Exits -or
    -not $script:LastServiceStopError -or $script:FactoryCalls) {throw 'UNPROVEN_EXIT_ACCEPTED'}
""")


def test_proven_cold_stop_then_exit_is_idempotent_without_controller(tmp_path):
    result = _run_isolated_launcher(tmp_path, COLD_SETUP + r"""
$script:RuntimeController=$null
Stop-Services
if ($script:LastServiceStopError -or -not $script:SafeStopAttempted) {throw 'COLD_STOP_FAILED'}
Exit-Launcher -Reason 'after-cold-stop'
if (-not $script:LauncherExitReady -or [System.Windows.Forms.Application]::Exits -ne 1 -or
    $script:OwnedBackendStartAttempted -or $script:FactoryCalls) {throw 'COLD_EXIT_FAILED'}
""")
    assert sum('OWNED_COLD_START_NOT_ATTEMPTED' in line for line in result['logs']) == 2


@pytest.mark.parametrize('entry', ['Start-Services', 'Restart-Services'])
@pytest.mark.parametrize('mode', ['no-owner', 'reload', 'packaged', 'unretained-runner'])
def test_no_owner_or_legacy_service_path_never_reaches_backend_force(tmp_path, entry, mode):
    fault = {
        'no-owner': '$script:OwnsMutex=$false',
        'reload': '$script:BackendReload=$true',
        'packaged': '$script:IsPackagedRelease=$true',
        'unretained-runner': '$script:BackendProcess=New-TestProcess -Exited $true',
    }[mode]
    result = _run_isolated_launcher(tmp_path, COLD_SETUP + fault + r"""
function Get-ListeningProcessIdsOnPort {param($Port) if ($Port -eq 43121) {return @(444)}}
try {ENTRY} catch {$script:Messages.Add($_.Exception.Message)}
if ($script:FactoryCalls -or $script:LauncherExitReady) {throw 'LEGACY_REPLACEMENT_ACCEPTED'}
""".replace('ENTRY', entry))
    assert not any('FORBIDDEN' in line for line in result['logs'])


PUMP_SETUP = COORDINATION_SETUP.replace(
    'public static void DoEvents() { }',
    'public static void DoEvents() { throw new System.Exception("UNEXPECTED_UI_PUMP"); }',
) + r"""
function Test-FrontendOk {return $script:Calls.Contains('frontend-restart')}
$script:LastStatusText='API OK; UI degraded'
$script:PumpChecks=0
function Assert-RestartReentryBlocked {
    if (-not $script:ServiceStartRequestInProgress -or $script:Timer.Enabled -or $script:ActivationTimer.Enabled) {
        throw 'UI_PUMP_UNGUARDED'
    }
    $script:PumpChecks++
    Invoke-ServiceStartRequest -Reason 'pump-run'
    Exit-Launcher -Reason 'pump-exit'
    foreach ($name in @('Restart-Services','Stop-Services')) {
        try {& $name; throw 'REENTRY_ACCEPTED'}
        catch {if ($_.Exception.Message -ne 'SERVICE_OPERATION_IN_PROGRESS') {throw}}
    }
}
function Get-OmiBackendApplicationRelease {
    Assert-RestartReentryBlocked
    return $script:ApplicationRelease
}
$script:ActualRestart=(Get-Item Function:Restart-Services).ScriptBlock
$script:RestartEntries=0
function Restart-Services {
    if (-not $script:ServiceStartRequestInProgress) {$script:RestartEntries++}
    & $script:ActualRestart
}
foreach ($name in @('RestartEvent','ExitEvent')) {
    $event=[pscustomobject]@{Resets=0}
    $event | Add-Member ScriptMethod Reset {
        if (-not $script:ServiceStartRequestInProgress) {throw 'UNGUARDED_COALESCING'}
        $this.Resets++
    }
    Set-Variable -Scope Script -Name $name -Value $event
}
"""


@pytest.mark.parametrize('entry', ["Invoke-ServiceStartRequest -Reason 'run'", 'Restart-Services'])
@pytest.mark.parametrize('fault,state,stage', [
    ('', 'succeeded', 'complete'),
    ("$script:StopMode='unknown'", 'blocked_or_unconfirmed', 'backend-restart'),
    ("$script:StopMode='rearmed'", 'blocked_or_unconfirmed', 'backend-restart'),
    ('$script:FrontendFailure=$true', 'partial', 'frontend-restart'),
    ('$script:FinalBackendReady=$false', 'partial', 'final-readiness'),
    ("function Restart-Frontend {throw 'FRONTEND_STOP_UNCONFIRMED'}", 'partial', 'frontend-restart'),
])
def test_run_and_direct_restart_keep_uuid_reentrancy_partial_and_finally(tmp_path, entry, fault, state, stage):
    _run_isolated_launcher(tmp_path, PUMP_SETUP + fault + r"""
try {ENTRY} catch {if ($_.Exception.Message -notmatch '^FULL_SERVICE_RESTART_INCOMPLETE') {throw}}
$r=$script:LastFullServiceRestart
if ($script:RestartEntries -ne 1 -or $r.State -cne 'STATE' -or $r.Stage -cne 'STAGE' -or
    $script:ServiceStartRequestInProgress -or $script:PumpChecks -lt 1 -or
    -not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled -or
    $script:RestartEvent.Resets -lt 1 -or $script:ExitEvent.Resets -lt 1 -or
    [System.Windows.Forms.Application]::Exits) {throw ('GUARD_OR_RESULT_LOST '+($r|ConvertTo-Json -Compress))}
if ($r.Stage -ne 'frontend-preflight' -and ($script:RestartIds.Count -ne 1 -or
    $r.RequestId -cne $script:RestartIds[0])) {throw 'UUID_LOST'}
$expectedSticky=('STAGE' -ne 'frontend-preflight' -and $script:StopMode -ne 'rearmed')
if ($script:SafeStopAttempted -ne $expectedSticky) {throw 'STICKY_FENCE_LOST'}
if ($expectedSticky) {
    $before=$script:Calls.Count
    Invoke-ServiceStartRequest -Reason 'after-sticky'
    if ($script:RestartEntries -ne 1 -or $script:Calls.Count -ne ($before+1)) {throw 'AUTOMATIC_REPLAY'}
}
""".replace('ENTRY', entry).replace('STATE', state).replace('STAGE', stage))


def test_production_start_overloads_distinguish_cold_from_pinned_restart(tmp_path):
    """Real PowerShell callsite + .NET overload fixture, no process or OMI startup."""
    _run_isolated_launcher(tmp_path, r"""
Add-Type -TypeDefinition @'
namespace Omi.OwnedShutdown {
    public static class ProductionSession {
        public static string Start(string root, string store, string host, int port) {
            return "cold-4";
        }
        public static string Start(string root, string store, string host, int port, string release) {
            return "restart-5:" + (release ?? "<null>");
        }
    }
}
'@
. (Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1')
function Assert-OmiProductionBackendStartPreflight {}
$script:RepoRoot='fixture-root'
$script:RuntimeControlStore='fixture-store'
$script:BackendHost='127.0.0.1'
$script:BackendPort=43121
$cold=New-OmiProductionOwnedBackend
$release='a'*64
$restart=New-OmiProductionOwnedBackend -ExpectedRelease $release
if ($cold -cne 'cold-4' -or $restart -cne "restart-5:$release") {
    throw "START_OVERLOAD_WRONG cold=$cold restart=$restart"
}
foreach ($invalid in @('', $null, ' ')) {
    try {
        New-OmiProductionOwnedBackend -ExpectedRelease $invalid | Out-Null
        throw 'UNPINNED_RESTART_ACCEPTED'
    }
    catch {
        if ($_.Exception.Message -cne 'RESTART_SOURCE_CHANGED') { throw }
    }
}
""", functions=())
