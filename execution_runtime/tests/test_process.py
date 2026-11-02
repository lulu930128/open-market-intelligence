"""Real process exit/reopen, SQLite rollback and cross-process lifetime ownership."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession


ROOT = Path(__file__).resolve().parents[2]


class ProcessTests(unittest.TestCase):
    def run_worker(self, directory, mode, stage="none"):
        # No credentials/SDK settings are inherited by fixture children.
        environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
        return subprocess.run([sys.executable, "-B", "-m", "execution_runtime.tests.process_worker",
                               str(directory), mode, stage], cwd=ROOT, env=environment,
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def test_crash_windows_have_no_automatic_second_attempt(self):
        for stage, expected_attempts, known_id in (
                ("after_claim", 0, False), ("after_effect", 1, False), ("after_binding", 1, True)):
            with self.subTest(stage=stage), TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
                crashed = self.run_worker(directory, "crash", stage)
                self.assertEqual(crashed.returncode, 73, crashed.stderr)
                recovered = self.run_worker(directory, "recover")
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                result = json.loads(recovered.stdout)
                self.assertEqual(result["attempts"], expected_attempts)
                self.assertTrue(result["verified"])
                self.assertEqual(bool(result["result"]["broker_order_id"]), known_id)
                if known_id:
                    self.assertEqual(result["result"]["state"], "CANCELLED")
                    self.assertEqual(result["result"]["filled_shares"], 3)
                    self.assertFalse(result["result"]["reconcile_required"])
                    self.assertEqual(result["cancels"], 1)
                else:
                    self.assertEqual(result["result"]["state"], "UNKNOWN")
                    self.assertEqual(result["cancels"], 0)
                    self.assertEqual(len(result["external"]), expected_attempts)

    def test_crash_before_claim_commit_rolls_back_entire_intent(self):
        with TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
            crashed = self.run_worker(directory, "crash", "before_claim_commit")
            self.assertEqual(crashed.returncode, 73, crashed.stderr)
            recovered = self.run_worker(directory, "recover")
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            result = json.loads(recovered.stdout)
            self.assertEqual(result["attempts"], 1)
            self.assertTrue(result["verified"])

    def test_second_process_cannot_start_another_session(self):
        with TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
            sdk = FakeSession()
            with ExecutionRuntime(Path(directory) / "execution.sqlite", account_id=ACCOUNT, trade_date=DAY,
                                  session_factory=sdk.binding, clock=lambda: NOW):
                child = self.run_worker(directory, "recover")
                self.assertEqual(child.returncode, 2, child.stderr)
                self.assertEqual(json.loads(child.stdout)["error"], "EXECUTION_OWNER_ALREADY_ACTIVE")

    def test_cancel_crash_does_not_repeat_effect(self):
        for stage, count in (("after_cancel_claim", 0), ("after_cancel_effect", 1)):
            with self.subTest(stage=stage), TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
                child = self.run_worker(directory, "cancel", stage)
                self.assertEqual(child.returncode, 73, child.stderr)
                recovered = self.run_worker(directory, "recover")
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                result = json.loads(recovered.stdout)
                self.assertEqual(result["attempts"], 1)
                self.assertEqual(result["cancels"], count)
                self.assertEqual(result["result"]["filled_shares"], 3)
                self.assertTrue(result["verified"])


if __name__ == "__main__":
    unittest.main()
