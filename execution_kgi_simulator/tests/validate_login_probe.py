"""Independent offline login-only profile; does not alter legacy ContractTest.

All inputs are invented. No Settings instantiation or credential lookup occurs.
"""

import ast
from dataclasses import FrozenInstanceError
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import unittest
from unittest.mock import patch

from execution_kgi_simulator.login_probe import (
    Credentials, CredentialOwnerReference, Outcome, Phase, Reason,
    credential_owner_reference, encode_private_frame, exercise_fixture, read_private_frame,
)
from execution_kgi_simulator.tests.login_fixture_worker import FakeSDK, FakeLoginPort

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / 'execution_kgi_simulator/tests/login_fixture_worker.py'


def run_child(scenario, *, raw=None, cancel=False):
    """Test-only supervisor. Fixed source child, invented Settings-shaped input.

    Popen handle is the only termination authority; no caller PID/executable.
    communicate provides bounded pipe transfer/wait. No capture is written out.
    """
    generation = secrets.token_hex(16)
    credentials = Credentials('INVENTED_PERSON', 'INVENTED_SECRET')
    payload = encode_private_frame(credentials, generation) if raw is None else raw
    credentials.clear()
    child = subprocess.Popen([sys.executable, '-I', '-S', '-B', str(WORKER), scenario, generation],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={'SystemRoot': os.environ.get('SystemRoot', '')},
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    killed = False
    try:
        if cancel:
            child.kill()
            killed = True
        try:
            stdout, stderr = child.communicate(payload, timeout=.6 if 'hang' in scenario else 5)
        except subprocess.TimeoutExpired:
            # May have crossed login. Never claim rejection, logout or no effect.
            child.kill()
            killed = True
            stdout, stderr = child.communicate(timeout=3)
        if killed:
            return {'status': 'UNKNOWN', 'reasonCodes': ['OWNED_CANCEL' if cancel else 'OWNED_TIMEOUT'],
                    'owned_pid': child.pid, 'stopped': child.poll() is not None,
                    'logout_confirmed': False, 'receipt': None, 'stdout_bytes': len(stdout),
                    'stderr_bytes': len(stderr)}
        if child.returncode != 0 or stderr or len(stdout) > 8192:
            raise AssertionError('FIXTURE_CONTROL_CHANNEL_INVALID')
        report = json.loads(stdout)
        if report.get('generation', generation) != generation:
            raise AssertionError('FIXTURE_SESSION_FENCED')
        return report
    finally:
        payload = b''
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


class LoginOnlyLifecycle(unittest.TestCase):
    def run_port(self, scenario, **kwargs):
        generation = secrets.token_hex(16)
        sdk = FakeSDK(scenario, generation)
        credentials = Credentials('INVENTED_PERSON', 'INVENTED_SECRET')
        result = exercise_fixture(FakeLoginPort(sdk), credentials, generation=generation,
                                  test_preflight=True, **kwargs)
        self.assertEqual(credentials.person_id, '')
        self.assertEqual(credentials.password, '')
        self.assertEqual(result.phases[-1], Phase.CLOSED)
        self.assertEqual(sdk.order_accesses, 0)
        return result, sdk

    def test_positive_login_readback_logout_has_only_fixture_receipt(self):
        result, sdk = self.run_port('accept')
        self.assertEqual(result.outcome, Outcome.ACCEPTED)
        self.assertEqual(result.phases, tuple(Phase))
        self.assertTrue(result.logout_confirmed)
        self.assertEqual((sdk.logins, sdk.readbacks, sdk.logouts), (1, 1, 1))
        self.assertEqual(result.receipt.origin, 'LOCAL_MOCK')
        self.assertEqual(result.public()['runtime_origin'], 'NOT_CONNECTED')
        self.assertNotIn('INVENTED', json.dumps(result.public()))

    def test_preflight_blocked_still_closed_and_secret_released(self):
        generation = secrets.token_hex(16)
        sdk = FakeSDK('accept', generation)
        for denied in (False, None, 'true', 1, {'verified': True}):
            credentials = Credentials('INVENTED_PERSON', 'INVENTED_SECRET')
            result = exercise_fixture(FakeLoginPort(sdk), credentials,
                generation=generation, test_preflight=denied)
            self.assertEqual(result.outcome, Outcome.BLOCKED)
            self.assertEqual(result.phases, (Phase.PREFLIGHT, Phase.CLOSED))
            self.assertEqual(credentials.password, '')
        self.assertEqual((sdk.logins, sdk.readbacks, sdk.logouts), (0, 0, 0))

    def test_external_port_cannot_unlock_io_even_with_true_test_flag(self):
        class Trap:
            def login(self, *args, **kwargs):
                raise AssertionError('EXTERNAL_PORT_MUST_NOT_RUN')
        credentials = Credentials('INVENTED_PERSON', 'INVENTED_SECRET')
        result = exercise_fixture(Trap(), credentials, generation=secrets.token_hex(16),
                                  test_preflight=True)
        self.assertEqual((result.outcome, result.reason), (Outcome.BLOCKED, Reason.PORT))
        self.assertEqual(result.phases, (Phase.PREFLIGHT, Phase.CLOSED))
        self.assertEqual(credentials.password, '')

    def test_rejected_unknown_null_and_native_failure_are_distinct(self):
        for scenario, outcome, reason in (
            ('reject', Outcome.REJECTED, Reason.REJECTED),
            ('unknown', Outcome.UNKNOWN, Reason.MALFORMED),
            ('null', Outcome.UNKNOWN, Reason.MALFORMED),
            ('error', Outcome.UNKNOWN, Reason.FAILURE),
            ('timeout', Outcome.UNKNOWN, Reason.TIMEOUT)):
            with self.subTest(scenario=scenario):
                result, sdk = self.run_port(scenario)
                self.assertEqual((result.outcome, result.reason), (outcome, reason))
                self.assertIsNone(result.receipt)
                self.assertEqual(sdk.logouts, 1)

    def test_target_generation_and_identity_fences(self):
        for scenario, reason in (('wrong_target', Reason.TARGET), ('stale', Reason.FENCED),
                                 ('mismatch', Reason.MALFORMED), ('wrong_person', Reason.MALFORMED)):
            with self.subTest(scenario=scenario):
                result, _ = self.run_port(scenario)
                self.assertEqual(result.reason, reason)
                self.assertIsNone(result.receipt)

    def test_logout_failure_cannot_return_success_receipt(self):
        for scenario in ('logout_error', 'logout_false'):
            result, _ = self.run_port(scenario)
            self.assertEqual((result.outcome, result.reason), (Outcome.UNKNOWN, Reason.LOGOUT))
            self.assertFalse(result.logout_confirmed)
            self.assertIsNone(result.receipt)

    def test_late_return_and_cancel_are_unknown_with_teardown(self):
        result, sdk = self.run_port('late', timeout_seconds=.04)
        self.assertEqual(result.reason, Reason.TIMEOUT)
        self.assertEqual(sdk.logouts, 1)
        report = run_child('cancel')
        self.assertEqual(report['reasonCodes'], ['LOGIN_ONLY_CANCELLED'])
        self.assertEqual(report['fixture_calls']['logout'], 1)

    def test_stray_callback_and_order_methods_never_become_authority(self):
        result, sdk = self.run_port('callback')
        self.assertEqual(result.outcome, Outcome.ACCEPTED)
        self.assertEqual(sdk.order_accesses, 0)
        port = FakeLoginPort(sdk)
        for name in ('create_order', 'cancel_order', 'Order', 'set_Account', '_API', 'callback'):
            self.assertFalse(hasattr(port, name))
        with self.assertRaises(ValueError):
            FakeLoginPort(object())

    def test_receipt_identity_is_randomized_and_no_raw_identity_escapes(self):
        first, _ = self.run_port('accept')
        second, _ = self.run_port('accept')
        self.assertNotEqual(first.receipt.identity_digest, second.receipt.identity_digest)
        self.assertNotEqual(first.receipt.receipt_id, second.receipt.receipt_id)
        self.assertNotIn('INVENTED', repr(first))

    def test_deadline_invalid_inputs_never_call_sdk(self):
        for timeout in (True, 0, -1, float('nan'), float('inf'), 11, '2'):
            with self.assertRaises(ValueError):
                self.run_port('accept', timeout_seconds=timeout)


class SecureHandoff(unittest.TestCase):
    def test_login_only_architecture_constraints_reject_injected_unlocks(self):
        from execution_kgi_simulator.tests.test_boundaries import CHECKER, CONSTRAINTS
        rules = [r for r in CHECKER.load_rules(CONSTRAINTS)
                 if r['id'] in {'login_only_no_order_or_live_adapter',
                                 'qualification_cannot_dispatch_login_fixture'}]
        self.assertTrue(rules)
        for rule in rules:
            for target in rule['forbidden_call_names']:
                with self.subTest(rule=rule['id'], target=target):
                    tree = ast.parse('sdk.' + target + '()')
                    facts = CHECKER.PythonFactCollector()
                    facts.visit(tree)
                    with patch.object(CHECKER, 'parse_python', return_value=(tree, facts)):
                        self.assertTrue(CHECKER.check_forbidden_calls(ROOT, rule))

    def test_owner_reference_matches_source_without_loading_settings(self):
        ref = credential_owner_reference()
        self.assertEqual(ref.owner, 'app.config.Settings')
        self.assertEqual(ref.ingress, 'BLOCKED_BEFORE_SETTINGS_READ')
        source = ast.parse((ROOT / 'backend/app/config.py').read_text(encoding='utf-8-sig'))
        settings = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'Settings')
        fields = {n.target.id for n in settings.body if isinstance(n, ast.AnnAssign)}
        self.assertTrue(set(ref.fields) <= fields)
        with self.assertRaises(TypeError):
            CredentialOwnerReference(owner='OTHER')
        with self.assertRaises(FrozenInstanceError):
            ref.target = 'PROD'

    def test_typed_pipe_roundtrip_with_invented_inputs_and_redacted_repr(self):
        generation = secrets.token_hex(16)
        credentials = Credentials('INVENTED_PERSON', 'INVENTED_SECRET')
        encoded = encode_private_frame(credentials, generation)
        decoded = read_private_frame(io.BytesIO(encoded), generation)
        self.assertEqual(decoded.password, 'INVENTED_SECRET')
        self.assertNotIn('INVENTED', repr(decoded))
        decoded.clear()
        self.assertEqual(decoded.password, '')

    def test_private_frame_rejects_proof_target_extra_keys_and_duplicate_keys(self):
        generation = secrets.token_hex(16)
        good = {'generation': generation, 'person_id': 'INVENTED_PERSON', 'password': 'INVENTED_SECRET'}
        for key in ('simulation', 'target', 'proof', 'sdk', 'executable', 'path', 'owner', 'account'):
            raw = json.dumps(good | {key: 'INVENTED_SECRET'}).encode()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '^INVALID_PRIVATE_FRAME$'):
                read_private_frame(io.BytesIO(raw), generation)
        for raw in (b'null', b'[]', b'{' , b' ' * 4097,
                    json.dumps(good | {'generation': '0' * 32}).encode(),
                    json.dumps(good | {'password': None}).encode(),
                    json.dumps(good | {'password': ''}).encode(),
                    json.dumps(good | {'password': '\nsecret'}).encode(),
                    json.dumps(good).encode()[:-1] + b',"password":"INVENTED_SECRET"}'):
            with self.assertRaisesRegex(ValueError, '^INVALID_PRIVATE_FRAME$'):
                read_private_frame(io.BytesIO(raw), generation)


