"""Offline source/negative tests. All credentials and SDK responses are invented.

Patching the non-issuing gate in a unit process is NOT host acceptance. No test
imports the installed SDK, app.config or any actual credential/CA/log file.
"""

import ast
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

from execution_kgi_simulator.login_probe import Credentials, encode_private_frame
from execution_kgi_simulator.native import adapter, credentials, readiness, worker


ROOT = Path(__file__).resolve().parents[2]
GENERATION = 'a' * 32
PERSON = 'INVENTED_PERSON_ONLY'
PASSWORD = 'INVENTED_PASSWORD_ONLY'


class FakeNative:
    """SDK-shaped unit double for the REAL adapter body, not login_fixture."""
    def __init__(self, *, target=True, accepted=True, rows=None, fail_logout=False):
        self.simulation = target
        self.person_id = PERSON
        self.person_pwd = PASSWORD
        self._ObjOrder = types.SimpleNamespace(FIsLogon=accepted, GetAccounts=self.accounts)
        self.rows = rows if rows is not None else json.dumps([
            {'broker_id': 'INVENTED_BRANCH', 'account': 'INVENTED_ACCOUNT', 'account_flag': 'S'}])
        self.fail_logout = fail_logout
        self.reads = self.logouts = 0

    def accounts(self):
        self.reads += 1
        return self.rows

    def _logout(self):
        self.logouts += 1
        if self.fail_logout:
            raise RuntimeError(PASSWORD)


