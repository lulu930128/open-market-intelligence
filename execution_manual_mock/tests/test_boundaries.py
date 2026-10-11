import ast
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('manual_checker', ROOT / 'scripts/check-architecture.py')
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)
CONSTRAINTS = ROOT / 'execution_manual_mock/constraints.toml'
DEBT = ROOT / 'execution_manual_mock/debt.toml'


class Boundary(unittest.TestCase):
    def test_manifest_no_debt_and_negative_injections(self):
        result = CHECKER.evaluate(ROOT, constraints_path=CONSTRAINTS, debt_path=DEBT)
        self.assertTrue(result.passed, result.violations)
        self.assertFalse(result.debt)
        for path, source in [('execution_manual_mock/bad.py', 'import kgisuperpy'),
                ('execution_manual_mock/bad.py', 'import execution_broker_preflight'),
                ('execution_manual_mock/bad.py', 'import sqlite3'),
                ('execution_manual_mock/bad.py', 'assess(draft, evidence, now)'),
                ('backend/app/bad.py', 'import execution_manual_mock'),
                ('agents/bad.py', 'import execution_manual_mock')]:
            with self.subTest(path=path, source=source), TemporaryDirectory() as temp:
                root = Path(temp)
                for rule in tomllib.loads(CONSTRAINTS.read_text())['rules']:
                    for name in rule['roots']:
                        target = root / name
                        (target.parent if target.suffix else target).mkdir(parents=True, exist_ok=True)
                        if target.suffix:
                            target.touch()
                (root / path).write_text(source)
                self.assertFalse(CHECKER.evaluate(root, constraints_path=CONSTRAINTS, debt_path=DEBT).passed)

    def test_loopback_literal_no_external_address_or_live_switch(self):
        source = (ROOT / 'execution_manual_mock/runtime.py').read_text()
        tree = ast.parse(source)
        binds = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'bind']
        self.assertEqual(len(binds), 1)
        self.assertEqual(ast.literal_eval(binds[0].args[0]), ('127.0.0.1', 0))
        for path in (ROOT / 'execution_manual_mock').glob('*.py'):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Name, ast.Attribute)):
                    name = node.id if isinstance(node, ast.Name) else node.attr
                    self.assertNotIn(name.lower(), {'live_enable', 'enable_live', 'load_dotenv', 'getenv'})
