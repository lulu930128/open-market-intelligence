"""Real finite Windows fixtures. No app import, server, DB or force cleanup."""
import base64
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'scripts/run-service-logged.ps1'
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows proof required; not a portable PASS')


def command(directory, scenario, *, service='r1e-fixture', opt_in=True):
    # Use the actual base interpreter, not a venv redirector with another PID.
    python = getattr(sys, '_base_executable', sys.executable)
    args = ['powershell.exe', '-NoProfile', '-File', str(RUNNER), '-ServiceName', service,
            '-RepoRoot', str(directory), '-WorkingDirectory', str(directory), '-FilePath', python,
            '-ArgumentsJsonBase64', base64.b64encode(b'[]').decode(), '-FixtureScenario', scenario]
    if opt_in:
        args.append('-GracefulStopFixture')
    return args


def execute(args):
    # Render ErrorRecord messages directly: the console formatter truncates
    # long runner paths/messages differently on GitHub's Windows host.
    if '-File' in args:
        offset = args.index('-File')
        invocation = ' '.join(value if value.startswith('-') else
                              "'" + value.replace("'", "''") + "'" for value in args[offset + 1:])
        script = '& ' + invocation + ' 2>&1 | ForEach-Object { $_.ToString() }; exit $LASTEXITCODE'
        args = args[:offset] + ['-EncodedCommand', base64.b64encode(script.encode('utf-16-le')).decode()]
    # communicate(timeout) on Popen never terminates a child. No run(timeout),
    # context-manager cleanup, terminate(), taskkill or kill() fallback.
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=15)
    return process.returncode, stdout.decode(errors='replace') + stderr.decode(errors='replace')


def await_finite_child(directory, identity=None):
    """Retain a Windows handle for a still-running negative-case fixture only."""
    ready = identity or json.loads((directory / 'ready.json').read_text(encoding='utf-8'))
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, ready['child_pid'])
    assert handle, 'Cannot attest disposable negative-case child exit'
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        assert kernel.GetProcessTimes(handle, *[ctypes.byref(v) for v in values])
        start = str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
        assert start == ready['child_start'], 'PID reused; do not touch replacement'
        assert kernel.WaitForSingleObject(handle, 9000) == 0, 'Finite child did not exit; no force fallback'
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.parametrize('scenario,reason', [
    ('normal', 'IDENTITY_ACK_DRAIN_EXACT_EXIT'),
    ('double-signal', 'IDENTITY_ACK_DRAIN_EXACT_EXIT'),
    ('wrong-pid', 'ACK_IDENTITY_MISMATCH'),
    ('wrong-start', 'ACK_IDENTITY_MISMATCH'),
    ('wrong-instance', 'ACK_IDENTITY_MISMATCH'),
    ('wrong-deadline', 'ACK_IDENTITY_MISMATCH'),
    ('missing-ack', 'MISSING_ACK'),
    ('timeout', 'DEADLINE_EXCEEDED'),
    ('child-crash', 'UNCLEAN_EXIT'),
    ('incomplete-drain', 'DEADLINE_EXCEEDED'),
    ('ack-without-exit', 'DEADLINE_EXCEEDED'),
    ('invalid-drain-receipt', 'INCOMPLETE_OR_FORCED_DRAIN'),
    ('forced-receipt', 'INCOMPLETE_OR_FORCED_DRAIN'),
])
def test_real_windows_handshake(scenario, reason):
    directory = ROOT / '.tmp' / ('r1e-test-' + uuid.uuid4().hex)
    code, output = execute(command(directory, scenario))
    assert (directory / 'verdict.json').exists(), output
    verdict = json.loads((directory / 'verdict.json').read_text(encoding='utf-8'))
    assert verdict['reason'] == reason, verdict
    success = scenario in {'normal', 'double-signal'}
    assert code == (0 if success else 79), output
    assert verdict['verdict'] == ('PASS_FIXTURE_ONLY' if success else 'BLOCKED')
    assert verdict['formal_R1'] == 'BLOCKED'
    assert verdict['child_starts'] == 1 and verdict['respawn_inhibited']
    assert verdict['stop_intent_latched'] and not verdict['force_fallback']
    intent = directory / 'stop-intent.json'
    request = directory / 'request.json'
    assert intent.stat().st_mtime_ns <= request.stat().st_mtime_ns
    assert json.loads(intent.read_text()) == json.loads(request.read_text())
    if success:
        assert verdict['exact_exit'] and verdict['exit_code'] == 0
        assert verdict['ack']['drain']['accepted'] == verdict['ack']['drain']['completed'] == 1
    if scenario == 'double-signal':
        assert verdict['ack']['duplicate_observed']
        assert verdict['ack']['drain']['stop_count'] == 1
    if scenario in {'timeout', 'incomplete-drain', 'ack-without-exit'}:
        await_finite_child(directory)
        # A late ACK cannot upgrade the terminal verdict or trigger respawn.
        assert json.loads((directory / 'verdict.json').read_text()) == verdict
        if scenario == 'incomplete-drain':
            ack = json.loads((directory / 'ack.json').read_text())
            assert not ack['drain']['worker_joined'] and ack['drain']['completed'] == 0
    before = sorted(p.name for p in directory.iterdir())
    code, output = execute(command(directory, scenario))
    assert code == 79 and 'recovery/rearm refused' in output
    assert sorted(p.name for p in directory.iterdir()) == before


