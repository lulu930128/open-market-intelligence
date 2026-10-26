"""Native Windows B4 handshake; failures are failures, never skips/xfails."""
import base64
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.tmp/us-r1-b4-disposable-20261011'


class ChildHandle:
    """Observation only; no PROCESS_TERMINATE authority requested."""
    def __init__(self, pid):
        self.kernel = k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = k.OpenProcess(0x100000 | 0x1000, False, pid)
        assert self.handle, 'child handle unavailable; no inferred exit'
        self.pid = pid
        values = [wintypes.FILETIME() for _ in range(4)]
        assert k.GetProcessTimes(self.handle, *[ctypes.byref(v) for v in values])
        self.start = str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)

    def wait(self):
        try:
            assert self.kernel.WaitForSingleObject(self.handle, 12000) == 0, 'ORPHAN: no force cleanup'
            code = wintypes.DWORD()
            assert self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code))
            return dict(pid=self.pid, start=self.start, exit_code=code.value,
                        retained_handle_signalled=True, observed_monotonic=time.monotonic())
        finally:
            self.kernel.CloseHandle(self.handle)


def command(directory, scenario, *, service='r1-b4-disposable', argv=b'[]'):
    return ['powershell.exe', '-NoProfile', '-File', str(ROOT/'scripts/run-service-logged.ps1'),
        '-ServiceName', service, '-RepoRoot', str(directory), '-WorkingDirectory', str(directory),
        '-FilePath', getattr(sys, '_base_executable', sys.executable),
        '-ArgumentsJsonBase64', base64.b64encode(argv).decode(), '-UvicornLifespanFixture',
        '-LifespanScenario', scenario]