class IsolatedLoginProcess(unittest.TestCase):
    def test_positive_child_and_sensitive_stdout_stderr_fd_suppression(self):
        for scenario in ('accept', 'noise'):
            report = run_child(scenario)
            self.assertEqual(report['status'], 'LOCAL_MOCK_ACCEPTED')
            self.assertEqual(report['fixture_calls'], {'login': 1, 'readback': 1, 'logout': 1, 'order': 0})
            self.assertNotIn('INVENTED', json.dumps(report))
            self.assertFalse(report['sdk_imported'])

    def test_hung_login_logout_timeout_and_explicit_cancellation_stop_only_owned_child(self):
        sentinel = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', 'import time; time.sleep(20)'],
            env={'SystemRoot': os.environ.get('SystemRoot', '')},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for scenario, cancel in (('hang', False), ('logout_hang', False), ('hang', True)):
                report = run_child(scenario, cancel=cancel)
                self.assertEqual(report['status'], 'UNKNOWN')
                self.assertTrue(report['stopped'])
                self.assertFalse(report['logout_confirmed'])
                self.assertIsNone(sentinel.poll())
                self.assertNotEqual(report['owned_pid'], sentinel.pid)
                self.assertEqual(report['stdout_bytes'] + report['stderr_bytes'], 0)
        finally:
            sentinel.kill()
            sentinel.wait(timeout=3)

    def test_child_malformed_pipe_is_sanitized(self):
        report = run_child('accept', raw=b'{"proof": "INVENTED_SECRET"}')
        self.assertEqual(report['reasonCodes'], ['INVALID_FIXTURE_INPUT'])
        self.assertNotIn('INVENTED', json.dumps(report))

    def test_shipping_worker_refuses_mock_flags_sdk_and_proof(self):
        for extra in ('--test_preflight', '--simulation', '--sdk', '--proof', '../INVENTED_SECRET'):
            child = subprocess.run([sys.executable, '-I', '-S', '-B',
                str(ROOT / 'execution_kgi_simulator/worker.py'), 'RealSimProbe', extra],
                input=b'{}', capture_output=True, timeout=5,
                env={'SystemRoot': os.environ.get('SystemRoot', '')})
            self.assertEqual(child.returncode, 2)
            self.assertEqual(child.stderr, b'')
            self.assertNotIn(b'INVENTED', child.stdout)
            self.assertEqual(json.loads(child.stdout)['reasonCodes'], ['WORKER_FAILED_CLOSED'])

    def test_shipping_launcher_exact_cli_allowlist(self):
        ps = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        for args in (['-Mode', 'realsimprobe'], ['-Mode', '../INVENTED_SECRET'],
                     ['-Mode', 'RealSimProbe', '-proof', 'INVENTED_SECRET'],
                     ['-TimeoutSeconds', 'NaN'], ['-TimeoutSeconds', '181']):
            child = subprocess.run([ps, '-NoProfile', '-File',
                str(ROOT / 'scripts/test-kgi-official-simulator.ps1'), *args],
                capture_output=True, timeout=10, env={'SystemRoot': os.environ['SystemRoot']})
            self.assertEqual(child.returncode, 2)
            self.assertNotIn(b'INVENTED', child.stdout + child.stderr)
            self.assertEqual(json.loads(child.stdout)['reasonCodes'], ['INVALID_LAUNCHER_ARGUMENTS'])

    def test_sdk_source_reparse_and_traversal_rejected(self):
        from execution_kgi_simulator.inspection import _source_path
        from types import SimpleNamespace
        with self.assertRaisesRegex(ValueError, 'SDK_SOURCE_PATH_REJECTED'):
            _source_path(ROOT, '../outside')
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=0, st_file_attributes=0x400)):
            with self.assertRaisesRegex(ValueError, 'SDK_SOURCE_REPARSE_REJECTED'):
                _source_path(ROOT, 'execution_kgi_simulator/login_probe.py')


if __name__ == '__main__':
    unittest.main()
