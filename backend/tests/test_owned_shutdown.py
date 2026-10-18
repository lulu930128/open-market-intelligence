"""Real disposable Launcher -> existing Runner -> shared Uvicorn transport."""
import json
from pathlib import Path
import subprocess
import time
import uuid

import pytest
from test_b4_lifespan import ChildHandle

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('scenario,fault', [
    ('normal', ''), ('normal', 'wrong-pid'), ('normal', 'wrong-created'),
    ('normal', 'wrong-nonce'), ('normal', 'expired'), ('normal', 'approval-missing'),
    ('normal', 'cancel'), ('normal', 'owner-absence'), ('normal', 'owner-crash'), ('active', ''), ('unknown', ''),
    ('stuck', ''), ('stuck-worker', ''), ('ack-alive', ''), ('runner-crash', ''),
    ('shutdown-error', ''), ('cancel-worker', ''), ('lifespan-alive', ''),
])
def test_owned_shutdown(scenario, fault):
    directory = ROOT / '.tmp/owned-shutdown' / (scenario + '-' + uuid.uuid4().hex)
    command = ['powershell.exe', '-NoProfile', '-File', str(ROOT / 'scripts/tests/test-owned-shutdown.ps1'),
               '-OutputRoot', str(directory), '-Scenario', scenario]
    if fault: command += ['-Fault', fault]
    launcher = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    handle = None
    runner_handle = None
    until = time.monotonic() + 20
    while launcher.poll() is None and time.monotonic() < until:
        public = directory / 'public-identity.json'
        if handle is None and public.exists():
            try:
                identity = json.loads(public.read_text(encoding='utf-8-sig'))
            except json.JSONDecodeError:
                time.sleep(.01)
                continue
            handle = ChildHandle(int(identity['child_pid']))
            runner_handle = ChildHandle(int(identity['runner_pid']))
        time.sleep(.005)
    stdout, stderr = launcher.communicate(timeout=20)  # Popen never kills on timeout
    proof = handle.wait() if handle else None
    runner_proof = runner_handle.wait() if runner_handle else None
    (directory / 'test-observation.json').write_text(json.dumps({
        'scope': 'DISPOSABLE_ONLY', 'launcher_exit': launcher.returncode,
        'child': proof, 'runner': runner_proof,
    }, indent=2), encoding='utf-8')
    assert launcher.returncode == (77 if fault == 'owner-crash' else 0), (stdout.decode(errors='replace'), stderr.decode(errors='replace'))
    assert proof and proof['retained_handle_signalled']
    assert runner_proof and runner_proof['retained_handle_signalled']
    assert proof['start'] == identity['child_created']
    if fault in {'owner-absence', 'owner-crash'}:
        assert not (directory / 'terminal-intent.json').exists()
        return
    record = json.loads((directory / 'launcher-receipt.json').read_text(encoding='utf-8-sig'))
    assert record['result'] == record['replay'], record
    result = record['result']
    if scenario == 'normal' and not fault:
        assert result['state'] == 'SUCCEEDED_DISPOSABLE', (result, stderr.decode(errors='replace'))
        assert result['exact_exit'] == 'true' and result['exit_code'] == '0'
        assert result['latched'] == 'true' and result['child_starts'] == '1'
        assert proof['exit_code'] == 0
    else:
        assert result['state'] != 'SUCCEEDED_DISPOSABLE', result
    latched = scenario in {'normal', 'stuck', 'ack-alive', 'runner-crash', 'shutdown-error', 'cancel-worker', 'lifespan-alive'} and not fault
    assert (directory / 'terminal-intent.json').exists() == latched
    if scenario != 'runner-crash':
        observation = json.loads((directory / 'exit-observation.json').read_text())
        assert observation['retained_handle_signalled'] == 'true'
        assert observation['child_pid'] == identity['child_pid']
        assert observation['child_created'] == identity['child_created']


