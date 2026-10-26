"""Launcher functions only; synthetic OS observations or disposable tmp runners.

Never execute the launcher entrypoint or contact production OMI endpoints.
"""
import subprocess
import sys

import pytest

from test_launcher_backend_start import RESTART_SETUP
from test_launcher_safe_stop import SETUP as STOP_SETUP
from test_runtime_launcher_recovery import LAUNCHER, SERVICE_RUNNER, _powershell, _run_isolated_launcher


FUNCTIONS = (
    'Test-FrontendRecoveryAdmission',
    'Get-FrontendProcessSnapshot', 'Get-FrontendCreationTicks', 'Assert-FrontendRunnerIdentity',
    'Assert-FrontendListenerOwnership',
    'Assert-FrontendSafeStopAvailable', 'Invoke-FrontendTreeTermination',
    'Stop-FrontendService', 'Restart-Frontend', 'Start-Frontend', 'Start-LoggedService',
)


def load_functions(names=FUNCTIONS):
    return "\n" + "\n".join(
        "$definition=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] "
        f"-and $n.Name -eq '{name}' }},$false); . ([scriptblock]::Create($definition.Extent.Text))"
        for name in names
    ) + "\n"


TREE_SETUP = load_functions() + r"""
$script:OwnsMutex=$true
$script:Mutex=[pscustomobject]@{SafeWaitHandle=[pscustomobject]@{IsClosed=$false;IsInvalid=$false}}
$script:FrontendPort=43123
$script:FrontendHost='127.0.0.1'
$script:Created=([DateTime]'2026-10-19T00:00:00Z').ToUniversalTime()
function New-Row($id,$parent,$offset) {
    return [pscustomobject]@{ProcessId=$id;ParentProcessId=$parent;
        CreationDate=$script:Created.AddSeconds($offset);ExecutablePath='fixture-powershell';CommandLine='fixture frontend args'}
}
function New-Handle($id,$offset) {
    $p=[pscustomobject]@{Id=$id;Handle=123;HasExited=$false;StartTime=$script:Created.AddSeconds($offset)}
    $p | Add-Member ScriptMethod Dispose {}
    return $p
}
$script:Root=New-Handle 41001 0
$script:Child=New-Handle 41002 1
$script:Grandchild=New-Handle 41003 2
$script:FrontendProcess=$script:Root
$script:FrontendRunnerIdentity=[pscustomobject]@{Process=$script:Root;Pid=41001;
    Created=$script:Created;Path='fixture-powershell';Arguments='frontend args';LauncherPid=$PID;
    Handle=123;LauncherCreated=[Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime()}
$script:Rows=@((New-Row 41001 $PID 0),(New-Row 41002 41001 1),(New-Row 41003 41002 2))
$script:Listeners=@(41003)
$script:Bindable=$false
$script:Terminations=0
function Get-FrontendProcessSnapshot { return $script:Rows }
function Get-ListeningProcessIdsOnPort {
    param($Port,[switch]$RequireObservation)
    if (-not $RequireObservation -or $Port -ne 43123) {throw 'OBSERVATION_REQUIRED'}
    return $script:Listeners
}
function Test-TcpPortBindable {return $script:Bindable}
function Get-Process {
    param($Id)
    switch ($Id) {41001 {return $script:Root} 41002 {return $script:Child} 41003 {return $script:Grandchild}}
    throw 'UNKNOWN_PID_LOOKUP'
}
function Invoke-FrontendTreeTermination {
    param($Identity)
    if (-not [object]::ReferenceEquals($Identity,$script:FrontendRunnerIdentity)) {throw 'UNRETAINED_ROOT'}
    $script:Terminations++
    if ($script:KillFault -eq 'timeout') {throw 'FIXTURE_TASKKILL_TIMEOUT'}
    $script:Root.HasExited=$true;$script:Child.HasExited=$true;$script:Grandchild.HasExited=$true
    $script:Rows=@();$script:Listeners=@();$script:Bindable=$true
    if ($script:KillFault -eq 'runner-alive') {$script:Root.HasExited=$false}
    if ($script:KillFault -eq 'external-listener') {$script:Listeners=@(49000);$script:Bindable=$false}
    if ($script:KillFault -eq 'unreleased-port') {$script:Bindable=$false}
}
function Stop-ProcessTree {throw 'LEGACY_FORCE_FORBIDDEN'}
function Stop-FrontendPortOwners {throw 'PORT_KILL_FORBIDDEN'}
"""


