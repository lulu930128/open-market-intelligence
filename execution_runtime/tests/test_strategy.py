"""Phase 3 offline acceptance: canonical review, mutable policy, actual fills."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from execution_runtime.application import ExecutionApplication
from execution_runtime.contracts import BrokerKey
from execution_runtime.review import Draft
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.strategy import SourceSnapshot, StrategyRules
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, command


ROOT = Path(__file__).resolve().parents[2]
RULES = StrategyRules("480", "550", "480")


def source(name="fixture-plan", seconds=0):
    return SourceSnapshot(name, (NOW - timedelta(seconds=60-seconds)).isoformat(), {"fixture": name})


def activate(app, *, space="USER_SPACE", sid="strategy-1", quantity=100, rules=RULES):
    draft = Draft(command(request_id=sid, intent_id=sid, quantity=quantity, price="500",
                          strategy_id=sid, revision=1, space_id=space),
                  "fixture-user", "LOCAL_STRATEGY" if space == "USER_SPACE" else "AGENT_PROPOSAL")
    app.draft(draft)
    preview = app.preview(draft.review_id, expected_revision=1)
    app.confirm(draft.review_id, expected_revision=1, expected_digest=preview["snapshot"]["digest"])
    return app.create_strategy(draft.review_id, rules, source(), expected_digest=preview["snapshot"]["digest"])


def idle(runtime):
    if not runtime._strategy_idle.wait(10):
        raise AssertionError("strategy pump did not become idle")
    if runtime.strategy_error:
        raise AssertionError("strategy coordination error: " + runtime.strategy_error)


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(dir=ROOT / "execution_runtime/tests")
        self.path = Path(self.directory.name) / "strategy.sqlite"
        self.sdk = FakeSession()
        self.sdk.cancel_ack_only = True
        self.open()
        self.value = activate(self.app)
        self.entry = self.value["entry_execution_id"]
        self.entry_oid = self.value["entry"]["broker_order_id"]
        idle(self.runtime)

    def open(self):
        self.runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
                                        session_factory=self.sdk.binding, clock=lambda: NOW)
        self.runtime.start()
        self.app = ExecutionApplication(self.runtime)

    def tearDown(self):
        self.runtime.close()
        self.directory.cleanup()

    def status(self):
        idle(self.runtime)
        return self.app.strategy_status("strategy-1")

    def fill(self, oid, qty, identity, stamp="100001", price="500"):
        event = self.sdk.broker.fill(oid, qty, identity, stamp, price)
        self.sdk.event(event)
        idle(self.runtime)
        return event

    def stop(self, request="stop-1", seconds=1):
        self.app.observe_strategy_price("strategy-1", source(request, seconds), request_id=request,
            expected_revision=self.status()["strategy_revision"], symbol="TEST", price="480")
        return self.status()

    def manual(self, request="manual-1", target=0):
        self.app.exit_strategy("strategy-1", source(request), request_id=request,
                              expected_revision=self.status()["strategy_revision"], target_position=target)
        return self.status()

    def cancel_final(self, stamp="100010"):
        self.sdk.broker.order_rows.append(self.sdk.broker.row(self.entry_oid, "D", stamp))
        self.app.query()
        return self.status()

    def test_partial_entry_stop_cancel_ack_late_fill_to_zero(self):
        self.fill(self.entry_oid, 60, "entry-60")
        self.assertEqual(self.status()["protected_quantity"], 60)
        stopped = self.stop()
        self.assertEqual(self.sdk.broker.cancels, [self.entry_oid])
        self.assertEqual([e["quantity"] for e in stopped["exits"]], [60])
        self.assertEqual(stopped["entry_remaining"], 40)
        self.assertEqual(stopped["exit_reason"], "STOP")
        self.assertEqual(stopped["target_position"], 0)
        exit_oid = stopped["exits"][0]["broker_order_id"]
        self.fill(exit_oid, 60, "exit-60", "100003", "480")
        self.assertNotEqual(self.status()["state"], "CLOSED")
        self.fill(self.entry_oid, 15, "entry-late-15", "100004")
        late = self.status()
        self.assertEqual([e["quantity"] for e in late["exits"]], [60, 15])
        self.fill(late["exits"][1]["broker_order_id"], 15, "exit-15", "100005", "480")
        self.assertNotEqual(self.status()["state"], "CLOSED")
        closed = self.cancel_final()
        self.assertEqual((closed["state"], closed["entry_remaining"], closed["effective_position"]), ("CLOSED", 0, 0))
        self.assertEqual(closed["protected_quantity"], 0)
        self.assertTrue(self.runtime.verify())

    def test_revision_snapshot_restart_and_immutable_entry(self):
        original = self.app.status(self.value["review_id"])["snapshot"]
        revised = self.app.revise_strategy("strategy-1", StrategyRules("485", "560", "484"), source("amend"),
                                           request_id="amend", expected_revision=1)
        self.assertEqual(revised["strategy_revision"], 2)
        self.fill(self.entry_oid, 60, "entry-60")
        self.runtime.close()
        self.open()
        restored = self.status()
        self.assertEqual(restored["rules"], revised["rules"])
        self.assertEqual(restored["source_snapshot"], revised["source_snapshot"])
        self.assertEqual(restored["protected_quantity"], 60)
        self.assertEqual(self.app.status(self.value["review_id"])["snapshot"], original)
        self.app.observe_strategy_price("strategy-1", source("new-stop", 1), request_id="new-stop",
                                        expected_revision=2, symbol="TEST", price="485")
        stopped = self.status()
        self.assertEqual(stopped["exits"][0]["revision"], 2)
        self.assertEqual(self.sdk.broker.attempts[-1]["price"], 484)
        self.assertTrue(self.runtime.verify())

    def test_concurrent_stop_take_profit_manual_one_owner_and_one_exit(self):
        self.fill(self.entry_oid, 60, "entry-60")
        def trigger(index):
            if index % 3 == 0:
                return self.app.exit_strategy("strategy-1", source(str(index), index), request_id=str(index), expected_revision=1)
            return self.app.observe_strategy_price("strategy-1", source(str(index), index), request_id=str(index),
                expected_revision=1, symbol="TEST", price="479" if index % 3 == 1 else "551")
        with ThreadPoolExecutor(max_workers=9) as pool:
            list(pool.map(trigger, range(9)))
        value = self.status()
        self.assertIn(value["exit_owner"], {str(i) for i in range(9)})
        self.assertEqual(len(value["exits"]), 1)
        self.assertEqual(value["exits"][0]["quantity"], 60)
        self.assertEqual(len(self.sdk.broker.attempts), 2)
        self.assertEqual(self.sdk.broker.cancels, [self.entry_oid])
        self.assertTrue(self.runtime.verify())

    def test_partial_exit_and_duplicate_out_of_order_fills_reserve_remaining(self):
        first = self.fill(self.entry_oid, 40, "first", "100002")
        self.fill(self.entry_oid, 20, "earlier", "100001")
        value = self.stop()
        exit_oid = value["exits"][0]["broker_order_id"]
        partial = self.fill(exit_oid, 25, "partial-exit", "100004", "480")
        for _ in range(3):
            self.sdk.event(first)
            self.sdk.event(partial)
            self.app.query()
        value = self.status()
        self.assertEqual((value["effective_position"], value["reserved_exit_quantity"]), (35, 35))
        self.assertEqual(len(value["exits"]), 1)
        self.fill(self.entry_oid, 15, "late", "100003")
        value = self.status()
        self.assertEqual([e["quantity"] for e in value["exits"]], [60, 15])
        self.assertEqual(value["reserved_exit_quantity"], 50)
        self.assertTrue(self.runtime.verify())

    def test_unknown_exit_never_replaced_even_after_restart_and_new_trigger(self):
        self.fill(self.entry_oid, 60, "entry")
        self.sdk.submit_mode = "error_after"
        value = self.stop()
        self.assertEqual(value["exits"][0]["state"], "UNKNOWN")
        self.assertIsNone(value["exits"][0]["broker_order_id"])
        self.runtime.close()
        self.sdk = FakeSession(self.sdk.broker)
        self.sdk.cancel_ack_only = True
        self.open()
        self.manual()
        self.assertEqual(len(self.sdk.broker.attempts), 2)
        value = self.status()
        self.assertEqual(value["reserved_exit_quantity"], 60)
        self.assertEqual(value["available_exit_quantity"], 0)
        self.assertEqual(len(value["unresolved_exit_claims"]), 1)
        self.assertTrue(self.runtime.verify())

    def test_cancelled_exit_keeps_capacity_for_late_fill_without_replacement(self):
        self.fill(self.entry_oid, 60, "entry")
        value = self.stop()
        child = value["exits"][0]
        self.sdk.cancel_ack_only = False
        self.app.cancel(child["execution_id"], BrokerKey(ACCOUNT, DAY, child["broker_order_id"]))
        self.app.query()
        self.manual()
        self.assertEqual(len(self.sdk.broker.attempts), 2)
        self.assertEqual(self.status()["reserved_exit_quantity"], 60)
        self.fill(child["broker_order_id"], 20, "cancel-race-exit", "100001", "480")
        self.assertEqual(self.status()["reserved_exit_quantity"], 40)
        self.assertEqual(len(self.sdk.broker.attempts), 2)

    def test_late_fill_after_closed_reopens_and_exits_only_new_quantity(self):
        self.fill(self.entry_oid, 60, "entry")
        value = self.stop()
        self.fill(value["exits"][0]["broker_order_id"], 60, "exit", "100003", "480")
        self.assertEqual(self.cancel_final()["state"], "CLOSED")
        self.fill(self.entry_oid, 15, "late", "100004")
        value = self.status()
        self.assertNotEqual(value["state"], "CLOSED")
        self.assertEqual([e["quantity"] for e in value["exits"]], [60, 15])
        self.assertFalse(value["fill_history_complete"])

    def test_reduction_then_stop_uses_same_consent_without_new_entry(self):
        self.fill(self.entry_oid, 60, "entry")
        value = self.manual("reduce", target=40)
        self.assertEqual(value["exits"][0]["quantity"], 20)
        self.fill(value["exits"][0]["broker_order_id"], 20, "reduce-filled", "100003", "480")
        self.assertEqual(self.cancel_final()["state"], "ACTIVE")
        self.assertEqual(self.status()["protected_quantity"], 40)
        with self.assertRaisesRegex(ValueError, "NEW_EXPOSURE_REQUIRES_PREVIEW_CONFIRM"):
            self.manual("increase", target=50)
        stopped = self.stop()
        self.assertEqual([e["quantity"] for e in stopped["exits"]], [20, 40])
        self.assertEqual(stopped["target_position"], 0)
        self.assertTrue(self.runtime.verify())

    def test_zero_fill_stop_cancels_entry_without_sell(self):
        self.stop()
        self.assertEqual(len(self.sdk.broker.attempts), 1)
        self.assertEqual(self.sdk.broker.cancels, [self.entry_oid])
        self.assertNotEqual(self.status()["state"], "CLOSED")
        self.assertEqual(self.cancel_final()["state"], "CLOSED")

    def test_source_and_revision_validation_is_atomic(self):
        cases = [
            (StrategyRules("560", "480", "480"), source(), 1),
            (StrategyRules("480", "550", "NaN"), source(), 1),
            (replace(RULES, protection_mode="BROKER_NATIVE"), source(), 1),
            (RULES, SourceSnapshot("future", (NOW+timedelta(seconds=1)).isoformat(), {}), 1),
            (RULES, source(), True), (RULES, source(), 5),
        ]
        original = self.status()["audit"]
        for rules, evidence, revision in cases:
            with self.subTest(rules=rules, revision=revision), self.assertRaises(ValueError):
                self.app.revise_strategy("strategy-1", rules, evidence, request_id="bad", expected_revision=revision)
        self.assertEqual(self.status()["audit"], original)
        self.assertEqual(len(self.sdk.broker.attempts), 1)

    def test_idempotent_revision_trigger_and_conflicting_request(self):
        for _ in range(2):
            self.app.revise_strategy("strategy-1", RULES, source(), request_id="same", expected_revision=1)
        self.assertEqual(self.status()["strategy_revision"], 2)
        with self.assertRaisesRegex(ValueError, "STRATEGY_IDEMPOTENCY_CONFLICT"):
            self.app.revise_strategy("strategy-1", StrategyRules("481", "551", "480"), source(),
                                     request_id="same", expected_revision=1)
        self.fill(self.entry_oid, 60, "entry")
        self.manual()
        self.manual()
        self.assertEqual(len(self.status()["exits"]), 1)

    def test_price_source_dedup_watermark_and_wrong_symbol(self):
        self.fill(self.entry_oid, 60, "entry")
        self.app.observe_strategy_price("strategy-1", source("current", 10), request_id="current",
                                        expected_revision=1, symbol="TEST", price="510")
        self.app.observe_strategy_price("strategy-1", source("old", 1), request_id="old",
                                        expected_revision=1, symbol="TEST", price="470")
        self.assertIsNone(self.status()["target_position"])
        with self.assertRaisesRegex(ValueError, "STRATEGY_SYMBOL_MISMATCH"):
            self.app.observe_strategy_price("strategy-1", source("wrong", 11), request_id="wrong",
                                            expected_revision=1, symbol="OTHER", price="470")
        self.stop("new", 11)
        self.stop("new", 11)
        self.assertEqual(len(self.status()["exits"]), 1)

    def test_agent_space_and_mobile_pool_are_not_strategy_position_allocations(self):
        agent = activate(self.app, space="AGENT_SPACE", sid="agent-1")
        self.fill(self.entry_oid, 60, "entry")
        self.fill(agent["entry"]["broker_order_id"], 20, "agent-fill")
        mobile_oid = self.sdk.broker.add(self.sdk.broker.attempts[0], channel="MOBILE")
        self.sdk.broker.fill(mobile_oid, 40, "mobile-fill")
        self.app.query()
        self.assertEqual(self.status()["protected_quantity"], 60)
        self.assertEqual(self.app.strategy_status("agent-1")["protected_quantity"], 20)
        self.assertEqual(self.runtime.external_orders()[0]["space_id"], "USER_SPACE")
        self.assertEqual(self.status()["space_id"], "USER_SPACE")
        self.assertEqual(self.app.strategy_status("agent-1")["space_id"], "AGENT_SPACE")

    def test_status_is_read_only_and_native_status_is_explicit(self):
        idle(self.runtime)
        with patch.object(self.runtime.session, "query", side_effect=AssertionError("status IO")), \
             patch.object(self.runtime, "_append", side_effect=AssertionError("status write")):
            value = self.app.strategy_status("strategy-1")
        self.assertEqual(value["protection_mode"], "LOCAL_SYNTHETIC")
        self.assertEqual(value["broker_native_protection"], "NOT_SUPPORTED")
        self.assertIn("PROVISIONAL", value["consent_policy"])
        value["source_snapshot"]["content"]["fixture"] = "mutated"
        self.assertNotEqual(self.status()["source_snapshot"], value["source_snapshot"])

    def test_sdk_waiting_for_callback_thread_does_not_deadlock_exit(self):
        self.fill(self.entry_oid, 60, "entry")
        original = self.sdk.cancel_order
        def cancel(oid):
            callback = Thread(target=lambda: self.sdk.event(self.sdk.event_for(oid, task="CancelOrder", stamp="100002")))
            callback.start()
            callback.join(2)
            self.assertFalse(callback.is_alive(), "callback tried to acquire SDK lock")
            return original(oid)
        with patch.object(self.sdk, "cancel_order", side_effect=cancel):
            value = self.stop()
        self.assertEqual(value["exits"][0]["quantity"], 60)
        self.assertIsNone(self.runtime.callback_error)

    def test_forged_broker_totals_do_not_create_strategy_fills(self):
        self.sdk.broker.fill(self.entry_oid, 60, "missing-id")
        with patch.object(self.sdk, "ExecReport", return_value=type(self.sdk.ExecReport())([], {"OrderNo", "TradeDate", "DealQty", "CNT"})):
            self.app.query()
            value = self.stop()
        self.assertEqual(value["entry_filled"], 0)
        self.assertEqual(value["exits"], [])
        self.assertEqual(len(self.sdk.broker.attempts), 1)

    def test_take_profit_updated_rules_equal_time_tick_and_revision_lineage(self):
        self.fill(self.entry_oid, 60, "entry")
        self.app.revise_strategy("strategy-1", StrategyRules("485", "530", "529"), source("tp-edit"),
                                 request_id="tp-edit", expected_revision=1)
        for name, price in (("before", "525"), ("hit", "530")):
            self.app.observe_strategy_price("strategy-1", source(name, 10), request_id=name,
                                            expected_revision=2, symbol="TEST", price=price)
        value = self.status()
        self.assertEqual(value["exit_reason"], "TAKE_PROFIT")
        self.assertEqual(value["exits"][0]["quantity"], 60)
        self.assertEqual(self.sdk.broker.attempts[-1]["price"], 529)
        self.assertEqual(self.sdk.broker.cancels, [self.entry_oid])

    def test_cancel_synchronous_late_fill_reserves_only_new_gap(self):
        self.fill(self.entry_oid, 60, "entry")
        self.sdk.cancel_fill = 15
        value = self.stop()
        self.assertEqual(value["entry_filled"], 75)
        self.assertEqual([e["quantity"] for e in value["exits"]], [60, 15])
        self.assertEqual(value["reserved_exit_quantity"], 75)
        self.assertTrue(self.runtime.verify())

    def test_rejected_exit_is_visible_without_an_unbounded_resubmit_loop(self):
        self.fill(self.entry_oid, 60, "entry")
        self.sdk.submit_mode = "reject"
        value = self.stop()
        self.assertEqual(value["exits"][0]["state"], "REJECTED")
        self.assertEqual(len(value["unresolved_exit_claims"]), 1)
        for _ in range(3):
            self.app.query()
        self.assertEqual(len(self.status()["exits"]), 1)
        self.assertEqual(len(self.sdk.broker.attempts), 2)

    def test_new_entry_requires_new_review_and_strategy_identity(self):
        new = command(request_id="new", intent_id="new", strategy_id="strategy-1", revision=2)
        with self.assertRaisesRegex(ValueError, "CONFIRMED_REVIEW_REQUIRED"):
            self.runtime.submit(new)
        draft = Draft(new, "fixture-user", "LOCAL_STRATEGY")
        self.app.draft(draft)
        preview = self.app.preview(draft.review_id, expected_revision=1)
        with self.assertRaisesRegex(ValueError, "STRATEGY_ENTRY_ALREADY_BOUND"):
            self.app.confirm(draft.review_id, expected_revision=1, expected_digest=preview["snapshot"]["digest"])
        self.assertEqual(self.app.status(draft.review_id)["state"], "PREVIEW")
        activate(self.app, sid="new-strategy")
        self.assertEqual(len(self.sdk.broker.attempts), 2)

    def test_unconfirmed_or_unqualified_entry_cannot_activate_strategy(self):
        draft = Draft(command(request_id="draft", intent_id="draft", strategy_id="draft", revision=1),
                      "fixture-user", "LOCAL_STRATEGY")
        self.app.draft(draft)
        preview = self.app.preview(draft.review_id, expected_revision=1)
        with self.assertRaisesRegex(ValueError, "EXECUTED_STRATEGY_REVIEW_REQUIRED"):
            self.app.create_strategy(draft.review_id, RULES, source(), expected_digest=preview["snapshot"]["digest"])
        with self.assertRaisesRegex(ValueError, "STRATEGY_IDEMPOTENCY_CONFLICT"):
            self.app.create_strategy(self.value["review_id"], RULES, source(), expected_digest="0"*64)

    def test_unknown_version_source_tamper_or_orphan_claim_fails_before_factory(self):
        idle(self.runtime)
        self.runtime.close()
        from execution_runtime.storage import Journal
        for change in ("version", "digest", "lineage", "claim"):
            with self.subTest(change=change):
                scenario_path = self.path.with_name(f"tamper-{change}.sqlite")
                with self.runtime._journal.connection(readonly=True) as source, closing(sqlite3.connect(scenario_path)) as target:
                    source.backup(target)
                journal = Journal(scenario_path, ACCOUNT)
                with journal.connection() as con:
                    if change == "claim":
                        con.execute("INSERT INTO journal VALUES (9999,'invalid',?,'STRATEGY_EXIT_CLAIMED',?,?)",
                            (self.entry, NOW.isoformat(), json.dumps({"strategy_version": 1,
                             "strategy_id": "strategy-1", "strategy_revision": 1, "command": {},
                             "exit_owner": "missing", "target_position": 0})))
                    else:
                        con.execute("DROP TRIGGER immutable_journal_UPDATE")
                        row = con.execute("SELECT seq,payload FROM journal WHERE kind='STRATEGY_CREATED'").fetchone()
                        payload = json.loads(row["payload"])
                        if change == "version":
                            payload["strategy_version"] = 2
                        elif change == "digest":
                            payload["source_snapshot"]["content"] = {"tamper": True}
                        else:
                            payload["strategy_id"] = "other"
                        con.execute("UPDATE journal SET payload=? WHERE seq=?", (json.dumps(payload), row["seq"]))
                calls = []
                runtime = ExecutionRuntime(scenario_path, account_id=ACCOUNT, trade_date=DAY,
                    session_factory=lambda: calls.append(True), clock=lambda: NOW)
                with self.assertRaises((ValueError, TypeError)):
                    runtime.start()
                self.assertEqual(calls, [])
        self.open()

    def test_entry_fill_callback_concurrent_with_exit_triggers_is_quantity_bounded(self):
        self.fill(self.entry_oid, 60, "entry")
        events = [self.sdk.broker.fill(self.entry_oid, 5, f"late-{i}", f"10000{i+2}") for i in range(3)]
        def operation(i):
            if i < 3:
                self.sdk.event(events[i])
            else:
                self.app.exit_strategy("strategy-1", source(str(i)), request_id=str(i), expected_revision=1)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(operation, range(6)))
        value = self.status()
        self.assertEqual(value["entry_filled"], 75)
        self.assertEqual(sum(c["quantity"] for c in value["exits"]), 75)
        self.assertEqual(self.sdk.broker.cancels, [self.entry_oid])
        self.assertTrue(self.runtime.verify())


if __name__ == "__main__":
    unittest.main()
