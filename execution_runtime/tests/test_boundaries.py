"""Executable owner boundaries and negative fixtures; no runtime SDK discovery."""

import ast
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tomllib
import unittest
from unittest.mock import patch

from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, command


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("execution_runtime_checker", ROOT / "scripts/check-architecture.py")
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)
CONSTRAINTS = ROOT / "architecture/execution-runtime-constraints.toml"
DEBT = ROOT / "architecture/execution-runtime-debt.toml"


class BoundaryTests(unittest.TestCase):
    def test_runtime_and_original_manifests_have_no_new_debt(self):
        for constraints, debt in ((CONSTRAINTS, DEBT),
                (ROOT / "architecture/execution-constraints.toml", ROOT / "architecture/execution-debt.toml"),
                (ROOT / "architecture/execution-simulation-constraints.toml", ROOT / "architecture/execution-simulation-debt.toml")):
            with self.subTest(manifest=constraints.name):
                result = CHECKER.evaluate(ROOT, constraints_path=constraints, debt_path=debt)
                self.assertTrue(result.passed, result.violations)
                self.assertFalse(result.debt)

    def test_negative_owner_imports_and_calls(self):
        for target, source in (("execution_runtime/application.py", "runtime._submit_engine(command)"),
                               ("execution_runtime/application.py", "runtime._claim_command(con, command, {})"),
                               ("execution_runtime/strategy.py", "db.connect()"),
                               ("execution_runtime/strategy.py", "from execution_runtime.storage import Journal"),
                               ("execution_runtime/kgi.py", "from execution_runtime.strategy import StrategyRules"),
                               ("execution_runtime/cli.py", "runtime.submit(command)"),
                               ("execution_runtime/review.py", "db.connect()"),
                               ("execution_runtime/application.py", "import execution_runtime.storage"),
                               ("execution_runtime/bad.py", "import kgisuperpy"),
                               ("execution_runtime/bad.py", "import execution_simulation.application"),
                               ("execution_runtime/bad.py", "api.login('x')"),
                               ("execution_runtime/native.py", "import backend.app"),
                               ("execution_runtime/native.py", "import personal_asset_os"),
                               ("execution_runtime/native.py", "api.Order.create_order()"),
                               ("execution_runtime/runtime.py", "api.Account.InventorySum('B')"),
                               ("execution_runtime/headless.py", "runtime._submit_engine(command)"),
                               ("execution_runtime/bad.py", "api.Order.cancel_order_all()"),
                               ("execution_runtime/kgi.py", "db.commit()"),
                               ("execution_runtime/storage.py", "reduce_order(x)"),
                               ("backend/app/bad.py", "from execution_runtime.runtime import ExecutionRuntime"),
                               ("execution/bad.py", "import execution_runtime")):
            with self.subTest(target=target, source=source), TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
                root = Path(directory)
                for rule in tomllib.loads(CONSTRAINTS.read_text(encoding="utf-8"))["rules"]:
                    for relative in rule["roots"]:
                        path = root / relative
                        if path.suffix == ".py":
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.touch()
                        else:
                            path.mkdir(parents=True, exist_ok=True)
                (root / target).write_text(source, encoding="utf-8")
                result = CHECKER.evaluate(root, constraints_path=CONSTRAINTS, debt_path=DEBT)
                self.assertFalse(result.passed)

    def test_only_runtime_calls_shared_reducer_and_only_adapter_calls_sdk(self):
        for path in (ROOT / "execution_runtime").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                if name == "reduce_order":
                    self.assertEqual(path.name, "runtime.py")
                if name in {"create_order", "cancel_order", "get_trades", "set_event"}:
                    self.assertEqual(path.name, "kgi.py")

    def test_fake_vertical_slice_has_zero_network_or_native_sdk_import(self):
        with TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory, ExitStack() as stack:
            for target in ("socket.socket", "socket.create_connection", "urllib.request.urlopen"):
                stack.enter_context(patch(target, side_effect=AssertionError("external IO forbidden")))
            sdk = FakeSession()
            with ExecutionRuntime(Path(directory) / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
                                  session_factory=sdk.binding, clock=lambda: NOW) as runtime:
                runtime._submit_engine(command())
                runtime.reconcile()
                self.assertTrue(runtime.verify())
            self.assertFalse(any(name == "kgisuperpy" or name.startswith("kgisuperpy.") for name in sys.modules))


if __name__ == "__main__":
    unittest.main()
