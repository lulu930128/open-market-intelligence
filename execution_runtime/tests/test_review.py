"""Canonical review workflow, bypass/invalid input and immutable recovery tests."""

from contextlib import closing
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest

from execution_runtime.application import ExecutionApplication
from execution_runtime.cli import run
from execution_runtime.contracts import BrokerKey, digest
from execution_runtime.review import Draft, draft_from
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession, command


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.path = Path(self.temp.name) / "review.sqlite"
        self.broker = FakeBroker()
        self.open()

    def open(self, **kwargs):
        self.sdk = FakeSession(self.broker, **kwargs)
        self.runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
            session_factory=self.sdk.binding, clock=lambda: NOW)
        self.runtime.start()
        self.app = ExecutionApplication(self.runtime)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def draft(self, **changes):
        return Draft(command(**changes), "fixture-user", "MANUAL")

    def preview(self, draft=None):
        draft = draft or self.draft()
        self.app.draft(draft)
        return self.app.preview(draft.review_id, expected_revision=1)

    def confirm(self, preview):
        return self.app.confirm(preview["review_id"], expected_digest=preview["snapshot"]["digest"],
                                expected_revision=preview["review_revision"])

    def test_two_spaces_have_exact_snapshots_and_share_one_broker_pool(self):
        user = self.draft()
        agent = Draft(command(request_id="agent-request", intent_id="agent-intent", space_id="AGENT_SPACE",
                              strategy_id="strategy-agent", revision=7), "fixture-agent", "AGENT_PROPOSAL")
        for draft in (user, agent):
            preview = self.preview(draft)
            value = preview["snapshot"]
            self.assertEqual(value["draft"], asdict(draft))
            self.assertEqual(value["review_revision"], 1)
            self.assertEqual(value["previewed_at"], NOW.isoformat())
            self.assertEqual(value["digest"], digest({k: v for k, v in value.items() if k != "digest"}))
            self.assertEqual(value["order_semantics"], {"order_kind": "LIMIT", "time_in_force": "ROD",
                             "quantity_unit": "shares", "broker_quantity": 10})
            result = self.confirm(preview)
            self.assertEqual(result["state"], "EXECUTION")
            self.assertEqual(result["execution"]["state"], "ACCEPTED")
            self.assertEqual(result["execution"]["space_id"], draft.command.space_id)
        self.assertEqual(len(self.broker.attempts), 2)
        self.assertEqual(len(self.app.list()), 2)
        self.assertTrue(self.runtime.verify())

    def test_manual_mobile_local_strategy_provenance_is_retained(self):
        for i, source in enumerate(("MANUAL", "MOBILE", "LOCAL_STRATEGY")):
            cmd = command(request_id=f"request-{i}", intent_id=f"intent-{i}",
                          strategy_id="strategy" if source == "LOCAL_STRATEGY" else None,
                          revision=3 if source == "LOCAL_STRATEGY" else None)
            draft = Draft(cmd, "fixture-user", source)
            result = self.preview(draft)
            self.assertEqual(result["snapshot"]["draft"]["source"], source)
        self.assertEqual(self.broker.attempts, [])

    def test_common_credit_lot_units_and_native_arguments_match_review(self):
        for index, condition in enumerate(("MARGIN", "CASH_SELLING", "SHORT_SELLING")):
            draft = self.draft(request_id=f"r-{index}", intent_id=f"i-{index}", condition=condition,
                               action="Buy" if condition == "MARGIN" else "Sell", lot="Common",
                               quantity=2000, shares_per_unit=1000)
            preview = self.preview(draft)
            self.assertEqual(preview["snapshot"]["order_semantics"]["broker_quantity"], 2)
            self.confirm(preview)
            args = self.broker.attempts[-1]
            self.assertEqual((args["action"], args["symbol"], args["qty"], args["price"],
                              args["order_cond"], args["odd_lot"], args["time_in_force"]),
                             (draft.command.action, "TEST", 2, 50, condition, "Common", "ROD"))

    def test_revision_invalidates_previous_preview_and_keeps_history(self):
        draft = self.draft()
        old = self.preview(draft)
        revised = replace(draft, command=replace(draft.command, quantity=12, price="51"))
        result = self.app.revise(draft.review_id, revised, expected_revision=1)
        self.assertEqual((result["state"], result["review_revision"], result["snapshot"]), ("DRAFT", 2, None))
        with self.assertRaisesRegex(ValueError, "STALE_REVIEW_REVISION"):
            self.confirm(old)
        with self.assertRaisesRegex(ValueError, "REVIEW_NOT_CONFIRMABLE"):
            self.app.confirm(draft.review_id, expected_digest=old["snapshot"]["digest"], expected_revision=2)
        new = self.app.preview(draft.review_id, expected_revision=2)
        self.assertNotEqual(new["snapshot"]["digest"], old["snapshot"]["digest"])
        with self.assertRaisesRegex(ValueError, "REVIEW_DIGEST_MISMATCH"):
            self.app.confirm(draft.review_id, expected_digest=old["snapshot"]["digest"], expected_revision=2)
        result = self.confirm(new)
        previews = [event["payload"]["snapshot"] for event in result["audit"] if event["kind"] == "REVIEW_PREVIEWED"]
        self.assertEqual(previews, [old["snapshot"], new["snapshot"]])
        self.assertEqual(self.broker.attempts[0]["qty"], 12)
        self.assertTrue(self.runtime.verify())

    def test_rejected_draft_and_preview_cannot_be_confirmed_or_revised(self):
        for index, preview_first in enumerate((False, True)):
            draft = self.draft(request_id=f"r-{index}", intent_id=f"i-{index}")
            self.app.draft(draft)
            if preview_first:
                self.app.preview(draft.review_id, expected_revision=1)
            result = self.app.reject(draft.review_id, expected_revision=1)
            self.assertEqual(result["state"], "REJECTED")
            with self.assertRaisesRegex(ValueError, "REVIEW_NOT_CONFIRMABLE"):
                self.app.confirm(draft.review_id, expected_digest="a" * 64, expected_revision=1)
            with self.assertRaises(ValueError):
                self.app.revise(draft.review_id, draft, expected_revision=1)
            with self.assertRaisesRegex(ValueError, "CONFIRMED_REVIEW_REQUIRED"):
                self.runtime._submit_engine(draft.command)
        self.assertEqual(self.broker.attempts, [])

    def test_five_concurrent_confirms_make_one_attempt_and_one_confirmation(self):
        preview = self.preview()
        barrier, errors, results = Barrier(5), [], []
        def confirm():
            try:
                barrier.wait(timeout=5)
                results.append(self.confirm(preview))
            except Exception as exc:
                errors.append(exc)
        threads = [Thread(target=confirm) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 5)
        self.assertEqual(len(self.broker.attempts), 1)
        self.assertEqual(len({r["execution_id"] for r in results}), 1)
        audit = self.app.status(preview["review_id"])["audit"]
        for kind in ("REVIEW_CONFIRMED", "REVIEW_EXECUTION_CLAIMED"):
            self.assertEqual(sum(event["kind"] == kind for event in audit), 1)
        self.assertTrue(self.runtime.verify())

    def test_direct_submit_is_closed_and_engine_cannot_bypass_draft_or_preview(self):
        self.assertFalse(hasattr(self.app, "submit"))
        with self.assertRaisesRegex(ValueError, "CONFIRMED_REVIEW_REQUIRED"):
            self.runtime.submit(command())
        draft = self.draft()
        self.app.draft(draft)
        for preview_first in (False, True):
            if preview_first:
                self.app.preview(draft.review_id, expected_revision=1)
            with self.assertRaisesRegex(ValueError, "CONFIRMED_REVIEW_REQUIRED"):
                self.runtime._submit_engine(draft.command)
            with self.assertRaisesRegex(ValueError, "CONFIRMED_REVIEW_REQUIRED"):
                self.runtime._submit_engine(draft.command, review_id=draft.review_id)
        self.assertEqual(self.broker.attempts, [])

    def test_query_and_exact_cancel_never_reconfirm_or_change_broker_id(self):
        result = self.confirm(self.preview())
        eid, oid = result["execution_id"], result["execution"]["broker_order_id"]
        before = result["audit"]
        with self.assertRaisesRegex(ValueError, "EXACT_CANCEL_IDENTITY_REQUIRED"):
            self.app.cancel(eid, BrokerKey(ACCOUNT, DAY, "OTHER"))
        self.app.query()
        cancelled = self.app.cancel(eid, BrokerKey(ACCOUNT, DAY, oid))
        self.assertEqual(cancelled["broker_order_id"], oid)
        self.app.query()
        after = self.app.status(result["review_id"])
        self.assertEqual(after["audit"], before)
        self.assertEqual(after["execution"]["state"], "CANCELLED")
        self.assertEqual(self.broker.cancels, [oid])
        self.assertEqual(len(self.broker.attempts), 1)

    def test_preview_is_idempotent_and_local_reads_do_not_acquire_or_write(self):
        preview = self.preview()
        queries = self.sdk.query_count
        with closing(sqlite3.connect(self.path)) as con:
            count = con.execute("SELECT count(*) FROM journal").fetchone()[0]
        self.assertEqual(self.app.preview(preview["review_id"], expected_revision=1), preview)
        self.app.status(preview["review_id"])
        self.app.list()
        self.assertEqual(self.sdk.query_count, queries)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM journal").fetchone()[0], count)
            for action in ("UPDATE journal SET payload='{}'", "DELETE FROM journal"):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "IMMUTABLE_EXECUTION_FACT"):
                    con.execute(action)
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 1)
        preview["snapshot"]["draft"]["command"]["quantity"] = 900
        self.assertEqual(self.app.status(preview["review_id"])["snapshot"]["draft"]["command"]["quantity"], 10)

    def test_reopen_recovers_every_pretrade_state_and_old_snapshot(self):
        draft = self.draft()
        self.app.draft(draft)
        self.runtime.close()
        self.open()
        self.assertEqual(self.app.status(draft.review_id)["state"], "DRAFT")
        preview = self.app.preview(draft.review_id, expected_revision=1)
        self.runtime.close()
        self.open()
        self.assertEqual(self.app.status(draft.review_id)["snapshot"], preview["snapshot"])
        self.app.reject(draft.review_id, expected_revision=1)
        self.runtime.close()
        self.open()
        self.assertEqual(self.app.status(draft.review_id)["state"], "REJECTED")
        self.assertEqual(self.broker.attempts, [])

    def test_unknown_and_rejected_broker_outcomes_cannot_be_resent(self):
        for index, mode in enumerate(("error_before", "error_after", "reject", "pending")):
            self.sdk.submit_mode = mode
            preview = self.preview(self.draft(request_id=f"r-{index}", intent_id=f"i-{index}"))
            result = self.confirm(preview)
            self.assertEqual(result["execution"]["state"],
                             "REJECTED" if mode == "reject" else "PENDING" if mode == "pending" else "UNKNOWN")
            self.confirm(preview)
            with self.assertRaises(ValueError):
                self.app.revise(preview["review_id"], self.draft(), expected_revision=1)
        self.assertEqual(len(self.broker.attempts), 4)

    def test_review_and_strategy_revision_are_distinct_and_future_intents_remain_possible(self):
        draft = Draft(command(strategy_id="strategy", revision=8), "user", "LOCAL_STRATEGY")
        old = self.preview(draft)
        revised = replace(draft, command=replace(draft.command, price="51", revision=9))
        self.app.revise(draft.review_id, revised, expected_revision=1)
        new = self.app.preview(draft.review_id, expected_revision=2)
        self.assertEqual(new["snapshot"]["draft"]["command"]["revision"], 9)
        self.confirm(new)
        future = replace(revised, command=replace(revised.command, request_id="next", intent_id="next", revision=10))
        result = self.app.draft(future)
        self.assertEqual(result["state"], "DRAFT")
        self.assertEqual(len(self.broker.attempts), 1)
        self.assertEqual(self.app.status(old["review_id"])["snapshot"], new["snapshot"])

    def test_invalid_drafts_unknown_and_stale_confirmation_do_not_change_review(self):
        preview = self.preview()
        for changes in ({"quantity": True}, {"quantity": 0}, {"price": "NaN"}, {"price": "0"},
                        {"price": "50.1234567890123456789"}, {"lot": "UNKNOWN"}, {"action": "UNKNOWN"},
                        {"condition": "UNKNOWN"}, {"space_id": "UNKNOWN"}, {"shares_per_unit": 3},
                        {"revision": True}, {"strategy_id": "strategy"}, {"trade_date": "2026-1-1"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.app.revise(preview["review_id"], self.draft(**changes), expected_revision=1)
        for revision, value in ((True, "a" * 64), (0, "a" * 64), (1, "UNKNOWN"), (1, None), (2, "a" * 64)):
            with self.subTest(revision=revision, value=value), self.assertRaises(ValueError):
                self.app.confirm(preview["review_id"], expected_revision=revision, expected_digest=value)
        with self.assertRaisesRegex(ValueError, "UNKNOWN_REVIEW"):
            self.app.confirm("unknown", expected_revision=1, expected_digest="a" * 64)
        self.assertEqual(self.app.status(preview["review_id"]), preview)
        self.assertEqual(self.broker.attempts, [])

    def test_revision_cannot_reassign_owner_request_intent_space_or_strategy(self):
        draft = self.draft()
        self.preview(draft)
        candidates = [replace(draft, owner_id="other"), replace(draft, source="MOBILE")]
        for changes in ({"request_id": "other"}, {"intent_id": "other"}, {"account_id": "other"},
                        {"trade_date": "2026-10-28"}, {"strategy_id": "other", "revision": 1}):
            candidates.append(replace(draft, command=replace(draft.command, **changes)))
        for other in candidates:
            with self.subTest(draft=other), self.assertRaises(ValueError):
                self.app.revise(draft.review_id, other, expected_revision=1)
        self.assertEqual(self.app.status(draft.review_id)["review_revision"], 1)

    def test_request_alias_and_preexisting_engine_execution_cannot_be_adopted(self):
        draft = self.draft()
        self.app.draft(draft)
        for changes in ({"intent_id": "alias"}, {"request_id": "alias"}):
            with self.assertRaises(ValueError):
                self.app.draft(self.draft(**changes))
        internal = command(intent_id="internal", request_id="internal")
        self.runtime._submit_engine(internal)
        with self.assertRaisesRegex(ValueError, "IDENTITY_ALREADY_EXECUTED"):
            self.app.draft(Draft(internal, "user", "MANUAL"))
        self.assertEqual(len(self.broker.attempts), 1)

    def test_corrupt_snapshot_fails_before_session_factory(self):
        preview = self.preview()
        self.runtime.close()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("DROP TRIGGER immutable_journal_UPDATE")
            row = con.execute("SELECT seq,payload FROM journal WHERE kind='REVIEW_PREVIEWED'").fetchone()
            value = json.loads(row[1])
            value["snapshot"]["draft"]["command"]["quantity"] = 11
            con.execute("UPDATE journal SET payload=? WHERE seq=?", (json.dumps(value), row[0]))
            con.commit()
        calls = []
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
                                   session_factory=lambda: calls.append(1) or self.sdk.binding())
        with self.assertRaisesRegex(ValueError, "JOURNAL_REVIEW_SNAPSHOT_MISMATCH"):
            runtime.start()
        self.assertEqual(calls, [])
        self.assertIsNotNone(preview["snapshot"])

    def test_headless_routes_require_exact_confirm_and_expose_no_submit(self):
        draft = self.draft()
        created = run(self.app, ["draft", "--draft-json", json.dumps(asdict(draft))])
        rid = created["review_id"]
        preview = run(self.app, ["preview", rid, "--expected-revision", "1"])
        self.assertEqual(run(self.app, ["status", rid]), preview)
        self.assertEqual(len(run(self.app, ["list"])), 1)
        with self.assertRaises(ValueError):
            run(self.app, ["confirm", rid, "--expected-revision", "1", "--expected-digest", "UNKNOWN"])
        result = run(self.app, ["confirm", rid, "--expected-revision", "1", "--expected-digest", preview["snapshot"]["digest"]])
        run(self.app, ["query"])
        cancelled = run(self.app, ["cancel", "--execution-id", result["execution_id"], "--account-id", ACCOUNT,
                                 "--trade-date", DAY, "--broker-order-id", result["execution"]["broker_order_id"]])
        self.assertEqual(cancelled["broker_order_id"], result["execution"]["broker_order_id"])
        self.assertEqual(len(self.broker.attempts), 1)

    def test_headless_strict_json_and_draft_field_validation(self):
        for value in ("{", '{"command":NaN}', '{"command":{},"command":{}}', 'null', '[]'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run(self.app, ["draft", "--draft-json", value])
        value = asdict(self.draft())
        value["command"]["unsupported"] = True
        with self.assertRaisesRegex(ValueError, "INVALID_COMMAND_FIELDS"):
            draft_from(value)
        self.assertEqual(self.app.list(), [])

    def test_invalid_lineage_and_session_never_create_durable_draft(self):
        for draft in (replace(self.draft(), source="AGENT_PROPOSAL"),
                      replace(self.draft(), owner_id=True),
                      self.draft(account_id="other"), self.draft(trade_date="2026-10-28"),
                      self.draft(space_id=["USER_SPACE"]),
                      self.draft(price="1e999999")):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                self.app.draft(draft)
        self.assertEqual(self.app.list(), [])
        self.assertEqual(self.broker.attempts, [])

    def test_unknown_review_record_version_fails_before_factory(self):
        self.app.draft(self.draft())
        self.runtime.close()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("DROP TRIGGER immutable_journal_UPDATE")
            row = con.execute("SELECT seq,payload FROM journal WHERE kind='REVIEW_DRAFTED'").fetchone()
            value = json.loads(row[1])
            value["review_version"] = 99
            con.execute("UPDATE journal SET payload=? WHERE seq=?", (json.dumps(value), row[0]))
            con.commit()
        calls = []
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
                                   session_factory=lambda: calls.append(1) or self.sdk.binding())
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_REVIEW_VERSION"):
            runtime.start()
        self.assertEqual(calls, [])

    def test_confirm_cannot_send_previous_day_preview_in_new_session(self):
        preview = self.preview()
        self.runtime.close()
        from execution_runtime.kgi import SessionBinding
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date="2026-10-30",
            session_factory=lambda: SessionBinding(self.sdk, self.sdk.binding().sdk, ACCOUNT, "2026-10-30"),
            clock=lambda: NOW)
        with runtime:
            app = ExecutionApplication(runtime)
            self.assertEqual(app.status(preview["review_id"])["snapshot"], preview["snapshot"])
            with self.assertRaisesRegex(ValueError, "COMMAND_SESSION_MISMATCH"):
                app.confirm(preview["review_id"], expected_digest=preview["snapshot"]["digest"], expected_revision=1)
        self.assertEqual(self.broker.attempts, [])


if __name__ == "__main__":
    unittest.main()