def test_owned_live_tree_stops_runner_and_all_children_without_backend_or_port_kill(tmp_path):
    result = _run_isolated_launcher(tmp_path, TREE_SETUP + r"""
Assert-FrontendSafeStopAvailable
if ($script:Terminations) {throw 'PREFLIGHT_MUTATED'}
Stop-FrontendService -RequireSafeStop
if ($script:Terminations -ne 1 -or $null -ne $script:FrontendProcess -or
    $script:LastFrontendStop.State -ne 'stopped' -or
    $script:FrontendStopUnconfirmed) {throw 'EXIT_NOT_PROVEN'}
Stop-FrontendService
if ($script:Terminations -ne 1) {throw 'REPLAY'}
""")
    assert not result['calls']


@pytest.mark.parametrize('exit_launcher', [False, True])
def test_full_stop_and_exit_keep_backend_safe_stop_before_owned_frontend(tmp_path, exit_launcher):
    result = _run_isolated_launcher(tmp_path, STOP_SETUP + TREE_SETUP + r"""
$script:BaseTermination=(Get-Item Function:Invoke-FrontendTreeTermination).ScriptBlock
function Invoke-FrontendTreeTermination {
    param($Identity)
    if (-not $script:OwnedBackendSession.LastStop.ExactExit -or $script:Timer.Enabled -or
        $script:ActivationTimer.Enabled -or -not $script:ServiceStopInProgress) {throw 'BACKEND_SAFE_STOP_ORDER_LOST'}
    $script:Calls.Add('frontend-tree-stop')
    & $script:BaseTermination -Identity $Identity
}
ACTION
if ($script:Terminations -ne 1 -or $script:LastServiceStopError -or
    [System.Windows.Forms.Application]::Exits -ne EXITS) {throw 'STOP_OR_EXIT_NOT_COMPLETED'}
""".replace('ACTION', "Exit-Launcher -Reason 'fixture'" if exit_launcher else 'Stop-Services')
        .replace('EXITS', '1' if exit_launcher else '0'))
    assert result['calls'].index('backend-stop') < result['calls'].index('frontend-tree-stop')


@pytest.mark.parametrize('fault', [
    '$script:FrontendRunnerIdentity=$null',
    '$script:FrontendRunnerIdentity.Process=New-Handle 41001 0',
    '$script:Root.StartTime=$script:Created.AddSeconds(20)',
    '$script:FrontendRunnerIdentity.Pid=49000',
    '$script:FrontendRunnerIdentity.LauncherPid=49000',
    '$script:FrontendRunnerIdentity.LauncherCreated=$script:Created',
    '$script:FrontendRunnerIdentity.Handle=0',
    '$script:Root.Handle=124',
    '$script:Mutex=$null',
    '$script:Mutex.SafeWaitHandle.IsClosed=$true',
    '$script:Mutex.SafeWaitHandle.IsInvalid=$true',
    '$script:OwnsMutex=$false',
    '$script:Root.HasExited=$true',
])
def test_unowned_or_unobservable_frontend_refuses_without_any_termination(tmp_path, fault):
    _run_isolated_launcher(tmp_path, TREE_SETUP + fault + r"""
try {Stop-FrontendService;throw 'FALSE_SUCCESS'} catch {if ($_.Exception.Message -ne 'FRONTEND_STOP_UNCONFIRMED') {throw}}
if ($script:Terminations -or -not $script:FrontendStopUnconfirmed -or
    $null -eq $script:FrontendProcess -or $script:LastFrontendStop.State -ne 'unknown') {throw 'UNOWNED_KILL_OR_LOST_EVIDENCE'}
""")


def test_owned_stop_does_not_depend_on_cim_or_descendant_metadata(tmp_path):
    _run_isolated_launcher(tmp_path, TREE_SETUP + r"""
function Get-FrontendProcessSnapshot {throw 'CIM_MUST_NOT_BE_USED_FOR_STOP'}
function Get-Process {throw 'PID_LOOKUP_FORBIDDEN'}
$script:Child.StartTime=$script:Created.AddSeconds(20)
Stop-FrontendService
if ($script:Terminations -ne 1 -or $script:LastFrontendStop.State -ne 'stopped') {throw 'OWNED_STOP_FAILED'}
""")


