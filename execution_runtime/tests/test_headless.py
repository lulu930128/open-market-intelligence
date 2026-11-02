"""One real application/runtime/journal with existing isolated SDK fixtures."""

from dataclasses import asdict
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from execution_runtime.application import ExecutionApplication
from execution_runtime.headless import MAX_LINE, dispatch, serve
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.review import Draft
from execution_runtime.native import NativeSessionFactory
from execution_runtime.storage import OwnerLease
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, command
from .test_native import SETTINGS, sdk_fixture


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.sdk = FakeSession(callback_before_return=True)
        self.lease = OwnerLease(Path(self.directory.name) / "native-session")
        self.lease.acquire()
        self.addCleanup(self.lease.release)
        self.native_sdk, self.native_api = sdk_fixture(self.sdk)
        factory = NativeSessionFactory(SETTINGS, owner_lease=self.lease,
            sdk_loader=lambda: self.native_sdk, current_day=lambda: DAY)
        factory.prepare()
        self.runtime = ExecutionRuntime(Path(self.directory.name) / "journal.sqlite",
            account_id=ACCOUNT, trade_date=DAY, session_factory=factory,
            clock=lambda: NOW, strategy_effects=False)
        self.runtime.start()
        self.addCleanup(self.runtime.close)
        self.app = ExecutionApplication(self.runtime)

    def call(self, *argv):
        return dispatch(self.app, {"id": "transport-id", "argv": list(argv)}, selected_account=ACCOUNT)["result"]

    def preview(self, space="USER_SPACE", *, strategy=False):
        draft = Draft(command(account_id="SELECTED", request_id="request-" + space, intent_id="intent-" + space,
            space_id=space, strategy_id="strategy-1" if strategy else None, revision=1 if strategy else None),
            "fixture-owner", "MANUAL" if space == "USER_SPACE" else "AGENT_PROPOSAL")
        result = self.call("draft", "--draft-json", json.dumps(asdict(draft)))
        return self.call("preview", result["review_id"], "--expected-revision", "1")

    def confirm(self, preview):
        return self.call("confirm", preview["review_id"], "--expected-revision", "1",
                         "--expected-digest", preview["snapshot"]["digest"])

    def test_dual_space_lineage_same_engine_only_exact_confirm_sends_once(self):
        for space in ("USER_SPACE", "AGENT_SPACE"):
            preview = self.preview(space)
            count = len(self.sdk.broker.attempts)
            self.assertEqual(preview["state"], "PREVIEW")
            self.assertEqual(preview["draft"]["command"]["account_id"], "SELECTED")
            self.assertNotIn(ACCOUNT, json.dumps(preview))
            self.assertNotIn("audit", preview)
            with self.assertRaisesRegex(ValueError, "REVIEW_DIGEST_MISMATCH"):
                self.call("confirm", preview["review_id"], "--expected-revision", "1", "--expected-digest", "0" * 64)
            self.assertEqual(len(self.sdk.broker.attempts), count)
            result = self.confirm(preview)
            self.confirm(preview)
            self.assertEqual(len(self.sdk.broker.attempts), count + 1)
            self.assertEqual(result["execution"]["space_id"], space)
            self.assertEqual(result["execution"]["request_id"], "request-" + space)
        self.assertEqual(len(self.app.list()), 2)
        self.assertTrue(self.runtime.verify())

    def test_query_and_exact_cancel_use_existing_runtime(self):
        result = self.confirm(self.preview())
        receipt = result["execution"]
        args = ["cancel", "--execution-id", result["execution_id"], "--account-id", "SELECTED",
                "--trade-date", DAY, "--broker-order-id", receipt["broker_order_id"]]
        with self.assertRaisesRegex(ValueError, "EXACT_CANCEL_IDENTITY_REQUIRED"):
            self.call(*args[:-1], "wrong-id")
        self.assertEqual(self.sdk.broker.cancels, [])
        self.call(*args)
        self.call(*args)
        count = self.sdk.query_count
        self.call("query")
        self.call("query")
        self.assertEqual(self.sdk.query_count, count + 2)
        self.assertEqual(len(self.sdk.broker.cancels), 1)
        self.assertEqual(self.call("status", result["review_id"])["execution"]["state"], "CANCELLED")

    def test_unknown_confirm_is_not_resent(self):
        self.sdk.submit_mode = "error_after"
        preview = self.preview()
        self.assertEqual(self.confirm(preview)["execution"]["state"], "UNKNOWN")
        self.confirm(preview)
        self.call("query")
        self.confirm(preview)
        self.assertEqual(len(self.sdk.broker.attempts), 1)

    def test_strategy_cli_revises_after_submit_without_rewriting_confirmed_command(self):
        preview = self.preview(strategy=True)
        self.confirm(preview)
        source = json.dumps({"source_id": "fixture-plan", "observed_at": NOW.isoformat(), "content": {"fixture": True}})
        rules = json.dumps({"stop_loss": "45", "take_profit": "55", "exit_limit_price": "45"})
        self.call("strategy-create", preview["review_id"], "--expected-digest", preview["snapshot"]["digest"],
                  "--rules-json", rules, "--source-json", source)
        rules = json.dumps({"stop_loss": "44", "take_profit": "56", "exit_limit_price": "44"})
        result = self.call("strategy-revise", "strategy-1", "--request-id", "strategy-adjust-1", "--expected-revision", "1",
                           "--rules-json", rules, "--source-json", source)
        self.assertEqual(result["strategy_revision"], 2)
        self.assertEqual(self.call("strategy-status", "strategy-1")["rules"]["stop_loss"], "44")
        self.assertEqual(self.call("status", preview["review_id"])["snapshot"], preview["snapshot"])
        self.assertEqual(len(self.sdk.broker.attempts), 1)

    def test_persistent_protocol_recovers_from_bad_input_without_echoing_it(self):
        bad = 'sanitized-private-input'
        lines = [bad, '{"id":"duplicate","id":"again","argv":["list"]}',
                 json.dumps({"id": "malformed", "argv": ["submit", bad]}),
                 json.dumps({"id": "help", "argv": ["--help"]}),
                 json.dumps({"id": "read-1", "argv": ["list"]})]
        output = io.StringIO()
        serve(self.app, io.StringIO("\n".join(lines) + "\n"), output, selected_account=ACCOUNT)
        self.assertNotIn(bad, output.getvalue())
        results = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["ok"] for r in results], [False, False, False, False, True])
        self.assertEqual(self.sdk.broker.attempts, [])

    def test_oversized_protocol_stops_instead_of_parsing_suffix(self):
        output = io.StringIO()
        serve(self.app, io.StringIO("x" * (MAX_LINE + 2) + '\n{"id":"next","argv":["list"]}\n'),
              output, selected_account=ACCOUNT)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "PROTOCOL_LINE_TOO_LARGE")

    def test_account_alias_and_unknown_arguments_fail_before_effect(self):
        draft = asdict(Draft(command(), "fixture-owner", "MANUAL"))
        with self.assertRaisesRegex(ValueError, "SELECTED_ACCOUNT_ALIAS_REQUIRED"):
            self.call("draft", "--draft-json", json.dumps(draft))
        for argv in (("submit",), ("draft", "--draft-json", "{}"), ("cancel-all",), ("query", "--fake")):
            with self.assertRaises(ValueError):
                self.call(*argv)
        self.assertEqual(self.sdk.broker.attempts, [])


if __name__ == "__main__":
    unittest.main()
