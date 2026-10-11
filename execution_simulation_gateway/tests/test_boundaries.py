import ast
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tomllib
import unittest

from execution_simulation_gateway.schema import contract_schema
from execution_simulation_gateway.contracts import decode, envelope, exact_fields
from execution_simulation_gateway.security import HttpRejected
from .support import draft


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('m2b_checker', ROOT / 'scripts/check-architecture.py')
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)
CONSTRAINTS = ROOT / 'execution_simulation_gateway/constraints.toml'
DEBT = ROOT / 'execution_simulation_gateway/debt.toml'


class Boundaries(unittest.TestCase):
    def test_manifest_and_prior_guards_intact(self):
        for constraints, debt in [(CONSTRAINTS, DEBT),
                (ROOT / 'architecture/execution-constraints.toml', ROOT / 'architecture/execution-debt.toml'),
                (ROOT / 'architecture/execution-simulation-constraints.toml', ROOT / 'architecture/execution-simulation-debt.toml')]:
            result = CHECKER.evaluate(ROOT, constraints_path=constraints, debt_path=debt)
            self.assertTrue(result.passed, result.violations)
            self.assertFalse(result.debt)

    def test_injected_negative_imports_and_calls(self):
        cases = [('execution_simulation_gateway/bad.py', source) for source in (
            'import socket', 'import sqlite3', 'import os', 'import kgisuperpy', 'import paos',
            'from app.market.providers import kgi', 'import execution_broker_preflight',
            'from execution_simulation.storage import connection', 'import uvicorn',
            'from execution.validation import assess; assess(d, e, now)', 'app.dispatch("x")', '__import__("socket")')]
        cases += [(path + '/bad.py', 'import execution_simulation_gateway')
                  for path in ('backend/app', 'agents', 'scripts', 'execution', 'execution_simulation')]
        cases += [('execution_simulation_gateway/headless.py', source) for source in (
            'app.rehearsal_claim("x")', 'app.rehearsal_report("x")', 'sdk.create_order()',
            'app.set_mock_send_enabled(True)', 'app._command(now, "x")')]
        for path, source in cases:
            with self.subTest(path=path, source=source), TemporaryDirectory(prefix='omi-m2b-guard-') as temp:
                root = Path(temp)
                for rule in tomllib.loads(CONSTRAINTS.read_text(encoding='utf-8'))['rules']:
                    for folder in rule['roots']:
                        target_root = root / folder
                        (target_root.parent if target_root.suffix == '.py' else target_root).mkdir(parents=True, exist_ok=True)
                        if target_root.suffix == '.py':
                            target_root.touch(exist_ok=True)
                (root / path).write_text(source, encoding='utf-8')
                result = CHECKER.evaluate(root, constraints_path=CONSTRAINTS, debt_path=DEBT)
                self.assertFalse(result.passed)

    def test_versioned_wire_schema_and_negative_fields(self):
        schema = contract_schema()
        self.assertEqual(schema['$id'], 'urn:omi:synthetic-execution:gateway:v1')
        self.assertEqual(set(schema['$defs']['previewRequest']['required']), set(draft()))
        self.assertEqual(set(schema['$defs']['response']['required']), set(envelope('REJECTED')))
        for definition in schema['$defs'].values():
            self.assertFalse(definition['additionalProperties'])
        with self.assertRaises(HttpRejected):
            exact_fields({'user_confirmed': True, 'scenario': 'ACCEPT'}, ('user_confirmed',))
        with self.assertRaises(HttpRejected):
            decode(b'{"token":"a", "token":"b"}')

    def test_factory_only_no_global_app_no_server_or_private_owner_seam(self):
        for path in (ROOT / 'execution_simulation_gateway').glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, {'_sandbox', '_preview', '_order', '_command', 'serve_forever'})
                if isinstance(node, ast.ImportFrom) and node.module == 'execution.validation':
                    self.assertTrue(all(alias.name in {'identifier', 'instant'} for alias in node.names))
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    self.assertFalse(any(isinstance(target, ast.Name) and target.id == 'app' for target in node.targets))