@pytest.mark.parametrize('fault', ['', 'pid', 'created', 'handle', 'launcher', 'mutex', 'object'])
def test_real_termination_helper_only_targets_retained_birth_pid_once(tmp_path, fault):
    _run_isolated_launcher(tmp_path, TREE_SETUP + load_functions(('Invoke-FrontendTreeTermination',)) +
        f"$script:Fault='{fault}'\n" + r"""
$script:Kills=0
function Start-Process {
    param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru)
    if ($FilePath -ne (Join-Path $env:SystemRoot 'System32\taskkill.exe') -or
        ($ArgumentList -join ' ') -cne '/PID 41001 /T /F' -or $WindowStyle -ne 'Hidden') {throw 'WRONG_TARGET'}
    $script:Kills++
    $helper=[pscustomobject]@{ExitCode=0}
    $helper | Add-Member ScriptMethod WaitForExit {param($timeout) return $timeout -eq 5000}
    $helper | Add-Member ScriptMethod Dispose {}
    return $helper
}
switch ($script:Fault) {
    'pid' {$script:FrontendRunnerIdentity.Pid=49000}
    'created' {$script:Root.StartTime=$script:Created.AddSeconds(1)}
    'handle' {$script:Root.Handle=999}
    'launcher' {$script:FrontendRunnerIdentity.LauncherCreated=$script:Created}
    'mutex' {$script:OwnsMutex=$false}
    'object' {$script:FrontendRunnerIdentity.Process=New-Handle 41001 0}
}
$ok=$false
try {Invoke-FrontendTreeTermination -Identity $script:FrontendRunnerIdentity;$ok=$true}
catch {if ($_.Exception.Message -ne 'FRONTEND_STOP_UNCONFIRMED') {throw}}
if ($ok -ne (-not $script:Fault) -or $script:Kills -ne [int]$ok) {throw 'UNOWNED_KILL'}
""")


def test_spawn_retains_birth_fields_accepted_by_identity_guard_without_cim(tmp_path):
    _run_isolated_launcher(tmp_path, TREE_SETUP + r"""
$script:Root | Add-Member NoteProperty Path 'fixture-powershell'
$script:RepoRoot='fixture-root';$script:ServiceRunner='fixture-runner'
function Test-Path {return $true}
function Start-Process {return $script:Root}
function Get-FrontendProcessSnapshot {throw 'BIRTH_CIM_FORBIDDEN'}
$spawned=Start-LoggedService -ServiceName frontend -FilePath 'fixture-npm' -Arguments @('run','dev') -WorkingDirectory 'fixture-ui'
Assert-FrontendRunnerIdentity -Identity $script:FrontendRunnerIdentity
if (-not [object]::ReferenceEquals($spawned,$script:FrontendRunnerIdentity.Process) -or
    $script:FrontendRunnerIdentity.Handle -ne $spawned.Handle -or
    $script:FrontendRunnerIdentity.Pid -ne $spawned.Id -or
    $script:FrontendRunnerIdentity.Created -ne $spawned.StartTime.ToUniversalTime()) {throw 'BIRTH_FIELDS_DRIFTED'}
""")


def test_stop_waits_for_retained_exit_and_port_release_without_second_termination(tmp_path):
    _run_isolated_launcher(tmp_path, TREE_SETUP + r"""
function Invoke-FrontendTreeTermination {param($Identity) $script:Terminations++}
$script:Waits=0
function Start-Sleep {
    param($Milliseconds)
    $script:Waits++
    if ($script:Waits -eq 1) {$script:Root.HasExited=$true}
    if ($script:Waits -eq 2) {$script:Listeners=@();$script:Bindable=$true}
}
Stop-FrontendService
if ($script:Terminations -ne 1 -or $script:Waits -ne 2 -or $script:LastFrontendStop.State -ne 'stopped') {
    throw 'FALSE_STOP_OR_KILL_RETRY'
}
""")


@pytest.mark.parametrize('observation', ['recover', 'unavailable', 'foreign', 'reused-root', 'changed-generation'])
def test_start_waits_for_http_before_snapshot_and_bounds_unknown_without_respawn(tmp_path, observation):
    _run_isolated_launcher(tmp_path, TREE_SETUP + f"$script:Observation='{observation}'\n" + r"""
$script:ServiceStartRequestInProgress=$true
$script:HealthCalls=0;$script:SnapshotCalls=0;$script:Spawns=0
function Start-Frontend {
    $script:Spawns++
    if ($script:LastFrontendStop.State -ne 'stopped') {throw 'STOP_REQUIRED'}
    $script:Root.HasExited=$false;$script:FrontendProcess=$script:Root
    $script:Rows=@((New-Row 41001 $PID 0),(New-Row 41002 41001 1),(New-Row 41003 41002 2))
    $script:Listeners=@(41003)
}
function Test-FrontendOk {
    $script:HealthCalls++
    if ($script:HealthCalls -le 3) {
        if ($script:SnapshotCalls) {throw 'CIM_BEFORE_HTTP_READY'}
        return $false
    }
    return $true
}
function Get-FrontendProcessSnapshot {
    $script:SnapshotCalls++
    if ($script:HealthCalls -le 3) {throw 'CIM_BEFORE_HTTP_READY'}
    if ($script:Observation -eq 'unavailable' -or $script:SnapshotCalls -eq 1) {throw 'CIM_TRANSIENT'}
    if ($script:Observation -eq 'foreign') {$script:Rows[2].ParentProcessId=$PID}
    if ($script:Observation -eq 'reused-root') {$script:Rows[0].CreationDate=$script:Created.AddSeconds(10)}
    if ($script:Observation -eq 'changed-generation') {$script:FrontendRunnerIdentity=$script:FrontendRunnerIdentity.PSObject.Copy()}
    return $script:Rows
}
# Shorten only the fixture's wall-clock budget. Production remains 30 seconds.
. ([scriptblock]::Create('function Restart-Frontend {' +
    (Get-Item Function:Restart-Frontend).ScriptBlock.ToString().Replace('-lt 30000','-lt 1500') + '}'))
$ok=$false;$reason=$null
try {Restart-Frontend;$ok=$true} catch {$reason=$_.Exception.Message}
if ($ok -ne ($script:Observation -eq 'recover') -or $script:Spawns -ne 1 -or $script:Terminations -ne 1) {
    throw "FALSE_READY_OR_RETRY: $reason"
}
if ($script:Observation -eq 'unavailable') {
    if ($reason -ne 'FRONTEND_START_READINESS_UNCONFIRMED' -or $script:SnapshotCalls -lt 2) {throw 'UNKNOWN_ACCEPTED'}
} elseif ($script:SnapshotCalls -ne 2) {throw 'SNAPSHOT_RETRY_AFTER_HARD_RESULT'}
""")


