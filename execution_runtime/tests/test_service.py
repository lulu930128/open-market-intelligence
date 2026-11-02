"""Actual Windows named-pipe lifecycle with sanitized existing runtime fixtures."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from execution_runtime.application import ExecutionApplication
from execution_runtime import service, control
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession
from .test_strategy import activate, source, idle


ROOT = Path(__file__).resolve().parents[2]


class ServiceTests(unittest.TestCase):
    def test_process_lifetime_suppression_includes_native_fd_and_atexit(self):
        code = "\n".join((
            "import atexit, os, sys",
            "from execution_runtime.__main__ import private_sdk_output",
            "atexit.register(lambda: os.write(1, b'vendor teardown\\n'))",
            "with private_sdk_output(process_lifetime=True) as output:",
            "    output.write('{\"ok\":true}\\n'); output.flush()",
            "    os.write(1,b'vendor during logout\\n')",
            "os.write(1,b'vendor after context\\n')",
            "sys.__stderr__.write('vendor stderr')"))
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '{"ok":true}\n')
        self.assertEqual(result.stderr, "")

    @unittest.skipUnless(os.name == "nt", "Windows pipe acceptance")
    def test_same_user_pipe_status_query_reconnect_stop_and_informational_source_hash(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory)
            sdk = FakeSession()
            with ExecutionRuntime(path / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
                session_factory=sdk.binding, clock=lambda: NOW, strategy_effects=False) as runtime:
                app = ExecutionApplication(runtime)
                address = r"\\.\pipe\omi-test-" + uuid4().hex
                with patch.object(service, "ADDRESS", address), patch.object(control, "ADDRESS", address), \
                     patch.object(service, "source_identity", return_value="loaded-fixture") as identity:
                    errors = []
                    def worker():
                        try:
                            service.serve_runtime(runtime, app, True, path)
                        except BaseException as exc:
                            errors.append(type(exc).__name__)
                    thread = Thread(target=worker, daemon=True)
                    thread.start()
                    # The Win32 Client waits for the pipe; no fixed sleep/racy file read.
                    status = control.request_control({"operation": "status"})
                    self.assertTrue(status["ok"], status)
                    self.assertEqual(status["result"]["pid"], os.getpid())
                    identity.return_value = "edited-source"
                    status = control.request_control({"operation": "status"})
                    self.assertFalse(status["result"]["source_matches"])
                    self.assertTrue(control.request_control({"operation": "query"})["ok"])
                    self.assertTrue(control.request_control({"operation": "reconnect"})["ok"])
                    self.assertTrue(control.request_control({"operation": "stop"})["ok"])
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(errors, [])
                    self.assertEqual(sdk.broker.attempts, [])

    def test_source_change_never_blocks_exact_cancel_or_strategy_manual_exit(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            sdk = FakeSession()
            with ExecutionRuntime(Path(directory) / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
                session_factory=sdk.binding, clock=lambda: NOW) as runtime:
                app = ExecutionApplication(runtime)
                value = activate(app)
                idle(runtime)
                with patch.object(service, "source_identity", return_value="changed"):
                    for argv in (["cancel", "--execution-id", value["entry_execution_id"], "--account-id", "SELECTED",
                                  "--trade-date", DAY, "--broker-order-id", value["entry"]["broker_order_id"]],
                                 ["strategy-exit", "strategy-1", "--request-id", "manual-exit", "--expected-revision", "1",
                                  "--source-json", json.dumps({"source_id": "fixture", "observed_at": NOW.isoformat(), "content": {}})]):
                        result, stopped = service.handle(runtime, app, {"operation": "command", "request": {"id": "receipt", "argv": argv}},
                                                          simulation=True, loaded="old-source")
                        self.assertTrue(result["ok"])
                        self.assertFalse(stopped)


if __name__ == "__main__":
    unittest.main()
