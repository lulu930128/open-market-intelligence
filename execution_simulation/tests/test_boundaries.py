"""Additive M2 guard and injected negative cases; M1 manifests remain unchanged."""

import ast
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('m2a_architecture_checker', ROOT / 'scripts/check-architecture.py')
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)
CONSTRAINTS = ROOT / 'architecture/execution-simulation-constraints.toml'
DEBT = ROOT / 'architecture/execution-simulation-debt.toml'


class Boundaries(unittest.TestCase):
    def test_m2_manifest_has_no_debt(self):
        result = CHECKER.evaluate(ROOT, constraints_path=CONSTRAINTS, debt_path=DEBT)
        self.assertTrue(result.passed, result.violations)
        self.assertFalse(result.debt)

    def test_negative_imports_and_production_callers(self):
        for path, source in (
            ('execution_simulation/bad.py', 'import socket'),
            ('execution_simulation/bad.py', 'from app.market.providers import kgi'),
            ('execution_simulation/bad.py', 'import kgisuperpy'),
            ('execution_simulation/bad.py', 'import paos'),
            ('execution_simulation/bad.py', 'import fastapi'),
            ('execution_simulation/bad.py', 'import subprocess'),
            ('backend/app/bad.py', 'from execution_simulation import SimulationApplication'),
            ('agents/bad.py', 'import execution_simulation'),
            ('scripts/bad.py', 'import execution_simulation'),
            ('execution/bad.py', 'import execution_simulation'),
        ):
            with self.subTest(path=path, source=source), TemporaryDirectory(prefix='omi-m2-guard-') as directory:
                root = Path(directory)
                for rule in tomllib.loads(CONSTRAINTS.read_text(encoding='utf-8'))['rules']:
                    for declared_root in rule['roots']:
                        (root / declared_root).mkdir(parents=True, exist_ok=True)
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding='utf-8')
                result = CHECKER.evaluate(root, constraints_path=CONSTRAINTS, debt_path=DEBT)
                self.assertFalse(result.passed)
                self.assertTrue(result.violations)

    def test_only_one_sandbox_factory_and_no_live_switch_or_listener(self):
        source = (ROOT / 'execution_simulation/storage.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        self.assertEqual(sum(isinstance(n, ast.FunctionDef) and n.name == 'temporary_sandbox'
                             for n in ast.walk(tree)), 1)
        for path in (ROOT / 'execution_simulation').glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Name, ast.Attribute)):
                    name = node.id if isinstance(node, ast.Name) else node.attr
                    self.assertNotIn(name.lower(), {'live_enable', 'enable_live', 'listen', 'serve_forever'})
