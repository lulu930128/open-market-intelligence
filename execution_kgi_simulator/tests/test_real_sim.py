"""Source qualification tests. No fake or real broker is invoked."""

import ast
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from execution_kgi_simulator.gates import SIM_NAMES
from execution_kgi_simulator.real_sim import qualify
from execution_kgi_simulator.worker import read_presence


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 12, 1, tzinfo=timezone.utc)


class RealSimQualification(unittest.TestCase):
    def test_installed_source_inspection_is_positive_but_never_runtime_proof(self):
        report = qualify(ROOT, {}, NOW, mode='RealSimPreflight')
        self.assertEqual(report['sdk']['installed_version'], '2.1.0')
        source = report['connection_source']
        for concern in ('NATIVE_CONNECT_FROM_RUNTIME_HOST', 'DYNAMIC_ENDPOINT_RESOLVER',
                        'IDENTITY_DERIVED_LOG_NAME', 'SDK_STDOUT'):
            self.assertTrue(source['review_locations'][concern])
        self.assertFalse(source['endpoint_attested'])
        self.assertEqual(report['origin'], 'SOURCE_INSPECTION')
        self.assertEqual(report['runtime_origin'], 'NOT_CONNECTED')
        self.assertFalse(report['broker_connected'])

    def test_all_presence_does_not_clear_identity_env_units_or_owner_gates(self):
        for mode in ('RealSimPreflight', 'RealSimProbe'):
            report = qualify(ROOT, dict.fromkeys(SIM_NAMES, True), NOW, mode=mode)
            self.assertEqual(report['status'], 'BLOCKED')
            self.assertEqual(report['connector'], 'NOT_IMPLEMENTED')
            for code in ('SIM_ENTITLEMENT_UNVERIFIED', 'BROKER_ENV_UNKNOWN',
                         'NATIVE_ENDPOINT_ATTESTATION_MISSING', 'QTY_UNIT_UNPROVEN',
                         'SDK_ABI_UNVERIFIED', 'DURABLE_REAL_SIM_LEDGER_MISSING',
                         'REAL_SIM_ORIGIN_INGRESS_NOT_IMPLEMENTED',
                         'BROKER_CALLBACK_FINALITY_UNVERIFIED'):
                self.assertIn(code, report['order']['reasonCodes'])
            for key in ('login_attempts', 'broker_calls', 'orders_sent',
                        'cancel_requests', 'native_probe_attempts'):
                self.assertEqual(report[key], 0)

    def test_only_bounded_unique_boolean_presence_is_accepted(self):
        self.assertEqual(read_presence(io.StringIO('{}')), {})
        payload = dict.fromkeys(SIM_NAMES, True)
        self.assertEqual(read_presence(io.StringIO(json.dumps(payload))), payload)
        for raw in ('[]', 'null', '{"KGI_SIM_PASSWORD":"invented-secret"}',
                    '{"KGI_SIM_ACCOUNT":1}', '{"KGI_SIM_ACCOUNT":true,"KGI_SIM_ACCOUNT":false}',
                    '{"KGI_SUPERPY_PERSON_ID":true}', '{"simulation":true}',
                    '{"endpoint_attested":true}', '{"runtime_origin":"REAL_SIM"}',
                    '{"account":"wrong-account"}', '{"environment":"PROD"}',
                    '{"qty":1}', '{"order_id":"invented-order"}',
                    '{"status":"Pending"}', '{"status":"Success"}',
                    '{"cancel_ack":true}', '{"sdk_error":"invented-native-error"}',
                    '{"timeout":true}', '{"proof":{"verified":true}}', ' ' * 4097):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                read_presence(io.StringIO(raw))

    def test_connector_has_no_sdk_session_order_callback_or_proof_injection(self):
        for key in ('sdk', 'session', 'credentials', 'proof', 'callback', 'order'):
            with self.subTest(key=key), self.assertRaises(TypeError):
                qualify(ROOT, {}, NOW, mode='RealSimProbe', **{key: object()})
        for mode in ('Send', 'PROD', 'LIVE', 'SYNTHETIC'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                qualify(ROOT, {}, NOW, mode=mode)
        tree = ast.parse((ROOT / 'execution_kgi_simulator/real_sim.py').read_text())
        calls = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertFalse(calls & {'login', 'create_order', 'cancel_order', 'callback',
                                  'assess', 'transition', 'commit'})

    def test_readonly_hook_denies_native_network_writes_and_processes(self):
        script = '''import os, sys
from execution_kgi_simulator.worker import readonly_guard
sys.addaudithook(readonly_guard)
events = [('socket.connect', (None, None)), ('ctypes.dlopen', ('invented',)),
          ('import', ('kgisuperpy',)), ('open', ('invented', 'w', os.O_WRONLY)),
          ('open', ('invented', None, os.O_CREAT)), ('os.mkdir', ('invented', 511, -1)),
          ('os.remove', ('invented', -1)), ('os.rename', ('a', 'b', -1, -1)),
          ('subprocess.Popen', ('invented', [], None, {}))]
for event, args in events:
    try: sys.audit(event, *args)
    except RuntimeError: pass
    else: raise AssertionError(event)
sys.audit('open', 'invented-read-only', 'r', 0)
'''
        child = subprocess.run([sys.executable, '-B', '-S', '-c', script], cwd=ROOT,
                               capture_output=True, text=True, timeout=10,
                               env={'SystemRoot': os.environ.get('SystemRoot', '')})
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_launcher_scrubs_environment_and_noncontract_path_does_not_create_temp(self):
        source = (ROOT / 'scripts/test-kgi-official-simulator.ps1').read_text()
        self.assertIn('$childEnvironment.Clear()', source)
        self.assertNotIn("Test-Path -LiteralPath ('Env:' + $name)", source)
        self.assertIn("if ($Mode -eq 'ContractTest') {\n            [System.IO.Directory]::CreateDirectory", source)
        self.assertNotIn('WaitForExit()', source)
        self.assertNotIn('KGI_SUPERPY_', source)

    def test_real_sim_architecture_guards_reject_injected_source_without_writes(self):
        from execution_kgi_simulator.tests.test_boundaries import CHECKER, CONSTRAINTS
        rules = [r for r in CHECKER.load_rules(CONSTRAINTS) if r['id'].startswith('real_sim_')]
        self.assertTrue(rules)
        for rule in rules:
            imports = rule['kind'] == 'python_forbidden_import'
            targets = rule['forbidden_prefixes' if imports else 'forbidden_call_names']
            for target in targets:
                with self.subTest(rule=rule['id'], target=target):
                    tree = ast.parse('import ' + target if imports else 'sdk.' + target + '()')
                    facts = CHECKER.PythonFactCollector()
                    facts.visit(tree)
                    with patch.object(CHECKER, 'parse_python', return_value=(tree, facts)):
                        check = CHECKER.check_forbidden_imports if imports else CHECKER.check_forbidden_calls
                        violations = check(ROOT, rule)
                    self.assertTrue(violations)
                    self.assertTrue(all(v.key.path == 'execution_kgi_simulator/real_sim.py'
                                        for v in violations))


class IsolatedWorkerRegression(unittest.TestCase):
    """Actual -I -S -B worker and launcher, no temp directory or broker effect."""

    def worker(self, mode, raw):
        return subprocess.run(
            [sys.executable, '-I', '-S', '-B', str(ROOT / 'execution_kgi_simulator/worker.py'), mode],
            cwd=ROOT, input=raw, capture_output=True, text=True, timeout=10,
            env={'SystemRoot': os.environ.get('SystemRoot', '')})

    def test_actual_probe_all_presence_combinations_remain_blocked(self):
        for bits in range(8):
            presence = {name: bool(bits & (1 << i)) for i, name in enumerate(SIM_NAMES)}
            with self.subTest(bits=bits):
                child = self.worker('RealSimProbe', json.dumps(presence))
                self.assertEqual(child.returncode, 2, child.stderr)
                self.assertEqual(child.stderr, '')
                report = json.loads(child.stdout)
                self.assertEqual(report['status'], 'BLOCKED')
                self.assertEqual(report['runtime_origin'], 'NOT_CONNECTED')
                self.assertEqual(report['dedicated_secret_presence'], presence)
                self.assertTrue(all(report['worker'][key]
                                    for key in ('isolated', 'no_site', 'no_bytecode')))
                self.assertEqual(report['orders_sent'], 0)
                self.assertEqual(report['broker_calls'], 0)
                self.assertFalse(report['sdk_imported'])

    def test_actual_worker_untrusted_proof_and_malformed_input_are_redacted(self):
        cases = ['{"KGI_SIM_ACCOUNT":true,"KGI_SIM_ACCOUNT":true}',
                 ' ' * 4097, 'null', '{',
                 '{"KGI_SIM_PASSWORD":"INVENTED_SECRET"}',
                 '{"endpoint":"https://invented-prod.invalid/INVENTED_SECRET"}',
                 '{"proof":{"simulation":true,"account":"INVENTED_SECRET","attested":true}}',
                 '{"KGI_SUPERPY_PERSON_ID":true}', '{"simulation":true}',
                 '{"runtime_origin":"REAL_SIM"}']
        for raw in cases:
            with self.subTest(raw=raw[:60]):
                child = self.worker('RealSimProbe', raw)
                self.assertEqual(child.returncode, 2, child.stderr)
                self.assertEqual(child.stderr, '')
                self.assertNotIn('INVENTED_SECRET', child.stdout)
                report = json.loads(child.stdout)
                self.assertEqual(report['reasonCodes'], ['WORKER_FAILED_CLOSED'])
                self.assertEqual(report['broker_calls'], 0)
                self.assertEqual(report['orders_sent'], 0)

    def test_old_modes_and_real_preflight_still_exit_two(self):
        for mode in ('Preflight', 'Probe', 'Send', 'RealSimPreflight'):
            with self.subTest(mode=mode):
                child = self.worker(mode, '{}')
                self.assertEqual(child.returncode, 2, child.stderr)
                report = json.loads(child.stdout)
                self.assertEqual(report['status'], 'BLOCKED')
                self.assertEqual(report['login_attempts'], 0)
                self.assertEqual(report['orders_sent'], 0)



if __name__ == '__main__':
    unittest.main()