@pytest.mark.parametrize('fault', ['timeout', 'runner-alive', 'external-listener', 'unreleased-port'])
def test_failed_tree_stop_retains_unknown_and_never_retries_or_cleans_ports(tmp_path, fault):
    _run_isolated_launcher(tmp_path, TREE_SETUP + f"$script:KillFault='{fault}'\n" + r"""
. ([scriptblock]::Create('function Stop-FrontendService {' + (Get-Item Function:Stop-FrontendService).ScriptBlock.ToString().Replace('-lt 5000','-lt 20') + '}'))
try {Stop-FrontendService} catch {if ($_.Exception.Message -ne 'FRONTEND_STOP_UNCONFIRMED') {throw}}
try {Stop-FrontendService} catch {if ($_.Exception.Message -ne 'FRONTEND_STOP_UNCONFIRMED') {throw}}
if ($script:Terminations -ne 1 -or $script:LastFrontendStop.State -ne 'unknown' -or
    -not $script:FrontendStopUnconfirmed -or $null -eq $script:FrontendProcess) {throw 'FALSE_SUCCESS_OR_REPLAY'}
""")


START_SETUP = TREE_SETUP + r"""
Stop-FrontendService
$script:ServiceStartRequestInProgress=$true
$script:SafeStopAttempted=$true
$script:IsPackagedRelease=$true
$script:FrontendDir='fixture-frontend'
$script:PackagedNode='fixture-node'
$script:Spawns=0
function Test-Path {return $true}
function Find-ExpectedFrontendPort {throw 'HEALTH_ADOPTION_FORBIDDEN'}
function Select-AvailableFrontendPortForStart {throw 'PORT_RESELECTION_FORBIDDEN'}
function Start-LoggedService {$script:Spawns++;return [pscustomobject]@{Id=42001}}
"""


def test_explicit_frontend_start_consumes_confirmed_stop_without_unlocking_backend(tmp_path):
    _run_isolated_launcher(tmp_path, START_SETUP + r"""
try {Start-Frontend;throw 'LEGACY_UNLOCKED'} catch {if ($_.Exception.Message -ne 'SAFE_STOP_NO_START_OR_RECOVERY') {throw}}
Start-Frontend -AfterConfirmedStop
try {Start-Frontend -AfterConfirmedStop;throw 'REPLAY'} catch {if ($_.Exception.Message -ne 'FRONTEND_START_NOT_ATTESTED') {throw}}
if ($script:Spawns -ne 1 -or -not $script:SafeStopAttempted) {throw 'BACKEND_FENCE_OR_SINGLE_ATTEMPT_LOST'}
""")


@pytest.mark.parametrize('fault', [
    '$script:Listeners=@(49000)', '$script:Bindable=$false',
    '$script:FrontendStopUnconfirmed=$true', '$script:ServiceStartRequestInProgress=$false',
    "$script:LastFrontendStop.State='unknown'", '$script:LastFrontendStop.Port=43124',
])
def test_frontend_start_rejects_unknown_stop_and_port_race_without_spawn(tmp_path, fault):
    _run_isolated_launcher(tmp_path, START_SETUP + fault + r"""
try {Start-Frontend -AfterConfirmedStop;throw 'FALSE_SUCCESS'} catch {if ($_.Exception.Message -ne 'FRONTEND_START_NOT_ATTESTED') {throw}}
if ($script:Spawns -or -not $script:SafeStopAttempted) {throw 'UNSAFE_START'}
""")


