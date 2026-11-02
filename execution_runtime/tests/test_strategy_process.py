"""Crash uncertainty and durable quantity reservations across actual processes."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]


class StrategyProcessTests(unittest.TestCase):
    def worker(self, directory, mode, stage="none"):
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
        return subprocess.run([sys.executable, "-B", "-m", "execution_runtime.tests.strategy_process_worker",
                               str(directory), mode, stage], cwd=ROOT, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=25)

    def success(self, directory, mode):
        result = self.worker(directory, mode)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["verified"])
        return value

    def test_atomic_target_claim_crash_reopen_and_unknown_never_replayed(self):
        cases = (("before_strategy_target_commit", 1, 0),
                 ("after_strategy_target_commit", 2, 60),
                 ("before_strategy_exit_claim_commit", 2, 60),
                 ("after_cancel_claim", 1, 60),
                 ("after_cancel_effect", 1, 60),
                 ("after_claim", 1, 60), ("after_effect", 2, 60), ("after_binding", 2, 60))
        for stage, attempts, reserved in cases:
            with self.subTest(stage=stage), TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
                original = self.success(directory, "prepare")["result"]
                crashed = self.worker(directory, "exit", stage)
                self.assertEqual(crashed.returncode, 73, crashed.stderr)
                reopened = self.success(directory, "inspect")
                self.assertEqual(reopened["attempts"], attempts)
                self.assertEqual(reopened["result"]["reserved_exit_quantity"], reserved)
                self.assertEqual(reopened["result"]["entry_execution_id"], original["entry_execution_id"])
                self.assertEqual(reopened["result"]["review_digest"], original["review_digest"])
                again = self.success(directory, "inspect")
                self.assertEqual(again["attempts"], attempts)
                if stage in {"after_claim", "after_effect", "after_cancel_claim", "after_cancel_effect"}:
                    child = again["result"]["exits"][0]
                    self.assertEqual(child["state"], "UNKNOWN")
                    self.assertIsNone(child["broker_order_id"])
                    repeated = self.success(directory, "exit")
                    self.assertEqual(repeated["attempts"], attempts)
                    late = self.success(directory, "late")
                    self.assertEqual([e["quantity"] for e in late["result"]["exits"]], [60, 15])
                    self.assertEqual(late["attempts"], attempts + 1)
                    self.assertEqual(self.success(directory, "inspect")["attempts"], attempts + 1)


if __name__ == "__main__":
    unittest.main()