def test_runner_disappearance_latches_and_never_signals_or_rearms():
    directory = ROOT / '.tmp' / ('r1e-crash-' + uuid.uuid4().hex)
    code, output = execute(command(directory, 'runner-crash'))
    assert code == 77, output
    assert (directory / 'stop-intent.json').exists()
    assert not (directory / 'request.json').exists()
    assert not (directory / 'ack.json').exists()
    assert not (directory / 'verdict.json').exists()  # abrupt loss bypasses finally
    await_finite_child(directory)
    code, output = execute(command(directory, 'normal'))
    assert code == 79 and 'recovery/rearm refused' in output
    assert not (directory / 'request.json').exists()


def test_unknown_child_creation_time_refuses_signal():
    directory = ROOT / '.tmp' / ('r1e-unknown-' + uuid.uuid4().hex)
    code, output = execute(command(directory, 'ready-wrong-start'))
    assert code == 79, output
    verdict = json.loads((directory / 'verdict.json').read_text())
    assert verdict['reason'] == 'Child OS identity mismatch'
    assert not verdict['stop_intent_latched'] and not (directory / 'request.json').exists()
    # Observe the runner's OS identity, never the deliberately false ready claim.
    await_finite_child(directory, verdict['launched_identity'])
    assert not (directory / 'ack.json').exists()


def test_production_service_name_refused_before_any_start():
    directory = ROOT / '.tmp' / ('r1e-rejected-' + uuid.uuid4().hex)
    code, output = execute(command(directory, 'normal', service='backend'))
    assert code == 79 and 'Disposable fixture identity required' in output
    assert not directory.exists()


def test_ipc_outside_disposable_root_refused():
    directory = ROOT / ('r1e-rejected-' + uuid.uuid4().hex)
    code, output = execute(command(directory, 'normal'))
    assert code == 79 and 'Fresh disposable directory' in output
    assert not directory.exists()


def test_unprotected_acl_rejected_without_changing_it(tmp_path):
    helper = str(ROOT / 'scripts/omi-graceful-stop-fixture.ps1').replace("'", "''")
    path = str(tmp_path).replace("'", "''")
    script = tmp_path / 'acl-check.ps1'
    script.write_text(f"""
$ErrorActionPreference='Stop'
. '{helper}'
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$before=(Get-Item -LiteralPath '{path}').GetAccessControl().GetSecurityDescriptorSddlForm('All')
try {{ $null=Assert-OmiPrivateDirectory '{path}' $sid; exit 1 }} catch {{}}
$after=(Get-Item -LiteralPath '{path}').GetAccessControl().GetSecurityDescriptorSddlForm('All')
if ($before -cne $after) {{ exit 2 }}
exit 0
""", encoding='utf-8-sig')
    code, output = execute(['powershell.exe', '-NoProfile', '-File', str(script)])
    assert code == 0, output
