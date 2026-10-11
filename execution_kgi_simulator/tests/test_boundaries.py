import ast
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('sim_qualification_guard', ROOT / 'scripts/check-architecture.py')
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)
CONSTRAINTS = ROOT / 'execution_kgi_simulator/constraints.toml'
DEBT = ROOT / 'execution_kgi_simulator/debt.toml'


class Guard(unittest.TestCase):
    def test_no_debt_and_injected_boundary_violations(self):
        result = CHECKER.evaluate(ROOT, constraints_path=CONSTRAINTS, debt_path=DEBT)
        self.assertTrue(result.passed, result.violations)
        self.assertFalse(result.debt)
        for path, source in [('execution_kgi_simulator/bad.py', 'import kgisuperpy'),
                             ('execution_kgi_simulator/bad.py', 'import sqlite3'),
                             ('execution_kgi_simulator/bad.py', 'transition(order, event, now)'),
                             ('execution_kgi_simulator/bad.py', 'import execution_manual_mock'),
                             ('backend/app/bad.py', 'import execution_kgi_simulator'),
                             ('agents/bad.py', 'import execution_kgi_simulator'),
                             ('execution_simulation/bad.py', 'import execution_kgi_simulator')]:
            with self.subTest(path=path), TemporaryDirectory() as temp:
                root = Path(temp)
                for rule in tomllib.loads(CONSTRAINTS.read_text())['rules']:
                    for name in rule['roots']:
                        (root / name).mkdir(parents=True, exist_ok=True)
                (root / path).write_text(source)
                self.assertFalse(CHECKER.evaluate(root, constraints_path=CONSTRAINTS, debt_path=DEBT).passed)

    def test_no_production_switch_or_credential_value_lookup_in_python(self):
        for path in (ROOT / 'execution_kgi_simulator').glob('*.py'):
            tree = ast.parse(path.read_text())
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            self.assertFalse(names & {'getenv', 'environ', 'load_dotenv', 'subscribe', 'connect'})
        source = (ROOT / 'scripts/test-kgi-official-simulator.ps1').read_text()
        self.assertNotIn('KGI_SUPERPY_', source)
        self.assertIn('$childEnvironment.Clear()', source)
        self.assertIn('CreateNoWindow = $true', source)

    def test_offline_audit_hook_blocks_network_native_sdk(self):
        # Isolated subprocess is required: audit hooks cannot be removed.
        import subprocess
        script = '''import sys
from execution_kgi_simulator.worker import offline_guard
sys.addaudithook(offline_guard)
count = 0
for event, args in [('socket.connect', (None, None)), ('ctypes.dlopen', ('fixture',)), ('import', ('kgisuperpy',))]:
    try: sys.audit(event, *args)
    except RuntimeError: count += 1
assert count == 3
'''
        child = subprocess.run([sys.executable, '-B', '-S', '-c', script], cwd=ROOT,
                               capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