def execute(directory, scenario, **kwargs):
    assert sys.platform == 'win32', 'Native Windows proof required'
    args = command(directory, scenario, **kwargs)
    # Popen timeout never kills. Retain both runner Popen and exact child handle.
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    handle = None
    until = time.monotonic() + 15
    while process.poll() is None and time.monotonic() < until:
        if handle is None and (directory/'ready.json').exists():
            ready = json.loads((directory/'ready.json').read_text())
            handle = ChildHandle(ready['child_pid'])
        time.sleep(.002)
    stdout, stderr = process.communicate(timeout=15)
    exit_proof = handle.wait() if handle else None
    record = dict(argv=args, runner_pid=process.pid, runner_exit=process.returncode,
                  child_exit=exit_proof, stdout=stdout.decode(errors='replace'),
                  stderr=stderr.decode(errors='replace'))
    (OUT/(directory.name+'-execution.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
    return record


SCENARIOS = ['normal','double-signal','wrong-pid','wrong-start','wrong-instance','wrong-deadline',
    'wrong-request','wrong-runner','missing-ack','timeout','child-crash','runner-crash',
    'parent-disappearance','partial-drain','stuck-worker','cancel-worker','unknown-session',
    'borrowed-escape','fake-ack','ack-without-exit','source-drift','ready-wrong-start',
    'request-wrong-pid','request-wrong-start','request-wrong-token','request-expired',
    'request-wrong-runner','orphan','ack-session-type','ack-publisher-type','ack-unknown-type',
    'ack-pending-constructor','ack-close-failure','ack-uncertain-owner','ack-unknown-publisher',
    'ack-incomplete-jobs','ack-global-drained','ack-null-owners','ack-unknown-scheduler','ack-active-collector']


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_lifespan_handshake(scenario):
    directory = OUT / (scenario+'-'+uuid.uuid4().hex)
    execution = execute(directory, scenario)
    assert execution['child_exit'], execution['stderr'] or json.dumps(execution)
    assert execution['child_exit']['retained_handle_signalled']
    proof = execution['child_exit']
    if scenario in {'runner-crash','parent-disappearance'}:
        assert execution['runner_exit'] == 77, execution
        assert not (directory/'ack.json').exists()
        assert not (directory/'request.json').exists()
        assert not (directory/'verdict.json').exists()
        assert proof['exit_code'] == 72
    else:
        verdict = json.loads((directory/'verdict.json').read_text())
        positive = scenario in {'normal','double-signal'}
        assert execution['runner_exit'] == (0 if positive else 79), (verdict,execution)
        assert verdict['verdict'] == ('PASS_FIXTURE_ONLY' if positive else 'BLOCKED'), verdict
        assert verdict['formal_R1'] == 'BLOCKED' and not verdict['force_fallback']
        assert verdict['respawn_inhibited'] and verdict['child_starts'] == 1
        if scenario.startswith('wrong-'):
            assert verdict['reason'] == 'ACK_IDENTITY_MISMATCH'
        elif scenario.startswith('request-'):
            assert verdict['reason'] == 'UNCLEAN_EXIT'
            assert proof['exit_code'] == 72 and not (directory/'ack.json').exists()
        elif scenario in {'timeout','stuck-worker','ack-without-exit','orphan'}:
            assert verdict['reason'] == 'DEADLINE_EXCEEDED'
        elif scenario.startswith('ack-'):
            assert verdict['reason'] == 'INCOMPLETE_LIFESPAN_OR_OWNER_DRAIN'
            assert verdict['exact_exit'] and proof['exit_code'] == 0
        elif scenario in {'partial-drain','cancel-worker','unknown-session','borrowed-escape','fake-ack'}:
            assert verdict['reason'] == 'INCOMPLETE_LIFESPAN_OR_OWNER_DRAIN'
        elif scenario == 'source-drift':
            assert verdict['reason'] == 'UNCLEAN_EXIT' and proof['exit_code'] == 72
            observation=json.loads((directory/'child-observation.json').read_text())
            assert observation['state']['reason'] == 'SOURCE_DRIFT'
            assert observation['source_hashes'] != observation['snapshot_hashes_after']
            assert not (directory/'ack.json').exists()
        elif scenario == 'missing-ack':
            assert verdict['reason'] == 'MISSING_ACK'
        elif scenario == 'child-crash':
            assert verdict['reason'] == 'UNCLEAN_EXIT' and proof['exit_code'] == 75
        elif scenario == 'ready-wrong-start':
            assert verdict['reason'] == 'Child OS identity mismatch'
            assert not (directory/'request.json').exists()
        assert proof['pid'] == verdict['launched_identity']['child_pid']
        assert proof['start'] == verdict['launched_identity']['child_start']
        if positive:
            ack = verdict['ack']
            assert verdict['exact_exit'] and verdict['exit_code'] == proof['exit_code'] == 0
            assert ack['lifespan_complete'] and ack['server_returned'] and ack['workers_exited']
            assert 'Proactor' in ack['event_loop'] and ack['listener_count'] == 0
            assert ack['drain']['state'] == 'REGISTERED_DRAINED'
            assert not ack['drain']['all_writers_drained'] and ack['drain']['unknown_writers']
            events = [item['event'] for item in ack['timeline']]
            assert events.index('admission_fenced') < events.index('runtime_drain_receipt')
            assert events.index('runtime_drain_receipt') < events.index('lifespan_shutdown_complete')
            assert events.index('lifespan_shutdown_complete') < events.index('uvicorn_serve_returned')
        if scenario in {'cancel-worker','borrowed-escape'}:
            observation=json.loads((directory/'child-observation.json').read_text())
            assert observation['state']['worker_after_finalizer']
        if scenario == 'cancel-worker':
            assert observation['state']['receipt']['sessions']['state'] == 'unknown'
        if scenario == 'orphan':
            assert verdict['orphan_exit_observed'] and proof['exit_code'] == 72
            assert json.loads((directory/'child-observation.json').read_text())['state']['reason'] == 'ORPHAN_LEASE_EXPIRED'
        # Frozen failure never upgraded by late receipt/worker completion/exit.
        assert json.loads((directory/'verdict.json').read_text()) == verdict
    files = sorted(p.name for p in directory.iterdir())
    retry = subprocess.Popen(command(directory, 'normal'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout,stderr=retry.communicate(timeout=10)
    assert retry.returncode == 79 and b'recovery/rearm refused' in stdout+stderr
    assert sorted(p.name for p in directory.iterdir()) == files


@pytest.mark.parametrize('kwargs', [dict(service='backend'), dict(argv=b'["app.main:app"]')])
def test_invalid_invocation_cannot_start_child(kwargs):
    directory = OUT / ('rejected-'+uuid.uuid4().hex)
    result=execute(directory,'normal',**kwargs)
    assert result['runner_exit'] == 79 and result['child_exit'] is None
    assert not directory.exists()
