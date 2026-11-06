"""Real Windows Launcher component -> both production venv redirectors -> Fake SDK.

All state/Journal and pipe names are temporary. No production Launcher invocation.
"""
import json
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from execution_runtime import control
from execution_runtime.launch import optional_receipt
from execution_runtime.storage import OwnerLease

ROOT = Path(__file__).resolve().parents[2]
SHELL = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def pipe_request(name, message):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.WriteFile.argtypes = [W.HANDLE, W.LPVOID, W.DWORD, ctypes.POINTER(W.DWORD), W.LPVOID]
    kernel.ReadFile.argtypes = [W.HANDLE, W.LPVOID, W.DWORD, ctypes.POINTER(W.DWORD), W.LPVOID]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    deadline = time.monotonic() + 2
    while True:
        handle = kernel.CreateFileW('\\\\.\\pipe\\' + name, 0xc0000000, 0, None, 3, 0, None)
        if handle != W.HANDLE(-1).value:
            break
        error = ctypes.get_last_error()
        if error not in {2, 231} or time.monotonic() >= deadline:
            raise ctypes.WinError(error)
        time.sleep(.01)  # Same normal pipe-instance gap handled by .NET Connect.
    try:
        payload = json.dumps(message).encode() + b'\n'
        count = W.DWORD()
        if not kernel.WriteFile(handle, payload, len(payload), ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        output = bytearray()
        while not output.endswith(b'\n'):
            buffer = ctypes.create_string_buffer(16384)
            if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None) or not count.value:
                raise ctypes.WinError(ctypes.get_last_error())
            output.extend(buffer.raw[:count.value])
            assert len(output) < 16384
        return json.loads(output)
    finally:
        kernel.CloseHandle(handle)


def eventually(callback, timeout=15):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = callback()
        if latest:
            return latest
        time.sleep(.1)
    raise AssertionError('fixture deadline: ' + str(latest))