class NativeActivation(unittest.TestCase):
    def test_actual_fixed_sdk_hashes_markers_and_non_attestation(self):
        report = readiness.readiness()
        self.assertTrue(all(x['integrity'] == 'MATCHES_REVIEWED_LOCAL_BYTES' for x in report['files']))
        compiled = next(x for x in report['files'] if x['path'].endswith('.pyd'))
        self.assertEqual(compiled['binary']['format'], 'AMD64_PE32_PLUS')
        self.assertTrue(compiled['binary']['named_markers']['AutoRefresh'])
        self.assertFalse(compiled['binary']['behavior_verified'])
        self.assertTrue(report['review_locations']['SDK_CHANGES_WORKING_DIRECTORY'])
        self.assertEqual(report['gates']['G3'], 'BLOCKED')
        self.assertIn('COMPILED_AUTOREFRESH_EGRESS_UNVERIFIED', report['reasonCodes'])
        self.assertEqual(report['official_target']['pinned_destinations'], 0)

    def test_pe_malformed_never_passes(self):
        for data in (b'', b'MZ', b'MZ' + b'\xff' * 100, b'PE\0\0' * 40):
            self.assertEqual(readiness._binary_observation(data)['format'], 'UNKNOWN')

    def test_fixed_path_rejects_nonlocal_traversal_and_reparse(self):
        from execution_kgi_simulator.inspection import _source_path
        for path in ('../outside', 'C:/outside', '//server/share/sdk.pyd'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                _source_path(ROOT, path)
        with patch.object(Path, 'lstat', return_value=types.SimpleNamespace(
                st_mode=stat.S_IFREG, st_file_attributes=0x400)):
            with self.assertRaisesRegex(ValueError, 'REPARSE'):
                _source_path(ROOT, readiness.SDK_PREFIX + 'main.py')

    def test_permission_missing_and_reparse_errors_are_redacted(self):
        for error, reason in ((PermissionError(PASSWORD), 'SDK_FILE_ACCESS_DENIED'),
                              (FileNotFoundError(PASSWORD), 'SDK_FILE_MISSING'),
                              (ValueError(PASSWORD), 'SDK_FILE_UNSAFE_OR_UNREADABLE')):
            with self.subTest(reason=reason), patch.object(readiness, '_source_path', side_effect=error):
                items = readiness._inspect_files()
                self.assertTrue(all(x['reason'] == reason for x in items))
                self.assertNotIn(PASSWORD, json.dumps(items))

    def test_tampered_bytes_block_secondary_validation(self):
        fake = types.SimpleNamespace(open=lambda *_: io.BytesIO(b'changed SDK'))
        with patch.object(readiness, '_source_path', return_value=fake):
            self.assertTrue(all(x['integrity'] == 'DRIFT' for x in readiness._inspect_files()))
            with self.assertRaises(readiness.ActivationBlocked):
                readiness.revalidate_reviewed_bytes()

    def test_forged_all_verified_report_does_not_issue_authority(self):
        with patch.object(readiness, 'readiness', return_value={'status': 'ALL VERIFIED'}):
            with self.assertRaises(readiness.ActivationBlocked):
                readiness.require_verified_host()
        for field in ('proof', 'endpoint', 'simulation', 'all_verified', 'host'):
            with self.subTest(field=field), self.assertRaises(TypeError):
                readiness.require_verified_host(**{field: True})

    def test_no_settings_import_before_gate_even_with_invented_module(self):
        touched = []
        fake = types.ModuleType('app.config')
        fake.__getattr__ = lambda name: touched.append(name)
        with patch.dict(sys.modules, {'app.config': fake}):
            with self.assertRaises(readiness.ActivationBlocked):
                credentials._canonical_frame(GENERATION)
        self.assertEqual(touched, [])

    def test_real_settings_owner_bridge_with_synthetic_module_only(self):
        fake = types.ModuleType('app.config')
        fake.settings = types.SimpleNamespace(kgi_superpy_person_id=PERSON, kgi_superpy_password=PASSWORD)
        events = []
        with patch.dict(sys.modules, {'app.config': fake}), \
                patch.object(credentials, 'require_verified_host', side_effect=lambda: events.append('gate')), \
                patch.object(credentials, 'revalidate_reviewed_bytes', side_effect=lambda: events.append('hash')):
            frame = credentials._canonical_frame(GENERATION)
        self.assertEqual(json.loads(frame), {'generation': GENERATION, 'person_id': PERSON, 'password': PASSWORD})
        self.assertEqual(events, ['gate', 'hash', 'gate'])
        self.assertEqual(fake.settings.kgi_superpy_password, PASSWORD)  # Owner is not mutated.

    def test_settings_error_is_redacted(self):
        fake = types.ModuleType('app.config')
        def fail(name):
            raise RuntimeError(PASSWORD)
        fake.__getattr__ = fail
        with patch.dict(sys.modules, {'app.config': fake}), \
                patch.object(credentials, 'require_verified_host'), \
                patch.object(credentials, 'revalidate_reviewed_bytes'):
            with self.assertRaisesRegex(readiness.ActivationBlocked, '^NATIVE_HOST_ACTIVATION_BLOCKED$'):
                credentials._canonical_frame(GENERATION)

    def test_handoff_never_reads_or_writes_before_gate(self):
        reader, writer = unittest.mock.Mock(), unittest.mock.Mock()
        with self.assertRaises(readiness.ActivationBlocked):
            credentials._handoff_once(reader, writer)
        reader.readline.assert_not_called()
        writer.write.assert_not_called()

    def test_private_handoff_one_frame_and_eof(self):
        challenge = json.dumps({'schema': 'omi.kgi-native-private-ready.v1', 'generation': GENERATION}).encode() + b'\n'
        writer = unittest.mock.Mock()
        writer.write.side_effect = lambda value: len(value)
        with patch.object(credentials, 'require_verified_host'), \
                patch.object(credentials, '_canonical_frame', return_value=b'INVENTED_FRAME') as frame:
            credentials._handoff_once(io.BytesIO(challenge), writer)
        frame.assert_called_once_with(GENERATION)
        writer.write.assert_called_once_with(b'INVENTED_FRAME')
        writer.close.assert_called_once()

    def test_private_challenge_injection_duplicate_wrong_target_or_partial_write_rejected(self):
        for raw in (b'{}\n', b'{"proof":true}\n', b'x' * 1025,
                    b'{"schema":"omi.kgi-native-private-ready.v1","generation":"a","generation":"b"}\n',
                    b'{"schema":"omi.kgi-native-private-ready.v1","generation":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","target":"PROD"}\n'):
            with self.subTest(raw=raw[:30]), patch.object(credentials, 'require_verified_host'), \
                    patch.object(credentials, '_canonical_frame') as frame:
                writer = unittest.mock.Mock()
                with self.assertRaises(readiness.ActivationBlocked):
                    credentials._handoff_once(io.BytesIO(raw), writer)
                frame.assert_not_called()
                writer.write.assert_not_called()
        challenge = json.dumps({'schema': 'omi.kgi-native-private-ready.v1', 'generation': GENERATION}).encode() + b'\n'
        with patch.object(credentials, 'require_verified_host'), \
                patch.object(credentials, '_canonical_frame', return_value=b'INVENTED_FRAME'):
            writer = unittest.mock.Mock()
            writer.write.return_value = 0
            with self.assertRaises(readiness.ActivationBlocked):
                credentials._handoff_once(io.BytesIO(challenge), writer)
            writer.close.assert_called_once()

    def invoke_adapter(self, native=None, login_error=None):
        calls = []
        def login(person, password, *, simulation):
            calls.append((person, password, simulation))
            if login_error:
                raise login_error
            return native
        fake = types.ModuleType('kgisuperpy')
        fake.login = login
        secret = Credentials(PERSON, PASSWORD)
        with patch.dict(sys.modules, {'kgisuperpy': fake}), \
                patch.object(adapter, 'require_verified_host'), \
                patch.object(adapter, 'revalidate_reviewed_bytes'):
            result = adapter._login_readback_logout(secret)
        self.assertEqual(calls, [(PERSON, PASSWORD, True)])
        self.assertEqual(secret.password, '')
        self.assertNotIn(PASSWORD, json.dumps(result))
        self.assertNotIn('INVENTED_ACCOUNT', json.dumps(result))
        self.assertNotEqual(result['status'], 'PASS')
        self.assertEqual(result['orders_sent'], 0)
        return result

    def test_real_adapter_literal_sim_one_login_readback_logout_no_false_finality(self):
        native = FakeNative()
        result = self.invoke_adapter(native)
        self.assertEqual((native.reads, native.logouts), (1, 1))
        self.assertIsNone(native.person_pwd)
        self.assertEqual(result['account_readback'], 'OBSERVED_NOT_ENTITLEMENT_PROOF')
        self.assertEqual(result['logout'], 'RETURNED_WITHOUT_BROKER_ACK')
        self.assertEqual(result['status'], 'UNKNOWN')

    def test_wrong_target_false_login_and_int_flag_refuse_readback_then_logout(self):
        for target, accepted in ((False, True), (1, True), (True, False), (True, 1)):
            native = FakeNative(target=target, accepted=accepted)
            result = self.invoke_adapter(native)
            self.assertEqual((native.reads, native.logouts), (0, 1))
            self.assertEqual(result['account_readback'], 'NOT_REQUESTED')

    def test_bad_readback_and_logout_failure_remain_unknown(self):
        for rows in ('[]', '{}', PASSWORD, '[{}]', '[{"account":"a","account":"b"}]', 'x' * 65537):
            native = FakeNative(rows=rows, fail_logout=True)
            result = self.invoke_adapter(native)
            self.assertEqual(native.logouts, 1)
            self.assertEqual(result['logout'], 'UNVERIFIED')
            self.assertEqual(result['status'], 'UNKNOWN')

    def test_readback_duplicate_identity_types_and_limits(self):
        row = {'account': 'INVENTED_ACCOUNT', 'broker_id': 'INVENTED_BRANCH', 'account_flag': 'S'}
        invalid = [None, b'[]', 'x' * 65537, 'null', '[]', '{}', '[null]',
                   json.dumps([row, row]), json.dumps([row] * 129),
                   '[{"account":"a","account":"b","broker_id":"x","account_flag":"S"}]']
        for key in row:
            for value in ('', None, True, 1, 'x' * 129, 'x\ny'):
                invalid.append(json.dumps([row | {key: value}]))
        for raw in invalid:
            with self.subTest(raw=str(raw)[:40]), self.assertRaises(ValueError):
                adapter._readback_count(raw)
        self.assertEqual(adapter._readback_count(json.dumps([row])), 1)

    def test_constructor_failure_no_retry_or_claimed_logout(self):
        result = self.invoke_adapter(login_error=RuntimeError(PASSWORD))
        self.assertEqual(result['login_attempts'], 1)
        self.assertEqual(result['logout'], 'NOT_REQUESTED')

    def test_adapter_blocks_before_sdk_import_or_secret_access(self):
        with patch.dict(sys.modules, {'kgisuperpy': None}):
            with self.assertRaises(readiness.ActivationBlocked):
                adapter._login_readback_logout(object())

    def test_child_channel_checks_gate_before_handshake_and_secrets(self):
        reader, writer = unittest.mock.Mock(), unittest.mock.Mock()
        with self.assertRaises(readiness.ActivationBlocked):
            worker._run_private_channel(reader, writer)
        reader.read.assert_not_called()
        writer.write.assert_not_called()

    def test_worker_contract_invented_trace_one_shot(self):
        secret = Credentials(PERSON, PASSWORD)
        frame = encode_private_frame(secret, GENERATION)
        output = io.BytesIO()
        with patch.object(readiness, 'require_verified_host'), \
                patch.object(readiness, 'revalidate_reviewed_bytes'), \
                patch.object(worker.secrets, 'token_hex', return_value=GENERATION), \
                patch.object(adapter, '_login_readback_logout', return_value={'status': 'UNKNOWN'}) as invoke:
            self.assertEqual(worker._run_private_channel(io.BytesIO(frame), output), 2)
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual(invoke.call_args.args[0].password, '')
        self.assertNotIn(PASSWORD.encode(), output.getvalue())
        self.assertEqual(len(output.getvalue().splitlines()), 2)

    def test_actual_worker_rejects_proof_and_does_not_wait_for_stdin_eof(self):
        for args in ([], ['--proof', PASSWORD], ['--target', 'PROD']):
            child = subprocess.Popen([sys.executable, '-I', '-S', '-B',
                str(ROOT / 'execution_kgi_simulator/native/worker.py'), *args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={'SystemRoot': os.environ.get('SystemRoot', '')})
            try:
                code = child.wait(timeout=5)  # stdin deliberately open; no secret read.
                stdout, stderr = child.communicate(timeout=5)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
            self.assertEqual(code, 2)
            self.assertEqual(stderr, b'')
            self.assertNotIn(PASSWORD.encode(), stdout)
            result = json.loads(stdout)
            self.assertFalse(result['credential_values_read'])
            self.assertEqual(result['broker_calls'], 0)

    def test_actual_worker_hostile_env_stdin_and_monkeypatch_text_cannot_activate(self):
        hostile = {'SystemRoot': os.environ.get('SystemRoot', ''),
                   'KGI_SUPERPY_PERSON_ID': PERSON, 'KGI_SUPERPY_PASSWORD': PASSWORD,
                   'KGI_SUPERPY_SIMULATION': 'false', 'ALL_VERIFIED': 'true',
                   'PYTHONPATH': 'INVENTED_UNTRUSTED_PATH', 'PYTHONSTARTUP': 'INVENTED_UNTRUSTED_STARTUP'}
        for raw in (json.dumps({'all_verified': True, 'endpoint': 'https://production.invalid', 'password': PASSWORD}),
                    'import execution_kgi_simulator.native.readiness as r; r.require_verified_host=lambda: None',
                    PASSWORD * 1000):
            child = subprocess.run([sys.executable, '-I', '-S', '-B',
                str(ROOT / 'execution_kgi_simulator/native/worker.py')],
                input=raw, capture_output=True, text=True, env=hostile, timeout=5)
            self.assertEqual(child.returncode, 2)
            self.assertEqual(child.stderr, '')
            self.assertNotIn(PASSWORD, child.stdout)
            self.assertNotIn(PERSON, child.stdout)
            result = json.loads(child.stdout)
            self.assertFalse(result['sdk_imported'])
            self.assertFalse(result['credential_values_read'])
            self.assertEqual(result['login_attempts'], 0)

    def test_cold_process_blocks_settings_import_through_all_entrypoints(self):
        script = '''import sys
class DenySensitive:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('app', 'app.config', 'kgisuperpy'):
            raise AssertionError('EARLY_SENSITIVE_IMPORT')
sys.meta_path.insert(0, DenySensitive())
from execution_kgi_simulator.native.credentials import _canonical_frame
from execution_kgi_simulator.native.adapter import _login_readback_logout
from execution_kgi_simulator.native.readiness import ActivationBlocked
for call in (lambda: _canonical_frame('a'*32), lambda: _login_readback_logout(object())):
    try: call()
    except ActivationBlocked: pass
    else: raise AssertionError('GATE_OPENED')
assert 'app.config' not in sys.modules and 'kgisuperpy' not in sys.modules
'''
        child = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
            'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + ');\n' + script],
            capture_output=True, text=True, env={'SystemRoot': os.environ.get('SystemRoot', '')}, timeout=5)
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_scoped_architecture_guards_reject_orders_and_second_owner(self):
        from execution_kgi_simulator.tests.test_boundaries import CHECKER, CONSTRAINTS, DEBT
        self.assertTrue(CHECKER.evaluate(ROOT, constraints_path=CONSTRAINTS, debt_path=DEBT).passed)
        rules = [r for r in CHECKER.load_rules(CONSTRAINTS) if r['id'].startswith('native_')]
        for rule in rules:
            imports = rule['kind'] == 'python_forbidden_import'
            for name in rule['forbidden_prefixes' if imports else 'forbidden_call_names']:
                tree = ast.parse('import ' + name if imports else name + '()')
                facts = CHECKER.PythonFactCollector()
                facts.visit(tree)
                with patch.object(CHECKER, 'parse_python', return_value=(tree, facts)):
                    check = CHECKER.check_forbidden_imports if imports else CHECKER.check_forbidden_calls
                    self.assertTrue(check(ROOT, rule), (rule['id'], name))

    def test_only_literal_sim_login_no_alternate_credential_owner(self):
        tree = ast.parse((ROOT / 'execution_kgi_simulator/native/adapter.py').read_text())
        logins = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == 'login']
        self.assertEqual(len(logins), 1)
        self.assertTrue(any(k.arg == 'simulation' and isinstance(k.value, ast.Constant)
                            and k.value.value is True for k in logins[0].keywords))
        tree = ast.parse((ROOT / 'execution_kgi_simulator/native/credentials.py').read_text())
        owner_import = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == 'app.config']
        self.assertEqual(len(owner_import), 1)
        self.assertEqual([n.name for n in owner_import[0].names], ['settings'])

    def test_source_worker_and_activation_worker_have_distinct_exact_scopes(self):
        from execution_kgi_simulator.tests.test_boundaries import CHECKER, CONSTRAINTS
        rules = {r['id']: r for r in CHECKER.load_rules(CONSTRAINTS)}
        source = rules['native_sim_no_issuer_or_secret_dispatch_in_source_worker']
        self.assertEqual(set(source['roots']), {'execution_kgi_simulator/worker.py',
            'execution_kgi_simulator/real_sim.py', 'execution_kgi_simulator/native/readiness.py'})
        self.assertIn('execution_kgi_simulator.native.adapter', source['forbidden_prefixes'])
        native = rules['native_child_never_reads_settings_or_fixture']
        self.assertEqual(native['roots'], ['execution_kgi_simulator/native/worker.py'])
        for forbidden in ('app', 'backend', 'execution_kgi_simulator.native.credentials',
                          'execution_kgi_simulator.tests', 'kgisuperpy'):
            self.assertIn(forbidden, native['forbidden_prefixes'])
        self.assertNotIn('execution_kgi_simulator.native.adapter', native['forbidden_prefixes'])

    def test_sensitive_imports_and_channel_io_are_dominated_by_direct_gate(self):
        # Direct, unconditional gate must precede each sensitive statement. An
        # if/proof wrapper or a removed gate is rejected by this source contract.
        checks = [('credentials.py', '_canonical_frame', {'settings'}),
                  ('credentials.py', '_handoff_once', {'readline', '_canonical_frame'}),
                  ('adapter.py', '_login_readback_logout', {'kgisuperpy', 'login'}),
                  ('worker.py', '_run_private_channel', {'read_private_frame', '_login_readback_logout', 'write'})]
        def enforced(function, sensitive):
            gates = [n.lineno for n in function.body if isinstance(n, ast.Expr)
                     and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                     and n.value.func.id == 'require_verified_host']
            uses = []
            for node in ast.walk(function):
                if isinstance(node, ast.Import):
                    if any(a.name in sensitive for a in node.names): uses.append(node.lineno)
                elif isinstance(node, ast.ImportFrom):
                    if any(a.name in sensitive for a in node.names): uses.append(node.lineno)
                elif isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
                    if name in sensitive: uses.append(node.lineno)
            return bool(gates and uses and min(gates) < min(uses))
        for filename, name, sensitive in checks:
            tree = ast.parse((ROOT / 'execution_kgi_simulator/native' / filename).read_text())
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertTrue(enforced(function, sensitive), name)
            function.body = [n for n in function.body if not (isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                and n.value.func.id == 'require_verified_host')]
            self.assertFalse(enforced(function, sensitive), name)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell')
    def test_powershell_rejects_false_native_readiness_pass(self):
        from execution_kgi_simulator.real_sim import qualify
        import copy
        good = qualify(ROOT, {}, datetime.now(timezone.utc), mode='RealSimPreflight')
        cases = [good]
        for section, key, value in ((None, 'status', 'ALL VERIFIED'),
                                    ('gates', 'G1', 'PASS'), ('gates', 'G2', 'PASS'), ('gates', 'G3', 'PASS'),
                                    ('containment', 'status', 'VERIFIED'),
                                    ('official_target', 'status', 'VERIFIED'),
                                    (None, 'credential_values_read', True), (None, 'broker_calls', 1)):
            bad = copy.deepcopy(good)
            target = bad['native_readiness'] if section is None else bad['native_readiness'][section]
            target[key] = value
            cases.append(bad)
        ps = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        script = ". './scripts/test-kgi-official-simulator.ps1'; $items = [Console]::In.ReadToEnd() | ConvertFrom-Json; foreach ($item in $items) { try { Assert-KgiQualificationResponse $item 2 'RealSimPreflight'; 'ACCEPT' } catch { 'REJECT' } }"
        child = subprocess.run([ps, '-NoProfile', '-Command', script], cwd=ROOT,
            input=json.dumps(cases), text=True, capture_output=True, timeout=20,
            env={'SystemRoot': os.environ.get('SystemRoot', '')})
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.splitlines(), ['ACCEPT'] + ['REJECT'] * (len(cases)-1))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell')
    def test_host_inventory_arguments_cannot_authorize_or_leak(self):
        ps = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        child = subprocess.run([ps, '-NoProfile', '-File', 'scripts/test-kgi-native-containment.ps1', PASSWORD],
            cwd=ROOT, text=True, capture_output=True, timeout=10,
            env={'SystemRoot': os.environ.get('SystemRoot', '')})
        self.assertEqual(child.returncode, 2)
        self.assertNotIn(PASSWORD, child.stdout + child.stderr)
        self.assertEqual(json.loads(child.stdout)['reasonCodes'], ['UNEXPECTED_ARGUMENTS'])


if __name__ == '__main__':
    unittest.main()