@pytest.mark.parametrize('fault', ['', 'foreign-listener', 'health-failure', 'listener-lost-after-health'])
def test_frontend_restart_checks_owned_listener_and_health_after_start(tmp_path, fault):
    _run_isolated_launcher(tmp_path, TREE_SETUP + f"$script:ReadyFault='{fault}'\n" + r"""
$script:ServiceStartRequestInProgress=$true
function Start-Frontend {
    param([switch]$AfterConfirmedStop)
    if (-not $AfterConfirmedStop -or $script:LastFrontendStop.State -ne 'stopped') {throw 'START_BEFORE_STOP'}
    $script:Root.HasExited=$false;$script:Child.HasExited=$false;$script:Grandchild.HasExited=$false
    $script:FrontendProcess=$script:Root
    $script:Rows=@((New-Row 41001 $PID 0),(New-Row 41002 41001 1),(New-Row 41003 41002 2))
    $script:Listeners=@(41003)
    if ($script:ReadyFault -eq 'foreign-listener') {$script:Listeners=@(49000);$script:Rows+=New-Row 49000 $PID 1}
}
function Test-FrontendOk {
    $script:Calls.Add('ui-health')
    if ($script:ReadyFault -eq 'health-failure') {throw 'FIXTURE_HEALTH_FAILURE'}
    if ($script:ReadyFault -eq 'listener-lost-after-health') {$script:Listeners=@()}
    return $true
}
if ($script:ReadyFault) {
    . ([scriptblock]::Create('function Restart-Frontend {' + (Get-Item Function:Restart-Frontend).ScriptBlock.ToString().Replace('-lt 30000','-lt 50') + '}'))
}
$ok=$false
try {Restart-Frontend;$ok=$true} catch {if (-not $script:ReadyFault) {throw}}
if ($ok -ne (-not $script:ReadyFault) -or $script:Terminations -ne 1 -or
    $null -eq $script:FrontendProcess) {throw 'FALSE_READY_OR_RETRY'}

""")


COORDINATION_SETUP = RESTART_SETUP + r"""
function Assert-FrontendSafeStopAvailable {$script:Calls.Add('frontend-preflight')}
function Assert-FrontendRunnerIdentity {}
function Test-FrontendOk {return $true}
function Test-HttpOk {return $script:FinalBackendReady}
$script:FinalBackendReady=$true
function Restart-Frontend {
    if ($script:Timer.Enabled -or $script:ActivationTimer.Enabled -or -not $script:ServiceStartRequestInProgress -or
        $script:LastBackendRestart.State -ne 'succeeded') {throw 'FRONTEND_BEFORE_BACKEND_OR_UNSERIALIZED'}
    $script:Calls.Add('frontend-restart')
    if ($script:FrontendFailure) {throw 'FRONTEND_STOP_UNCONFIRMED'}
}
"""


@pytest.mark.parametrize('fault,stage,backend,frontend', [
    ('', 'complete', 'ready', 'ready'),
    ("$script:StopMode='unknown'", 'backend-restart', 'unconfirmed', 'unchanged'),
    ("$script:StopMode='rearmed'", 'backend-restart', 'unconfirmed', 'unchanged'),
    ('$script:Ready=$false', 'backend-restart', 'unconfirmed', 'unchanged'),
    ('$script:FrontendFailure=$true', 'frontend-restart', 'ready', 'unconfirmed'),
    ('$script:FinalBackendReady=$false', 'final-readiness', 'unconfirmed', 'ready'),
])
def test_full_restart_uses_real_owned_backend_flow_then_frontend_with_partial_result(tmp_path, fault, stage, backend, frontend):
    result = _run_isolated_launcher(tmp_path, COORDINATION_SETUP + fault + r"""
try {Restart-Services} catch {if ($_.Exception.Message -notmatch '^FULL_SERVICE_RESTART_INCOMPLETE') {throw}}
$r=$script:LastFullServiceRestart
if ($r.Stage -ne 'STAGE' -or $r.Backend -ne 'BACKEND' -or $r.Frontend -ne 'FRONTEND') {throw ($r|ConvertTo-Json -Compress)}
if (($r.State -eq 'succeeded') -ne ('STAGE' -eq 'complete') -or
    $script:ServiceStartRequestInProgress -or -not $script:Timer.Enabled -or -not $script:ActivationTimer.Enabled) {throw 'RESULT_OR_GUARD_LOST'}
if ($script:RestartIds.Count -ne 1 -or $script:RestartIds[0] -ne $r.RequestId -or
    $script:Calls.Contains('authenticated-intent')) {throw 'LOCAL_UUID_OR_NO_REPLAY_LOST'}
""".replace('STAGE', stage).replace('BACKEND', backend).replace('FRONTEND', frontend))
    assert result['calls'].count('backend-stop') == 1
    assert result['calls'].count('frontend-restart') == (0 if stage == 'backend-restart' else 1)


