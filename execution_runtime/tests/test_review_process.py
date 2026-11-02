"""Actual child-process crash windows and separate CLI invocations."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from execution_runtime.review import Draft
from .fake_sdk import ACCOUNT, DAY, command


ROOT = Path(__file__).resolve().parents[2]


class ReviewProcessTests(unittest.TestCase):
    def child(self, module, argv):
        environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
        return subprocess.run([sys.executable, "-B", "-m", module, *argv], cwd=ROOT, env=environment,
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def worker(self, directory, mode, stage="none"):
        return self.child("execution_runtime.tests.review_process_worker", [str(directory), mode, stage])

    def test_confirmation_crash_windows_reopen_without_any_implicit_send(self):
        for stage, attempts, state in (("before_confirmation_commit", 0, "PREVIEW"),
                ("after_confirmation", 0, "CONFIRMED"), ("before_claim_commit", 0, "CONFIRMED"),
                ("after_claim", 0, "EXECUTION"), ("after_effect", 1, "EXECUTION"),
                ("after_binding", 1, "EXECUTION")):
            with self.subTest(stage=stage), TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
                prepared = self.worker(directory, "prepare")
                self.assertEqual(prepared.returncode, 0, prepared.stderr)
                snapshot = json.loads(prepared.stdout)["result"]["snapshot"]
                crashed = self.worker(directory, "confirm", stage)
                self.assertEqual(crashed.returncode, 73, crashed.stderr)
                reopened = self.worker(directory, "inspect")
                self.assertEqual(reopened.returncode, 0, reopened.stderr)
                result = json.loads(reopened.stdout)
                self.assertEqual((result["attempts"], result["result"]["state"]), (attempts, state))
                self.assertEqual(result["result"]["snapshot"], snapshot)
                self.assertTrue(result["verified"])
                resumed = self.worker(directory, "confirm")
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                result = json.loads(resumed.stdout)
                self.assertEqual(result["attempts"], 0 if stage == "after_claim" else 1)
                self.assertTrue(result["verified"])
                if stage in {"after_claim", "after_effect"}:
                    self.assertEqual(result["result"]["execution"]["state"], "UNKNOWN")
                    self.assertIsNone(result["result"]["execution"]["broker_order_id"])
                elif stage == "after_binding":
                    self.assertEqual(result["result"]["execution"]["broker_order_id"], "O0001")
                again = self.worker(directory, "confirm")
                self.assertEqual(again.returncode, 0, again.stderr)
                self.assertEqual(json.loads(again.stdout)["attempts"], result["attempts"])

    def test_fake_cli_full_lifecycle_in_separate_processes(self):
        with TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
            def cli(*args, expected_code=0):
                child = self.child("execution_runtime.tests.review_cli", ["--directory", directory, *args])
                self.assertEqual(child.returncode, expected_code, child.stderr)
                return json.loads(child.stdout)
            draft = Draft(command(), "fixture-user", "MANUAL")
            created = cli("draft", "--draft-json", json.dumps(asdict(draft)))
            rid = created["result"]["review_id"]
            first = cli("preview", rid, "--expected-revision", "1")["result"]
            changed = asdict(draft)
            changed["command"]["price"] = "51"
            cli("revise", rid, "--expected-revision", "1", "--draft-json", json.dumps(changed))
            self.assertEqual(cli("confirm", rid, "--expected-revision", "1", "--expected-digest",
                                 first["snapshot"]["digest"], expected_code=2)["error"], "STALE_REVIEW_REVISION")
            second = cli("preview", rid, "--expected-revision", "2")["result"]
            self.assertEqual(cli("status", rid)["result"]["snapshot"], second["snapshot"])
            result = cli("confirm", rid, "--expected-revision", "2", "--expected-digest", second["snapshot"]["digest"])
            self.assertEqual(result["fake_submit_attempts"], 1)
            value = result["result"]
            cli("query")
            cancelled = cli("cancel", "--execution-id", value["execution_id"], "--account-id", ACCOUNT,
                            "--trade-date", DAY, "--broker-order-id", value["execution"]["broker_order_id"])
            self.assertEqual(cancelled["fake_exact_cancels"], ["O0001"])
            self.assertEqual(cli("status", rid)["result"]["execution"]["broker_order_id"], "O0001")
            other = asdict(Draft(command(request_id="reject", intent_id="reject"), "fixture-agent", "AGENT_PROPOSAL"))
            other["command"]["space_id"] = "AGENT_SPACE"
            rejected_id = cli("draft", "--draft-json", json.dumps(other))["result"]["review_id"]
            cli("reject", rejected_id, "--expected-revision", "1")
            listed = cli("list")
            self.assertEqual({item["state"] for item in listed["result"]}, {"EXECUTION", "REJECTED"})
            self.assertEqual(listed["fake_submit_attempts"], 1)
            self.assertTrue(listed["journal_verified"])

    def test_fake_cli_rejects_unmarked_nonempty_directory_before_open(self):
        with TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
            sentinel = Path(directory) / "sentinel.txt"
            sentinel.write_bytes(b"preserve")
            child = self.child("execution_runtime.tests.review_cli", ["--directory", directory, "list"])
            self.assertEqual(child.returncode, 2, child.stderr)
            self.assertEqual(json.loads(child.stdout)["error"], "FAKE_FIXTURE_DIRECTORY_NOT_EMPTY")
            self.assertEqual(sentinel.read_bytes(), b"preserve")
            self.assertFalse((Path(directory) / "fake-review.sqlite").exists())

    def test_fake_cli_has_no_raw_submit_or_incomplete_confirm_route(self):
        for args in (["submit"], ["confirm", "unknown", "--expected-revision", "1"]):
            with self.subTest(args=args), TemporaryDirectory(dir=ROOT / "execution_runtime/tests") as directory:
                child = self.child("execution_runtime.tests.review_cli", ["--directory", directory, *args])
                self.assertEqual(child.returncode, 2)
                self.assertFalse(any(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
