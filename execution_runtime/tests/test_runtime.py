"""Durable command/callback/reconciliation regression with KGI-shaped fakes."""

from dataclasses import replace
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from execution_runtime.contracts import BrokerKey
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession, command


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.path = Path(self.temp.name) / "execution.sqlite"
        self.broker = FakeBroker()
        self.sdk = FakeSession(self.broker)
        self.runtime = self.open(self.sdk)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def open(self, sdk, **kwargs):
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
            session_factory=sdk.binding, clock=lambda: NOW, **kwargs)
        runtime.start()
        return runtime

    def submit(self, **kwargs):
        cmd = command(**kwargs)
        return cmd, self.runtime._submit_engine(cmd)

    def key(self, status):
        return BrokerKey(ACCOUNT, DAY, status["broker_order_id"])

    def test_claim_committed_before_sdk_and_replay_returns_same_receipt(self):
        cmd = command()
        self.sdk.before_create = lambda: self.assertEqual(self.runtime.status(cmd.execution_id)["submit_stage"], "CLAIMED")
        first = self.runtime._submit_engine(cmd)
        self.assertEqual(first["state"], "ACCEPTED")
        self.assertEqual(self.runtime._submit_engine(cmd), first)
        self.assertEqual(len(self.broker.attempts), 1)
        self.assertEqual(first["intent_id"], cmd.intent_id)

    def test_payload_or_intent_request_alias_cannot_create_second_attempt(self):
        cmd, _ = self.submit()
        for other in (replace(cmd, price="51"), replace(cmd, request_id="new"), replace(cmd, intent_id="new")):
            with self.assertRaisesRegex(ValueError, "IDEMPOTENCY_CONFLICT"):
                self.runtime._submit_engine(other)
        self.assertEqual(len(self.broker.attempts), 1)

    def test_unknown_before_and_after_effect_never_resends(self):
        for mode in ("error_before", "error_after"):
            self.sdk.submit_mode = mode
            cmd, result = self.submit(request_id=mode, intent_id=mode)
            self.assertEqual(result["state"], "UNKNOWN")
            self.runtime._submit_engine(cmd)
        self.assertEqual(len(self.broker.attempts), 2)
        self.runtime.query()
        self.assertEqual(len(self.runtime.external_orders()), 1)

    def test_pending_id_appears_later_without_resend(self):
        self.sdk.submit_mode = "pending"
        cmd, result = self.submit()
        self.assertEqual(result["state"], "PENDING")
        self.assertIsNone(result["broker_order_id"])
        self.runtime._submit_engine(cmd)
        self.sdk.pending_trade.order.order_id = "O0001"
        self.runtime.query()
        self.assertEqual(self.runtime.status(cmd.execution_id)["state"], "ACCEPTED")
        self.assertEqual(self.runtime.external_orders(), [])
        self.assertEqual(len(self.broker.attempts), 1)

    def test_callback_before_binding_is_persisted_then_correlated(self):
        self.sdk.callback_before_return = True
        cmd, result = self.submit()
        self.assertEqual(result["state"], "ACCEPTED")
        self.assertEqual(self.runtime.external_orders(), [])
        self.assertIsNone(self.runtime.callback_error)

    def test_partial_duplicate_out_of_order_deals_and_query_dedupe(self):
        cmd, result = self.submit()
        oid = result["broker_order_id"]
        later = self.broker.fill(oid, 3, "fill-2", "100003")
        earlier = self.broker.fill(oid, 2, "fill-1", "100001")
        for event in (later, earlier, later, earlier):
            self.sdk.event(event)
        self.sdk.event(self.sdk.event_for(oid))  # late acceptance cannot reset fills
        self.runtime.query()
        status = self.runtime.status(cmd.execution_id)
        self.assertEqual(status["filled_shares"], 5)
        self.assertEqual(status["state"], "PARTIALLY_FILLED")
        self.assertEqual(len(status["fills"]), 2)

    def test_cancel_ack_is_not_final_and_no_confirmation_or_cancel_all(self):
        self.sdk.cancel_ack_only = True
        cmd, result = self.submit()
        cancelled = self.runtime.cancel(cmd.execution_id, self.key(result))
        self.assertEqual(cancelled["state"], "CANCEL_PENDING")
        self.runtime.cancel(cmd.execution_id, self.key(result))
        self.assertEqual(self.broker.cancels, [result["broker_order_id"]])

    def test_exact_cancel_partial_and_late_full_fill_race(self):
        self.sdk.cancel_fill = 4
        cmd, result = self.submit()
        self.runtime.cancel(cmd.execution_id, self.key(result))
        self.runtime.reconcile()
        status = self.runtime.status(cmd.execution_id)
        self.assertEqual((status["state"], status["filled_shares"]), ("CANCELLED", 4))
        self.sdk.event(self.broker.fill(result["broker_order_id"], 6, "late-fill", "100003"))
        self.runtime.reconcile()
        status = self.runtime.status(cmd.execution_id)
        self.assertEqual((status["state"], status["filled_shares"]), ("FILLED", 10))
        self.assertEqual(len(status["fills"]), 2)

    def test_exact_id_scope_mismatch_cannot_cancel(self):
        cmd, result = self.submit()
        for key in (BrokerKey(ACCOUNT, DAY, "OTHER"), BrokerKey("other", DAY, result["broker_order_id"]),
                    BrokerKey(ACCOUNT, "2026-10-28", result["broker_order_id"])):
            with self.assertRaisesRegex(ValueError, "EXACT_CANCEL_IDENTITY_REQUIRED"):
                self.runtime.cancel(cmd.execution_id, key)
        self.assertEqual(self.broker.cancels, [])

    def test_restart_recovers_missed_fill_and_same_identity(self):
        cmd, first = self.submit()
        self.runtime.close()
        self.broker.fill(first["broker_order_id"], 4)
        self.sdk = FakeSession(self.broker)
        self.runtime = self.open(self.sdk)
        recovered = self.runtime.status(cmd.execution_id)
        self.assertEqual(recovered["broker_order_id"], first["broker_order_id"])
        self.assertEqual(recovered["filled_shares"], 4)
        self.runtime._submit_engine(cmd)
        self.assertEqual(len(self.broker.attempts), 1)

    def test_external_mobile_same_economic_order_never_claims_internal_identity(self):
        cmd, first = self.submit()
        self.broker.add(self.broker.attempts[0], "MOBILE1", channel="MOBILE")
        self.runtime.query()
        external = self.runtime.external_orders()
        self.assertEqual(len(external), 1)
        self.assertEqual(external[0]["space_id"], "USER_SPACE")
        self.assertEqual(external[0]["order_id"], "MOBILE1")
        self.runtime.query()
        self.assertEqual(external, self.runtime.external_orders())
        self.assertEqual(self.runtime.status(cmd.execution_id)["broker_order_id"], first["broker_order_id"])

    def test_cancelled_history_does_not_block_new_intent(self):
        cmd, first = self.submit()
        self.runtime.cancel(cmd.execution_id, self.key(first))
        self.runtime.query()
        _, second = self.submit(request_id="next", intent_id="next")
        self.assertNotEqual(first["broker_order_id"], second["broker_order_id"])
        self.assertEqual(len(self.broker.attempts), 2)

    def test_query_failure_is_not_empty_and_repeated_reads_are_fresh(self):
        cmd, _ = self.submit()
        before = self.sdk.query_count
        self.sdk.query_error = True
        self.assertEqual(self.runtime.query()["status"], "UNAVAILABLE")
        self.sdk.query_error = False
        self.runtime.query()
        self.runtime.query()
        self.assertEqual(self.sdk.query_count, before + 3)
        self.assertTrue(all(self.sdk.full_reads))
        self.assertFalse(self.runtime.status(cmd.execution_id)["reconcile_required"])

    def test_reconnect_closes_old_session_and_ignores_its_late_callback(self):
        cmd, result = self.submit()
        old = self.sdk
        new = FakeSession(self.broker)
        self.runtime.session._factory = new.binding
        self.runtime.reconnect()
        self.assertTrue(old.closed)
        old.event(self.broker.fill(result["broker_order_id"], 2))
        self.assertEqual(self.runtime.status(cmd.execution_id)["filled_shares"], 0)
        self.runtime.query()
        self.assertEqual(self.runtime.status(cmd.execution_id)["filled_shares"], 2)
        self.assertEqual(len(self.broker.attempts), 1)

    def test_second_owner_cannot_open_session(self):
        other = FakeSession(self.broker)
        calls = []
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
            session_factory=lambda: calls.append(1) or other.binding())
        with self.assertRaisesRegex(RuntimeError, "EXECUTION_OWNER_ALREADY_ACTIVE"):
            runtime.start()
        self.assertEqual(calls, [])

    def test_concurrent_same_command_only_one_attempt(self):
        errors = []
        def submit():
            try:
                self.runtime._submit_engine(command())
            except Exception as exc:
                errors.append(exc)
        threads = [Thread(target=submit) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.broker.attempts), 1)

    def test_fill_id_conflict_and_overfill_roll_back_atomically(self):
        cmd, result = self.submit()
        event = self.broker.fill(result["broker_order_id"], 4)
        self.sdk.event(event)
        event.quantity = 5
        self.sdk.event(event)
        self.assertTrue(self.runtime.status(cmd.execution_id)["reconcile_required"])
        event.seqno, event.quantity = "overfill", 20
        self.sdk.event(event)
        status = self.runtime.status(cmd.execution_id)
        self.assertEqual(status["filled_shares"], 4)
        self.assertEqual(len(status["fills"]), 1)

    def test_readonly_status_and_immutable_facts(self):
        cmd, _ = self.submit()
        with closing(sqlite3.connect(self.path)) as con:
            before = con.execute("SELECT count(*) FROM journal").fetchone()[0]
            with self.assertRaisesRegex(sqlite3.IntegrityError, "IMMUTABLE_EXECUTION_FACT"):
                con.execute("DELETE FROM intents")
        self.runtime.status(cmd.execution_id)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM journal").fetchone()[0], before)

    def test_foreign_database_is_not_migrated(self):
        self.runtime.close()
        other = Path(self.temp.name) / "foreign.sqlite"
        with closing(sqlite3.connect(other)) as con:
            con.execute("CREATE TABLE unrelated(value TEXT)")
        before = other.read_bytes()
        runtime = ExecutionRuntime(other, account_id=ACCOUNT, trade_date=DAY, session_factory=self.sdk.binding)
        with self.assertRaisesRegex(ValueError, "FOREIGN_JOURNAL"):
            runtime.start()
        self.assertEqual(before, other.read_bytes())

    def test_rejected_return_without_id_is_not_pending_or_resent(self):
        self.sdk.submit_mode = "reject"
        cmd, result = self.submit()
        self.assertEqual(result["state"], "REJECTED")
        self.assertIsNone(result["broker_order_id"])
        self.assertEqual(self.runtime.query()["invalid_trade_count"], 1)
        self.runtime._submit_engine(cmd)
        self.assertEqual(len(self.broker.attempts), 1)
        self.assertTrue(self.runtime.verify())

    def test_restart_accepted_order_and_missing_cache_do_not_invent_fills(self):
        cmd, result = self.submit()
        self.runtime.close()
        self.sdk = FakeSession(self.broker)
        self.runtime = self.open(self.sdk)
        self.assertEqual(self.runtime.status(cmd.execution_id)["state"], "ACCEPTED")
        self.sdk.cache_missing = True
        self.runtime.query()
        self.assertTrue(self.runtime.status(cmd.execution_id)["reconcile_required"])
        self.runtime.cancel(cmd.execution_id, self.key(result))
        self.assertEqual(self.broker.cancels, [])
        self.assertEqual(self.runtime.status(cmd.execution_id)["state"], "UNKNOWN")

    def test_projection_corruption_stops_before_session_creation(self):
        cmd, _ = self.submit()
        self.runtime.close()
        with closing(sqlite3.connect(self.path)) as con:
            state = json.loads(con.execute("SELECT state FROM orders").fetchone()[0])
            state["state"] = "FILLED"
            con.execute("UPDATE orders SET state=?", (json.dumps(state),))
            con.commit()
        calls = []
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
            session_factory=lambda: calls.append(1) or self.sdk.binding())
        with self.assertRaisesRegex(ValueError, "JOURNAL_PROJECTION_MISMATCH"):
            runtime.start()
        self.assertEqual(calls, [])

    def test_new_thread_callback_during_submit_does_not_deadlock(self):
        def callback():
            thread = Thread(target=lambda: self.sdk.event(self.sdk.event_for("O0001")))
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.sdk.after_create = callback
        _, result = self.submit()
        self.assertEqual(result["state"], "ACCEPTED")

    def test_unconfirmed_logout_retains_owner_lease(self):
        original = self.sdk.logout
        def fail():
            raise RuntimeError("fixture-logout-unknown")
        self.sdk.logout = fail
        try:
            with self.assertRaisesRegex(RuntimeError, "fixture-logout-unknown"):
                self.runtime.close()
            other = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY, session_factory=self.sdk.binding)
            with self.assertRaisesRegex(RuntimeError, "EXECUTION_OWNER_ALREADY_ACTIVE"):
                other.start()
        finally:
            self.sdk.logout = original

    def test_incomplete_exec_report_does_not_invent_fill_ledger(self):
        cmd, result = self.submit()
        self.broker.fill(result["broker_order_id"], 4)
        original = self.sdk.ExecReport
        from .fake_sdk import Frame
        self.sdk.ExecReport = lambda: Frame([], {"OrderNo", "TradeDate", "DealQty", "CNT"})
        self.runtime.query()
        status = self.runtime.status(cmd.execution_id)
        self.assertEqual(status["filled_shares"], 0)
        self.assertTrue(status["reconcile_required"])
        self.sdk.ExecReport = original
        self.runtime.query()
        self.assertEqual(self.runtime.status(cmd.execution_id)["filled_shares"], 4)
        self.assertFalse(self.runtime.status(cmd.execution_id)["reconcile_required"])

    def test_malformed_submit_response_stays_unknown(self):
        self.sdk.create_order = lambda **args: None
        cmd, result = self.submit()
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["submit_claims"], 1)
        self.assertEqual(self.runtime._submit_engine(cmd)["state"], "UNKNOWN")

    def test_same_broker_number_on_another_date_is_distinct_external_identity(self):
        cmd, result = self.submit()
        prior_day = dict(self.broker.order_rows[0], TradeDate="20261028")
        self.broker.order_rows.append(prior_day)
        self.runtime.query()
        external = self.runtime.external_orders()
        self.assertEqual(len(external), 1)
        self.assertEqual(external[0]["trade_date"], "2026-10-28")
        self.assertEqual(self.runtime.status(cmd.execution_id)["trade_date"], DAY)

    def test_unknown_journal_version_cannot_start_or_migrate(self):
        self.runtime.close()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("PRAGMA user_version=999")
        calls = []
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
            session_factory=lambda: calls.append(1) or self.sdk.binding())
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_JOURNAL_VERSION"):
            runtime.start()
        self.assertEqual(calls, [])

    def test_missing_order_projection_is_detected_before_session_start(self):
        self.submit()
        self.runtime.close()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("DELETE FROM orders")
            con.commit()
        calls = []
        runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
            session_factory=lambda: calls.append(1) or self.sdk.binding())
        with self.assertRaisesRegex(ValueError, "JOURNAL_ORDER_SET_MISMATCH"):
            runtime.start()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