def test_frontend_failure_keeps_completed_backend_restart_as_partial(tmp_path):
    result = _run_isolated_launcher(tmp_path, COORDINATION_SETUP + r"""
function Restart-Frontend {throw 'FRONTEND_STOP_UNCONFIRMED'}
try {Restart-Services} catch {}
if ($script:LastFullServiceRestart.Stage -ne 'frontend-restart' -or
    $script:LastFullServiceRestart.State -ne 'partial' -or
    $script:LastFullServiceRestart.Backend -ne 'ready' -or -not $script:SafeStopAttempted) {throw 'BACKEND_RESULT_LOST'}
""")
    assert result['calls'].count('backend-stop') == 1


@pytest.mark.parametrize('entry', ['event', 'tray', 'full'])
def test_restart_event_and_click_coalesce_with_original_owner_and_explicit_scope(tmp_path, entry):
    result = _run_isolated_launcher(tmp_path, COORDINATION_SETUP + f"$entry='{entry}'\n" + r"""
function New-PendingEvent($pending) {
    $event=[pscustomobject]@{Pending=$pending;Resets=0}
    $event | Add-Member ScriptMethod WaitOne {param($timeout) $p=$this.Pending;$this.Pending=$false;return $p}
    $event | Add-Member ScriptMethod Reset {$this.Pending=$false;$this.Resets++}
    return $event
}
$script:RestartBackendEvent=New-PendingEvent $true
$script:RestartEvent=New-PendingEvent ($entry -eq 'full')
$script:RunEvent=New-PendingEvent $false
$script:ExitEvent=New-PendingEvent $false
$script:ActivationEvent=New-PendingEvent $false
function Invoke-OmiRuntimeControlTick {}
if ($entry -ne 'full') {
    function Restart-Frontend {throw 'BACKEND_ONLY_TOUCHED_FRONTEND'}
    function Assert-FrontendSafeStopAvailable {throw 'BACKEND_ONLY_FRONTEND_PREFLIGHT'}
    function Test-FrontendOk {throw 'BACKEND_ONLY_FRONTEND_HTTP'}
}
$tick=$ast.Find({param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and
    $n.Member.Value -eq 'add_Tick' -and $n.Expression.Extent.Text -eq '$script:ActivationTimer'},$true)
$tickBody=[scriptblock]::Create($tick.Arguments[0].ScriptBlock.Extent.Text.Trim('{','}'))
if ($entry -eq 'tray') {$restartBackendItem.PerformClick()} else {& $tickBody}
# A pending duplicate and the other restart event must be drained in finally.
& $tickBody
if ($script:RestartIds.Count -ne 1 -or $script:SpawnCount -ne 1 -or $script:RestartBackendEvent.Pending -or
    $script:RestartBackendEvent.Resets -lt 1 -or -not [object]::ReferenceEquals($frontend,$script:FrontendProcess)) {
    throw 'DOUBLE_FIRE_OR_FRONTEND_CHANGED'
}
""")
    assert result['calls'].count('backend-stop') == 1
    assert result['calls'].count('frontend-restart') == (1 if entry == 'full' else 0)


@pytest.mark.parametrize('owner', [False, True])
@pytest.mark.parametrize('available', [False, True])
def test_secondary_backend_action_requires_existing_owner_and_only_signals_its_event(tmp_path, owner, available):
    _run_isolated_launcher(tmp_path, f"$owner=${str(owner).lower()};$available=${str(available).lower()}\n" + r"""
$LauncherAction='RestartBackend'
$script:OwnsMutex=-not $owner
$script:RestartBackendEventName='fixture-backend-event'
$script:RestartEventName='forbidden-full-event'
$script:AppDisplayName='fixture'
$script:Mutex=[pscustomobject]@{}
$script:Mutex | Add-Member ScriptMethod ReleaseMutex {$script:Calls.Add('release-mutex')}
$script:Mutex | Add-Member ScriptMethod Dispose {$script:Calls.Add('dispose-mutex')}
function Show-Message {throw 'NO_DIALOG'}
function Start-Process {throw 'NO_SPAWN'}
function Open-TestEvent($name) {
    if ($name -ne 'fixture-backend-event') {throw 'WRONG_EVENT'}
    $script:Calls.Add('open-backend-event')
    if (-not $available) {throw 'MISSING_EVENT'}
    $event=[pscustomobject]@{}
    $event | Add-Member ScriptMethod Set {$script:Calls.Add('signal-backend-event');return $true}
    $event | Add-Member ScriptMethod Dispose {}
    return $event
}
if ($owner) {
    $branch=$ast.Find({param($n) $n -is [Management.Automation.Language.IfStatementAst] -and
        $n.Clauses[0].Item1.Extent.Text -eq '-not $script:OwnsMutex'},$false)
} else {
    $branch=$ast.Find({param($n) $n -is [Management.Automation.Language.IfStatementAst] -and
        $n.Clauses[0].Item1.Extent.Text -like '$LauncherAction -in *RestartBackend*'},$false)
}
if ($null -eq $branch) {throw 'MISSING_BRANCH'}
$body=$branch.Extent.Text.Replace('[System.Threading.EventWaitHandle]::OpenExisting(', '(Open-TestEvent ')
$body=$body.Replace('exit 0',"throw 'EXIT_0'").Replace('exit 2',"throw 'EXIT_2'").Replace('exit 3',"throw 'EXIT_3'")
$reason=$null
try {& ([scriptblock]::Create($body))} catch {$reason=$_.Exception.Message}
$expected=if(-not $owner){'EXIT_3'}elseif($available){'EXIT_0'}else{'EXIT_2'}
if ($reason -ne $expected -or $script:Calls.Contains('signal-backend-event') -ne ($owner -and $available) -or
    $script:Calls.Contains('open-backend-event') -ne $owner) {throw "UNSAFE_SECONDARY: $reason"}
""")