def test_production_scope_cannot_use_fixture_or_boolean_authority():
    import base64
    import sys
    command = ['powershell.exe', '-NoProfile', '-File', str(ROOT / 'scripts/run-service-logged.ps1'),
               '-OwnedShutdownChannel', '-ServiceName', 'backend', '-RepoRoot', str(ROOT),
               '-WorkingDirectory', str(ROOT / 'backend'), '-FilePath', sys._base_executable,
               '-ArgumentsJsonBase64', base64.b64encode(b'[]').decode(), '-LauncherPid', str(__import__('os').getpid())]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = process.communicate(json.dumps({'scope': 'PRODUCTION', 'all_writers_drained': True,
        'approval': True, 'graceful': True}).encode() + b'\n', timeout=10)
    assert process.returncode == 79
    assert b'READY' not in out
    assert b'PRODUCTION_ADMISSION_AUTHORITY_UNAVAILABLE' in err


def test_actual_startup_failure_never_attests_ready_or_respawns():
    directory = ROOT / '.tmp/owned-shutdown' / uuid.uuid4().hex
    process = subprocess.Popen(['powershell.exe', '-NoProfile', '-File',
        str(ROOT / 'scripts/tests/test-owned-shutdown.ps1'), '-OutputRoot', str(directory),
        '-Scenario', 'startup-error'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child = runner = None
    until = time.monotonic() + 15
    while process.poll() is None and time.monotonic() < until:
        observed = directory / 'child-observation.json'
        if child is None and observed.exists():
            try:
                value = json.loads(observed.read_text())
            except json.JSONDecodeError:
                continue
            child = ChildHandle(int(value['child_pid']))
            runner = ChildHandle(int(value['runner_pid']))
        time.sleep(.005)
    stdout, stderr = process.communicate(timeout=15)
    assert process.returncode != 0
    assert child is not None and child.wait()['retained_handle_signalled']
    assert runner is not None and runner.wait()['retained_handle_signalled']
    assert not (directory / 'public-identity.json').exists()
    assert not (directory / 'terminal-intent.json').exists()
    assert b'SUCCEEDED' not in stdout


def test_production_restart_keeps_restart_only_gates_before_shared_stop():
    control = (ROOT / 'scripts/omi-runtime-control.ps1').read_text(encoding='utf-8-sig')
    bridge = control.split('function Restart-Backend {', 1)[1].split('\nfunction ', 1)[0]
    assert 'Invoke-OwnedBackendRestart -RequestId $RequestId -RemoteRequest' in bridge
    owner = control.split('function Assert-OmiManualBackendStartOwner {', 1)[1].split('\nfunction ', 1)[0]
    assert 'Get-OmiLifecycleSourceId' in owner

    launcher = (ROOT / 'scripts/omi-launcher.ps1').read_text(encoding='utf-8-sig')
    body = launcher.split('function Invoke-OwnedBackendRestart {', 1)[1].split('\nfunction ', 1)[0]
    stop = body.index('$old.StopAsync($RequestId)')
    for gate in ('Assert-OmiManualBackendStartOwner', 'RestartBlocker', 'VerifyReadiness',
                 'BeginAuthenticatedOwnedRestart'):
        assert body.index(gate) < stop
    for forbidden in ('HumanApprovalIssuer', 'StopDisposable', 'Stop-ProcessTree',
                      'Stop-BackendService ', 'Start-Backend '):
        assert forbidden not in body

def test_transport_terminal_order_and_no_force():
    source = (ROOT / 'scripts/OmiOwnedShutdown.cs').read_text()
    assert source.index('latched = true;') < source.index('Persist(root, "terminal-intent.json"') < source.index('Wire.Send(child.StandardInput, request)')
    for forbidden in ('taskkill', '.Kill(', 'Stop-Process', 'cmd.exe /'):
        assert forbidden not in source
    assert 'child.WaitForExit' in source and 'var retained = child.Handle' in source
    assert 'retained = Process.Start(info); var handle = retained.Handle' in source
    production = source.split('ProductionSession(string repository', 1)[1].split('bool ConfirmStartupExit', 1)[0]
    assert production.index('try {') < production.index('out runner') < production.index('Wire.Send(runner.StandardInput')