@unittest.skipUnless(os.name == 'nt', 'Windows processes and authenticated pipes')
class DeploymentOwnerTests(unittest.TestCase):
    def owner(self, root, scenario='normal'):
        name = 'omi-execution-deployment-' + uuid4().hex
        (root / 'SYNTHETIC_ONLY').touch()
        process = subprocess.Popen([SHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'scripts/tests/execution-owner-fixture.ps1'), '-FixtureRoot', str(root),
            '-PipeName', name, '-Scenario', scenario], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        header = process.stdout.readline()
        if not header.startswith('{'):
            error = process.stderr.read()
            process.wait(timeout=10)
            process.stdin.close(); process.stdout.close(); process.stderr.close()
            raise AssertionError(header + error)
        owner = json.loads(header)
        return process, owner

    def request(self, owner, action, request_id=None):
        return pipe_request(owner['pipe'], {'action': 'Execution' + action, 'request_id': request_id or str(uuid4()),
            'expected_owner_id': owner['owner_id'], 'token': ''})

    def close(self, process):
        if process.poll() is None:
            process.stdin.write('exit\n'); process.stdin.flush()
            response = process.stdout.readline()
            self.assertTrue(json.loads(response)['exit_ready'], response)
        process.wait(timeout=15)
        if not process.stderr.closed:
            error = process.stderr.read()
            process.stdin.close(); process.stdout.close(); process.stderr.close()
            self.assertEqual(process.returncode, 0, error)

    def running(self, owner):
        value = self.request(owner, 'Status')
        return value if value['state'] == 'RUNNING' else None

    def test_client_exit_idempotent_stop_persist_restart_and_normal_owner_exit(self):
        with TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            root = Path(directory)
            process, owner = self.owner(root)
            try:
                request_id = str(uuid4())
                message = {'action': 'ExecutionStart', 'request_id': request_id,
                           'expected_owner_id': owner['owner_id'], 'token': ''}
                # A distinct, short command exits. It creates no server/child tree.
                code = 'from execution_runtime.tests.test_deployment_owner import pipe_request; import json; print(json.dumps(pipe_request(' + repr(owner['pipe']) + ',' + repr(message) + ')))'
                client = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(client.returncode, 0, client.stderr)
                first = eventually(lambda: self.running(owner))
                self.assertTrue(first['lineage_attested'])
                # Both local production venvs redirect; actual Python != spawn.
                self.assertNotEqual(first['spawn_pid'], first['supervisor_pid'])
                receipt = optional_receipt(root / 'state' / ('startup-' + first['startup_id'] + '.json'))
                self.assertNotEqual(receipt['child_launcher_pid'], first['native_pid'])
                time.sleep(1.2)
                again = self.request(owner, 'Start')
                self.assertEqual(again['startup_id'], first['startup_id'])
                self.assertEqual((root / 'state/fake-logins.txt').read_text().count('synthetic'), 1)
                process.stdin.write('research-cycle\n'); process.stdin.flush()
                self.assertEqual(process.stdout.readline().strip(), 'RESEARCH_PUBLICATION_COMPLETE')
                self.assertEqual(self.running(owner)['startup_id'], first['startup_id'])
                # A stale READY cannot defeat retained process identity/freshness.
                path = root / 'state' / ('startup-' + first['startup_id'] + '.json')
                original = optional_receipt(path)
                def rejected_receipt(field, value):
                    altered = {**original, field: value}
                    temporary = path.with_suffix('.test.tmp')
                    temporary.write_text(json.dumps(altered), encoding='utf-8')
                    os.replace(temporary, path)
                    return self.request(owner, 'Status')['state'] == 'UNKNOWN'
                eventually(lambda: rejected_receipt('observed_at', '2000-01-01T00:00:00+00:00'))
                eventually(lambda: rejected_receipt('owner_pid', owner['pid'] + 1))
                # Restore only the fixture receipt, then wait for owner's heartbeat.
                eventually(lambda: self.running(owner))
                wrong = pipe_request(owner['pipe'], {**message, 'action': 'ExecutionStatus', 'expected_owner_id': str(uuid4())})
                self.assertEqual(wrong['reason'], 'OWNER_MISMATCH')
                self.assertFalse(self.request(owner, 'PrepareUpdate')['update_prepared'])
                stopped = self.request(owner, 'Stop')
                self.assertFalse(stopped['keep_online'])
                self.assertIn(self.request(owner, 'Start')['reason'], {'EXECUTION_STOP_IN_PROGRESS', 'EXECUTION_OWNER_UNVERIFIED'})
                eventually(lambda: self.request(owner, 'Status')['state'] == 'STOPPED')
                replay = self.request(owner, 'Start', request_id)
                self.assertEqual(replay['state'], 'STOPPED')
                # Test evidence contains only synthetic process/config facts.
                output = os.environ.get('OMI_DEPLOYMENT_EVIDENCE')
                if output:
                    Path(output).write_text(json.dumps({'scenario':'synthetic_only','client_exit_code':client.returncode,
                        'running':first,'supervisor_receipt':receipt,'stop':self.request(owner,'Status'),
                        'fake_logins_before_restart':1},indent=2),encoding='utf-8')
                self.close(process)
                # Manual OFFLINE survives Launcher restart, no new login.
                process, owner = self.owner(root)
                self.assertEqual(self.request(owner, 'Status')['state'], 'STOPPED')
                self.assertEqual((root / 'state/fake-logins.txt').read_text().count('synthetic'), 1)
                self.request(owner, 'Start')
                eventually(lambda: self.running(owner))
                self.close(process)  # Exit preserves keep_online and proves child exit.
                self.assertTrue(json.loads((root / 'controller/settings/execution-preference.json').read_text())['keep_online'])
                process, owner = self.owner(root)
                eventually(lambda: self.running(owner))  # Normal startup adopts intent once.
                self.assertEqual((root / 'state/fake-logins.txt').read_text().count('synthetic'), 3)
                self.request(owner, 'Stop')
                eventually(lambda: self.request(owner, 'Status')['state'] == 'STOPPED')
                update = self.request(owner, 'PrepareUpdate')
                self.assertTrue(update['update_prepared'])
                self.assertEqual(self.request(owner, 'Start')['reason'], 'EXECUTION_OWNER_CLOSING')
                print('RECEIPT client_exit_survival both_redirectors idempotent_start durable_offline startup_adoption normal_exit update_fence PASS')
            except BaseException:
                # Keep only synthetic owner/receipt diagnostics before cleanup
                # changes desired state or removes the temporary fixture.
                print('FIXTURE_FAILURE ' + json.dumps({
                    'status': self.request(owner, 'Status'),
                    'receipts': [optional_receipt(path) for path in (root / 'state').glob('startup-*.json')],
                    'errors': {path.name: path.read_text(encoding='utf-8') for path in (root / 'state').glob('fixture-error-*.txt')},
                }))
                raise
            finally:
                self.close(process)

    def test_backoff_stop_and_owner_loss_do_not_respawn(self):
        for scenario in ('backoff', 'normal'):
            with self.subTest(scenario=scenario), TemporaryDirectory(dir=ROOT / '.tmp') as directory:
                root = Path(directory)
                process, owner = self.owner(root, scenario)
                try:
                    self.request(owner, 'Start')
                    if scenario == 'backoff':
                        eventually(lambda: self.request(owner, 'Status')['state'] == 'RECOVERING')
                        self.request(owner, 'Stop')
                        eventually(lambda: self.request(owner, 'Status')['state'] == 'STOPPED')
                        time.sleep(1)
                        self.assertEqual((root / 'state/fake-logins.txt').read_text().count('synthetic'), 1)
                    else:
                        first = eventually(lambda: self.running(owner))
                        process.stdin.write('owner-loss\n'); process.stdin.flush()
                        process.wait(timeout=10)
                        path = root / 'state' / ('startup-' + first['startup_id'] + '.json')
                        eventually(lambda: (optional_receipt(path) or {}).get('status') == 'STOPPED')
                        for name in ('native-session', 'launch-supervisor'):
                            lease = OwnerLease(root / 'state' / name)
                            eventually(lambda: self.lease_free(lease))
                        self.assertEqual((root / 'state/fake-logins.txt').read_text().count('synthetic'), 1)
                finally:
                    self.close(process)

    @staticmethod
    def lease_free(lease):
        try:
            lease.acquire(); lease.release(); return True
        except RuntimeError:
            return False

    def test_bad_preference_can_exit_and_missing_interpreter_has_fixed_error(self):
        for scenario in ('bad-preference', 'missing'):
            with self.subTest(scenario=scenario), TemporaryDirectory(dir=ROOT / '.tmp') as directory:
                process, owner = self.owner(Path(directory), scenario)
                try:
                    response = self.request(owner, 'Start')
                    self.assertEqual(response['reason'], 'EXECUTION_OWNER_UNAVAILABLE' if scenario == 'bad-preference' else 'EXECUTION_INTERPRETER_MISSING')
                    self.assertEqual(response['operation_outcome'], 'NOT_STARTED')
                finally:
                    self.close(process)


if __name__ == '__main__':
    unittest.main()