RECOVERY_SETUP = TREE_SETUP + load_functions(('Invoke-FrontendHealthRecovery',)) + r"""
. (Join-Path (Split-Path $ast.Extent.File) 'omi-runtime-control.ps1')
$script:SafeStopAttempted=$true
$script:OwnedBackendSession=[pscustomobject]@{Alive=$true;Terminal=$false}
$script:RestartReadyBackendSession=$script:OwnedBackendSession
$script:FrontendHealthRecoveryAttempts=0
$script:Spawns=0
$script:Clears=0
$script:FrontendDir='fixture-frontend'
$script:FrontendDevBundlerArgument='--webpack'
function Show-Message {param($Message) $script:Calls.Add($Message)}
function Get-FrontendHealth {return $null}
function Find-ExpectedFrontendPort {return $null}
function Test-HttpOk {return $false}
function Select-AvailableFrontendPortForStart {}
function Test-Path {return $true}
function Get-Command {return [pscustomobject]@{Source='fixture-npm'}}
function Clear-FrontendDevOutput {$script:Clears++}
function Start-LoggedService {$script:Spawns++;return (New-Handle 42001 10)}
"""


@pytest.mark.parametrize('state', ['initial', 'backend-restarted', 'full-restarted'])
def test_health_recovery_runs_real_stop_and_normal_start_with_admitted_generation(tmp_path, state):
    setup = {
        'initial': '$script:SafeStopAttempted=$false;$script:OwnedBackendSession=$null',
        'backend-restarted': '',
        'full-restarted': "$script:LastFullServiceRestart=[pscustomobject]@{State='succeeded'}",
    }[state]
    _run_isolated_launcher(tmp_path, RECOVERY_SETUP + setup + r"""
$fence=$script:SafeStopAttempted
if (-not (Invoke-FrontendHealthRecovery)) {throw 'RECOVERY_REFUSED'}
if ($script:Terminations -ne 1 -or $script:Spawns -ne 1 -or $script:Clears -ne 1 -or
    $script:SafeStopAttempted -ne $fence -or $script:FrontendHealthRecoveryInProgress) {throw 'UNSAFE_RECOVERY'}
if ($fence) {
    Invoke-ServiceStartRequest -Reason 'fixture'
    if ($script:Calls.Contains('start') -or $script:Spawns -ne 1 -or
        -not ($script:Calls -match '^SAFE_STOP_NO_START_OR_RECOVERY:')) {throw 'SERVICE_START_FENCE_LOST'}
}
""")


@pytest.mark.parametrize('fault', [
    '$script:OwnedBackendSession=$null',
    '$script:OwnedBackendSession.Alive=$false',
    '$script:OwnedBackendSession.Terminal=$true',
    '$script:RestartReadyBackendSession=$null',
    '$script:OwnedBackendSession=[pscustomobject]@{Alive=$true;Terminal=$false}',
    "$script:LastBackendStartError='failed'",
    '$script:FrontendStopUnconfirmed=$true',
    "$script:LastFullServiceRestart=[pscustomobject]@{State='partial'}",
    "$script:LastFullServiceRestart=[pscustomobject]@{State='unknown'}",
    "$script:LastFullServiceRestart=[pscustomobject]@{State='blocked_or_unconfirmed'}",
    '$script:ServiceStopInProgress=$true',
    '$script:ServiceStartRequestInProgress=$true',
    '$script:RuntimeControlInProgress=$true',
    '$script:BackendRecoveryInProgress=$true',
    '$script:IsShuttingDown=$true',
    "function Test-OmiRemoteRestartGeneration {throw 'OBSERVATION_FAILED'}",
])
def test_health_recovery_and_normal_start_refuse_unverified_or_busy_state(tmp_path, fault):
    _run_isolated_launcher(tmp_path, RECOVERY_SETUP + fault + r"""
if (Invoke-FrontendHealthRecovery) {throw 'FALSE_RECOVERY'}
try {Start-Frontend;throw 'FALSE_START'} catch {if ($_.Exception.Message -ne 'SAFE_STOP_NO_START_OR_RECOVERY') {throw}}
if ($script:Terminations -or $script:Spawns -or $script:Clears -or
    $script:FrontendHealthRecoveryAttempts -or -not $script:SafeStopAttempted) {throw 'FENCE_MUTATED'}
""")


