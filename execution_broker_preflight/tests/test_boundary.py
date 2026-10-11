import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "execution_broker_preflight"


class BoundaryTests(unittest.TestCase):
    def test_offline_guard_denies_simulated_io_attempts(self):
        from execution_broker_preflight.tests.run_offline import offline_guard
        for name, args in (("import", ("kgisuperpy",)), ("import", ("paos",)),
                           ("import", ("sqlite3",)), ("import", ("execution",)),
                           ("socket.connect", ()), ("subprocess.Popen", ()),
                           ("sqlite3.connect", ()), ("open", ("FAKE_FILE", "w", 0))):
            with self.subTest(name=name, args=args), self.assertRaises(RuntimeError):
                offline_guard(name, args)

    def test_pure_modules_use_only_allowlisted_imports_and_no_io_calls(self):
        allowed = {"dataclasses", "datetime", "decimal", "enum", "contracts"}
        forbidden_calls = {"open", "exec", "eval", "compile", "__import__", "input", "print",
                           "getattr_dynamic", "now", "today", "utcnow", "login", "create_order",
                           "cancel_order", "get_trades", "connect", "import_module"}
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name, allowed, str(path))
                if isinstance(node, ast.ImportFrom):
                    self.assertIn(node.module, allowed, str(path))
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    self.assertNotIn(name, forbidden_calls, str(path))

    def test_no_production_import_of_new_package(self):
        for folder in ("backend/app", "agents", "scripts", "execution", "execution_simulation"):
            for path in (ROOT / folder).rglob("*.py"):
                source = path.read_text(encoding="utf-8-sig")
                if "execution_broker_preflight" not in source:
                    continue
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Import):
                        self.assertFalse(any(a.name.startswith("execution_broker_preflight") for a in node.names), str(path))
                    elif isinstance(node, ast.ImportFrom):
                        self.assertFalse((node.module or "").startswith("execution_broker_preflight"), str(path))

    def test_bridge_remains_read_only_without_importing_it(self):
        path = ROOT / "backend/app/market/providers/kgi_superpy_bridge.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_handle")
        actions = {n.value for node in ast.walk(handler) if isinstance(node, ast.Compare)
                   for n in node.comparators if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertEqual(actions, {"subscribe", "unsubscribe", "status", "data_get", "portfolio_get", "shutdown"})


if __name__ == "__main__":
    unittest.main()
