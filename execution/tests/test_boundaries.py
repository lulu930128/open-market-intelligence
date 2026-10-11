"""Negative architecture checks. File reads belong to tests, never to the domain."""

import ast
from contextlib import ExitStack
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from execution.contracts import EventKind, SimulationEvent
from execution.tests.fixtures import NOW, confirmation, fixture, service


ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "execution"
SAFE_IMPORTS = {"dataclasses", "datetime", "decimal", "enum", "hashlib", "hmac", "json"}
LOCAL_MODULES = {p.stem for p in DOMAIN.glob("*.py")}
FORBIDDEN_CALLS = {
    "open", "exec", "eval", "compile", "__import__", "input", "print", "import_module",
    "connect", "commit", "rollback", "flush", "now", "utcnow", "today", "sleep", "Popen", "system",
}
ROUTE = re.compile(r"(?:^|/)(?:execution|manual-execution|manual-trading|orders)(?:/|$)", re.I)


def domain_violations(source):
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            violations.extend(alias.name for alias in node.names if alias.name not in SAFE_IMPORTS)
        elif isinstance(node, ast.ImportFrom):
            allowed = (node.level == 1 and node.module in LOCAL_MODULES) or (
                node.level == 0 and node.module in SAFE_IMPORTS)
            if not allowed or any(alias.name == "*" for alias in node.names):
                violations.append("import:" + str(node.module))
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else "")
            if name in FORBIDDEN_CALLS:
                violations.append("call:" + name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and ROUTE.search(node.value):
            violations.append("route:" + node.value)
    return violations


def consumer_violations(source):
    violations = []
    for node in ast.walk(ast.parse(source)):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        if any(module == "execution" or module.startswith("execution.") for module in modules):
            violations.append("execution-import")
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else "")
            if name in {"__import__", "import_module"} and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if argument.value == "execution" or argument.value.startswith("execution."):
                        violations.append("execution-dynamic-import")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("/") and ROUTE.search(node.value):
                violations.append("execution-route")
    return violations


class BoundaryTests(unittest.TestCase):
    def test_domain_only_imports_reviewed_pure_stdlib_and_local_modules(self):
        for path in DOMAIN.rglob("*.py"):
            if "tests" not in path.relative_to(DOMAIN).parts:
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertEqual(domain_violations(path.read_text(encoding="utf-8")), [])

    def test_negative_import_guard_detects_prohibited_dependencies(self):
        for module in ("app.market.providers", "app.ai", "app.portfolio", "paos",
                       "kgi_broker_bridge", "kgisuperpy", "socket", "os", "pathlib",
                       "subprocess", "sqlite3", "requests", "fastapi", "importlib"):
            with self.subTest(module=module):
                self.assertTrue(domain_violations(f"import {module}"))
                self.assertTrue(domain_violations(f"from {module} import x"))
        for source in ("__import__('socket')", "eval('1')", "open('x')", "datetime.now()",
                       "from .tests.fixtures import fixture", "from .contracts import *"):
            self.assertTrue(domain_violations(source))

    def test_production_has_no_execution_imports_or_routes(self):
        for directory in (ROOT / "backend/app", ROOT / "agents"):
            for path in directory.rglob("*.py"):
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertEqual(consumer_violations(path.read_text(encoding="utf-8-sig")), [])
        for path in (ROOT / "frontend/src").rglob("*"):
            if path.suffix in {".ts", ".tsx"}:
                source = path.read_text(encoding="utf-8-sig")
                self.assertIsNone(re.search(r"/api/(?:execution|manual-execution|manual-trading|orders)(?:/|[\"'`])", source), str(path))

    def test_negative_route_and_dynamic_consumer_guards(self):
        for source in ("import execution", "from execution.service import OfflineExecution",
                       "__import__('execution.service')", "importlib.import_module('execution.service')",
                       "@router.post('/api/execution/confirm')\ndef x(): pass",
                       "@router.post('/api/orders')\ndef x(): pass"):
            self.assertTrue(consumer_violations(source), source)
        self.assertEqual(consumer_violations("from app.ai.ask_execution import x"), [])
        self.assertEqual(consumer_violations("schema = {'execution': 'execution.trace'}"), [])

    def test_no_runtime_entrypoint_or_packaged_executable(self):
        for name in ("__main__.py", "main.py", "server.py", "routes.py", "router.py", "cli.py",
                     "pyproject.toml", "setup.py"):
            self.assertFalse((DOMAIN / name).exists(), name)

    def test_workflow_does_not_attempt_external_io(self):
        # Imports for patched stdlib modules happen in the harness before all patches are active.
        targets = ("builtins.open", "pathlib.Path.open", "socket.socket", "socket.create_connection",
                   "sqlite3.connect", "subprocess.Popen", "urllib.request.urlopen")
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(target, side_effect=AssertionError("IO forbidden")))
                     for target in targets]
            current = service()
            draft, evidence = fixture()
            preview = current.preview(draft, evidence, now=NOW)
            current.confirm(preview, confirmation(preview), now=NOW)
            current.apply(SimulationEvent("fixture-accepted", preview.preview_id, EventKind.ACCEPTED,
                                          NOW, 1), now=NOW)
            current.result(preview.preview_id)
            for mock in mocks:
                mock.assert_not_called()