def test_normal_start_rechecks_successor_after_frontend_stop(tmp_path):
    _run_isolated_launcher(tmp_path, RECOVERY_SETUP + r"""
function Clear-FrontendDevOutput {$script:OwnedBackendSession.Terminal=$true}
if (Invoke-FrontendHealthRecovery) {throw 'STALE_ADMISSION'}
if ($script:Terminations -ne 1 -or $script:Spawns -or -not $script:SafeStopAttempted -or
    $script:FrontendHealthRecoveryInProgress) {throw 'RECHECK_OR_FENCE_LOST'}
""")


def test_disposable_legacy_retry_runner_tree_exit_and_port_release(tmp_path):
    # Real legacy runner + cmd + Python child, private temporary files, port 0.
    # The child exits once to prove retry was active before the entire tree stop.
    child = tmp_path / 'frontend_child.py'
    child.write_text(
        'import pathlib, socket, time\n'
        f'root=pathlib.Path({str(tmp_path)!r})\n'
        'marker=root/"attempt"\n'
        'if not marker.exists():\n'
        ' marker.write_text("1"); raise SystemExit(17)\n'
        's=socket.socket(); s.bind(("127.0.0.1",0)); s.listen()\n'
        '(root/"port").write_text(str(s.getsockname()[1]))\n'
        'until=time.monotonic()+35\n'
        'while time.monotonic()<until: time.sleep(.1)\n', encoding='utf-8')
    quote = lambda value: str(value).replace("'", "''")
    harness = tmp_path / 'disposable-tree.ps1'
    harness.write_text(r"""
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('LAUNCHER',[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw 'PARSE_FAILED'}
""".replace('LAUNCHER', quote(LAUNCHER)) + load_functions(FUNCTIONS + (
        'Get-ListeningProcessIdsOnPort', 'Test-TcpPortBindable',
    )) + r"""
function Write-LauncherLog {param($Message,$Level)}
$script:OwnsMutex=$true
$script:Mutex=[pscustomobject]@{SafeWaitHandle=[pscustomobject]@{IsClosed=$false;IsInvalid=$false}}
$script:FrontendHost='127.0.0.1'
$script:RepoRoot='ROOT'
$script:ServiceRunner='RUNNER'
$script:FrontendProcess=Start-LoggedService -ServiceName frontend -FilePath 'PYTHON' -Arguments @('CHILD') -WorkingDirectory 'ROOT'
$runner=$script:FrontendProcess
try {
    $clock=[Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath 'ROOT/port') -and $clock.ElapsedMilliseconds -lt 15000) {Start-Sleep -Milliseconds 100}
    $script:FrontendPort=[int](Get-Content -LiteralPath 'ROOT/port')
    if ($script:FrontendPort -in @(3000,8400)) {throw 'PRODUCTION_PORT_FORBIDDEN'}
    Assert-FrontendSafeStopAvailable
    Stop-FrontendService -RequireSafeStop
    if (-not $runner.HasExited -or $script:LastFrontendStop.State -ne 'stopped') {throw 'TREE_EXIT_UNCONFIRMED'}
    Start-Sleep -Milliseconds 600
    if (@(Get-ListeningProcessIdsOnPort -Port $script:FrontendPort -RequireObservation).Count) {throw 'RESPAWN'}
    'DISPOSABLE_TREE_PASS'
} finally {
    # No cleanup by port or name. The disposable child also expires on its own.
    if (-not $runner.HasExited) {
        $cleanup=Start-Process -FilePath "$env:SystemRoot/System32/taskkill.exe" -ArgumentList @('/PID',"$($runner.Id)",'/T','/F') -WindowStyle Hidden -PassThru
        if (-not $cleanup.WaitForExit(5000)) {$cleanup.Kill()}
        $cleanup.Dispose()
    }
    $runner.Dispose()
}
""".replace('ROOT', quote(tmp_path)).replace('RUNNER', quote(SERVICE_RUNNER))
        .replace('PYTHON', quote(sys.executable)).replace('CHILD', quote(child)), encoding='utf-8-sig')
    result = subprocess.run([_powershell(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(harness)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DISPOSABLE_TREE_PASS' in result.stdout
    logs = list((tmp_path / 'logs/frontend').glob('*/frontend.log'))
    assert len(logs) == 1
    assert 'Service restart scheduled.' in logs[0].read_text(encoding='utf-8-sig')
