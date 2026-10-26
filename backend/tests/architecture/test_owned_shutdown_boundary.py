"""Private cooperative channel cannot become an HTTP/fixture authority bypass."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_runner_branch_cannot_fall_into_force_or_recovery():
    source = (ROOT / 'scripts/run-service-logged.ps1').read_text(encoding='utf-8-sig')
    branch = source[source.index('if ($OwnedShutdownChannel)'):source.index('# The B4 seam')]
    assert 'exit ([Omi.OwnedShutdown.Runner]::Run' in branch and 'exit 79' in branch
    assert '$LauncherPid -le 0' in branch and 'EXACT_BASE_INTERPRETER_REQUIRED' in branch
    for call in ('Stop-ServiceProcessTree', 'Stop-Process', 'taskkill', 'Start-Process'):
        assert call not in branch


def test_backend_shutdown_does_not_own_process_or_writer_policy():
    source = (ROOT / 'backend/app/owned_uvicorn.py').read_text()
    tree = ast.parse(source)
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not {'runtime.stop', 'os.kill', 'os._exit', 'subprocess.Popen'} & calls
    assert 'server.should_exit = True' in source
    assert 'PRODUCTION_WRITER_COVERAGE_UNAVAILABLE' in source
    assert 'force_exit = True' not in source
    assert source.index('await serving\n') < source.index('state="LIFESPAN_COMPLETE"')


def test_no_public_or_legacy_route_to_disposable_authority():
    for path in ('backend/app/routers/runtime_control.py', 'backend/app/runtime_control.py', 'scripts/omi-launcher.ps1'):
        source = (ROOT / path).read_text(encoding='utf-8-sig')
        assert 'StartDisposable' not in source and 'StopDisposable' not in source
    source = (ROOT / 'scripts/omi-runtime-control.ps1').read_text(encoding='utf-8-sig')
    restart = source[source.index('function Restart-Backend'):source.index('function Invoke-OmiRuntimeControlTick')]
    assert 'Invoke-OwnedBackendRestart -RequestId $RequestId -RemoteRequest' in restart
    launcher = (ROOT / 'scripts/omi-launcher.ps1').read_text(encoding='utf-8-sig')
    restart = launcher.split('function Invoke-OwnedBackendRestart {', 1)[1].split('\nfunction ', 1)[0]
    assert 'BeginAuthenticatedOwnedRestart' in restart and 'CompleteOwnedRestart' in restart
    assert '$script:OwnsMutex' in restart and '$old.HasRetainedIdentity' in restart
    assert 'StopWithinDeadlineAsync' in restart
    assert '.Begin(' not in restart and '.Complete(' not in restart
    for call in ('Stop-BackendService ', 'Stop-ProcessTree ', 'Start-Backend '):
        assert call not in restart


def test_local_stop_uses_retained_deadline_core_without_restart_or_port_kill():
    source = (ROOT / 'scripts/omi-launcher.ps1').read_text(encoding='utf-8-sig')
    def body(name):
        return source.split(f'function {name} {{', 1)[1].split('\nfunction ', 1)[0]
    stop = body('Stop-BackendService')
    assert '$owned.StopWithinDeadlineAsync($requestId, $null, $Deadline)' in stop and '$owned.LastStop' in stop
    assert 'ForcedExitConfirmed' in stop
    assert 'ReferenceEquals' in stop and '$script:OwnsMutex' in stop
    for forbidden in ('Stop-ProcessTree', 'Stop-BackendPortOwners', 'Stop-LegacyBackendService',
                      'RestartBlocker', 'VerifyReadiness', 'Get-OmiLifecycleSourceId', 'Start-Backend'):
        assert forbidden not in stop
    services = body('Stop-Services')
    assert services.index('Stop-BackendService') < services.index('Stop-FrontendService -RequireSafeStop')
    exit_body = body('Exit-Launcher')
    assert exit_body.index('Stop-Services') < exit_body.index('$script:LauncherExitReady = $true') < exit_body.index('::Exit()')
    assert '::Exit()' not in exit_body.split('finally {', 1)[1]
    cleanup = source.split('::add_ApplicationExit({', 1)[1]
    assert cleanup.index('if (-not $script:LauncherExitReady)') < cleanup.index('.Dispose()') < cleanup.index('.ReleaseMutex()')


def test_stop_authority_is_current_drain_not_disk_release_or_ready_snapshot():
    source = (ROOT / 'scripts/OmiOwnedShutdown.cs').read_text()
    stop = source.split('StopEvidence StopOnce(', 1)[1].split('public void Dispose()', 1)[0]
    for forbidden in ('ApplicationRelease', 'RestartBlocker', 'VerifyReadiness'):
        assert forbidden not in stop
    assert '!Alive' in stop and 'terminal = true' in stop
    assert 'PREFLIGHT_REARMED' in stop and 'terminal = false' in stop
    assert 'STOP_TIMEOUT' in stop and 'no_respawn' in stop
    assert stop.index('child.WaitForExit') < stop.index('evidence.ExactExit = true')
    assert stop.index('runner.WaitForExit') < stop.index('evidence.ExactExit = true')
    production = source.split('static int RunProduction(', 1)[1]
    assert production.index('prepare["action"] = "PREPARE"') < production.index('WRITERS_PREPARED') < production.index('Wire.Send(child.StandardInput, request)')
    assert production.index('LIFESPAN_COMPLETE') < production.index('child.WaitForExit(Wire.Remaining') < production.index('SUCCEEDED_PRODUCTION')


def test_manual_start_is_tray_only_and_keeps_existing_owner_and_queue_fence():
    launcher = (ROOT / 'scripts/omi-launcher.ps1').read_text(encoding='utf-8-sig')
    control = (ROOT / 'scripts/omi-runtime-control.ps1').read_text(encoding='utf-8-sig')
    start = launcher.split('function Start-OmiBackendAfterExactStop {', 1)[1].split('\nfunction ', 1)[0]
    start += launcher.split('function Start-OmiBackendSuccessor {', 1)[1].split('\nfunction ', 1)[0]
    assert start.count('New-OmiProductionOwnedBackend') == 1
    assert 'CanStartAfterStop' in start and 'DisposeAfterConfirmedStop' in start
    assert '-RequireObservation' in start
    assert launcher.count('Invoke-BackendStartRequest') == 3  # definition and two local menu items only
    for forbidden in ('Start-Process', 'Start-Services', 'Start-Frontend', 'Stop-Frontend', 'TakePending',
                      '$script:SafeStopAttempted = $false', '$script:OwnedBackendSession = $null'):
        assert forbidden not in start
    owner = control.split('function Assert-OmiManualBackendStartOwner {', 1)[1].split('\nfunction ', 1)[0]
    assert 'SelectedHost' in owner and 'SelectedPort' in owner and '8400' not in owner
    tick = control.split('function Invoke-OmiRuntimeControlTick {', 1)[1]
    assert tick.index('ServiceStopInProgress') < tick.index('TakePending')
    assert 'Test-OmiRemoteRestartGeneration' not in tick
    generation = control.split('function Test-OmiRemoteRestartGeneration {', 1)[1].split('\nfunction ', 1)[0]
    assert 'SafeStopAttempted' in generation and 'ReferenceEquals' in generation
