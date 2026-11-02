"""Carryover and native-shaped inventory contracts; isolated journals, no SDK effects."""

import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from execution_runtime.application import ExecutionApplication
from execution_runtime.contracts import BrokerKey
from execution_runtime.kgi import KgiSessionOwner, report_observation
from execution_runtime.review import Draft
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.strategy import SourceSnapshot, StrategyRules
from execution_runtime.strategy import replay as replay_strategies
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, Frame, command
from .test_native_prices import tick
from .test_strategy import activate, idle, source, RULES


ROOT = Path(__file__).resolve().parents[2]
NEXT = "2026-10-30"


def inventory_session(sdk, state, *, day=DAY, guarded=True):
    """Add only the actual SDK frame contract to the existing sanitized fixture."""
    original_orders, original_deals = sdk.account_report, sdk.ExecReport

    def dated(frame):
        return Frame([{**r, "TradeDate": day.replace("-", "")} for r in frame.rows],
                     frame.columns | {"Side"})

    sdk.Account.OrderReport = lambda: dated(original_orders())
    sdk.ExecReport = lambda: dated(original_deals())

    def holdings(mode):
        assert mode == "B"
        state["reads"] = state.get("reads", 0) + 1
        if state.get("error"):
            raise TimeoutError("sanitized")
        rows = state.get("rows", [{"Symbol": "TEST", "NETQTY0": state.get("total", 100),
                                   "NETQTY9": state.get("odd", 0)}])
        return Frame(rows, {"Symbol", "NETQTY0", "NETQTY9"})

    sdk.Account.InventorySum = holdings
    return lambda: replace(sdk.binding(), trade_date=day, current_day=lambda: day,
                           cash_inventory_required=guarded)


class CarryoverInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=ROOT / "execution_runtime/tests")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.sqlite"
        self.now = NOW
        self.runtime = None
        self.addCleanup(lambda: self.runtime.close() if self.runtime else None)

    def open(self, sdk, factory=None, *, day=DAY, prices=False):
        if self.runtime:
            self.runtime.close()
        self.sdk = sdk
        self.runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=day,
            session_factory=factory or sdk.binding, clock=lambda: self.now, native_prices=prices)
        self.runtime.start()
        self.app = ExecutionApplication(self.runtime)

    def fill(self, value, quantity, fill_id="filled"):
        self.sdk.event(self.sdk.broker.fill(value["entry"]["broker_order_id"], quantity, fill_id, price="500"))
        idle(self.runtime)

    def exit(self, sid="strategy-1", request="operator-exit", revision=1):
        self.app.exit_strategy(sid, SourceSnapshot(request, self.now.isoformat(), {}),
                              request_id=request, expected_revision=revision)
        idle(self.runtime)
        return self.app.strategy_status(sid)

    def test_installed_inventory_contract_units_fields_and_native_factory_guard(self):
        path = ROOT / ".venv-kgi/Lib/site-packages/kgisuperpy/trading/Order.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "InventorySum")
        self.assertEqual([a.arg for a in method.args.args], ["self", "FType"])
        text = ast.get_docstring(method)
        self.assertIn("'B'", text)
        self.assertIn("股", text)
        self.assertTrue(all(field in text for field in ("NETQTY0", "NETQTY9", "SALEQTY0")))
        native = (ROOT / "execution_runtime/native.py").read_text(encoding="utf-8")
        self.assertIn("cash_inventory_required=True", native)

    def test_prior_entry_new_day_quote_exit_verify_and_no_duplicate_after_reconnect(self):
        old = FakeSession()
        self.open(old)
        value = activate(self.app)
        self.fill(value, 60)
        original = self.app.status(value["review_id"])["snapshot"]
        self.now += timedelta(days=1)
        sdk, state = FakeSession(), {"total": 60}
        subscriptions, callbacks = [], []
        sdk.Quote = NS(set_cb_all=callbacks.append,
                       subscribe_all=lambda symbol, odd_lot: subscriptions.append((symbol, odd_lot)))
        self.open(sdk, inventory_session(sdk, state, day=NEXT), day=NEXT, prices=True)
        self.assertEqual(subscriptions, [("TEST", True)])
        self.app.revise_strategy("strategy-1", RULES, SourceSnapshot("today", self.now.isoformat(), {}),
                                 request_id="today-revision", expected_revision=1)
        callbacks[-1](tick(datetime="20261030100000", close="470"))
        idle(self.runtime)
        self.assertEqual(sdk.broker.attempts, [])  # First sample is not a native trade.
        callbacks[-1](tick(datetime="20261030100000", close="469", total_volume=101))
        idle(self.runtime)
        result = self.app.strategy_status("strategy-1")
        self.assertEqual((result["entry_trade_date"], result["exits"][0]["trade_date"]), (DAY, NEXT))
        self.assertEqual(result["entry_remaining"], None)
        self.assertFalse(result["entry_cancel_eligible"])
        self.assertEqual(result["exit_initiation"], "AUTOMATIC_PRICE_TRIGGER")
        self.assertEqual(result["trigger_state"], "TRIGGERED")
        self.assertEqual(result["exit_execution_state"], "CLAIMED_UNFILLED")
        self.assertFalse(result["exit_fill_guaranteed"])
        self.assertEqual([a["qty"] for a in sdk.broker.attempts], [60])
        self.assertEqual(sdk.broker.cancels, [])
        self.assertEqual(self.app.status(value["review_id"])["snapshot"], original)
        self.assertTrue(self.runtime.verify())
        with self.runtime._journal.connection(readonly=True) as con:
            records = self.runtime._strategy_records(con)
            reviews = self.runtime._reviews(con)
        corrupted = [(k, t, {**p, "command": {**p["command"], "trade_date": DAY}})
                     if k == "STRATEGY_EXIT_CLAIMED" else (k, t, p) for k, t, p in records]
        with self.assertRaisesRegex(ValueError, "STRATEGY_EXIT_CLAIM_MISMATCH"):
            replay_strategies(corrupted, reviews)
        with self.assertRaisesRegex(ValueError, "CANCEL_SESSION_MISMATCH"):
            self.runtime.cancel(value["entry_execution_id"], BrokerKey(ACCOUNT, DAY, value["entry"]["broker_order_id"]))
        self.runtime.reconnect()
        self.exit(request="explicit-again", revision=2)
        self.assertEqual(len(sdk.broker.attempts), 1)
        factory = self.runtime.session._factory
        self.open(sdk, factory, day=NEXT, prices=True)
        idle(self.runtime)
        self.assertTrue(self.runtime.verify())
        self.assertEqual(len(sdk.broker.attempts), 1)

    def test_mobile_sale_and_two_spaces_share_inventory_ceiling(self):
        sdk, state = FakeSession(), {"total": 100}
        self.open(sdk, inventory_session(sdk, state))
        first = activate(self.app)
        second = activate(self.app, sid="agent-1", space="AGENT_SPACE")
        self.fill(first, 80, "entry-user")
        self.fill(second, 80, "entry-agent")
        # Mobile sale reduced the actual total; a separate open mobile sell
        # occupies another 10. Neither is inferred as a strategy fill.
        state["total"] = 70
        sdk.broker.add({**sdk.broker.attempts[0], "action": "Sell", "qty": 10}, channel="MOBILE")
        first = self.exit()
        self.exit("agent-1")
        sold = [a["qty"] for a in sdk.broker.attempts if a["action"] == "Sell"]
        self.assertEqual(sold, [60])
        self.assertEqual(first["entry_filled"], 80)
        self.assertEqual(first["exit_initiation"], "OPERATOR")
        self.assertEqual(self.app.strategy_status("agent-1")["cash_inventory"]["reserved_quantity"], 60)
        self.assertTrue(self.runtime.verify())

    def test_odd_only_max_not_sum_quarantine_and_same_symbol_ambiguity(self):
        sdk, state = FakeSession(), {"total": 0, "odd": 120}
        self.open(sdk, inventory_session(sdk, state))
        value = activate(self.app)
        self.fill(value, 100)
        template = dict(sdk.broker.order_rows[0])
        sdk.broker.order_rows.append({**template, "StockID": "OTHER", "OrderNo": "0000", "ErrCode": "FAIL"})
        sdk.broker.add({**sdk.broker.attempts[0], "action": "Sell", "qty": 10}, channel="MOBILE")
        evidence = self.runtime.session.cash_inventory(lambda: self.now)
        self.assertEqual(evidence["holdings"]["TEST"], 120)
        self.assertEqual(len(evidence["diagnostics"]), 1)
        self.runtime.query()
        with self.runtime._journal.connection(readonly=True) as con:
            self.assertEqual(self.runtime._cash_exit_view(con, "TEST")["executable_quantity"], 110)
        state.update(total=120, odd=120)
        sdk.broker.order_rows.append({**template, "OrderNo": "0000", "ErrCode": "FAIL"})
        self.runtime.query()
        result = self.exit()
        self.assertEqual(result["cash_inventory"]["reason"], "CASH_OPEN_SELL_AMBIGUOUS")
        self.assertEqual(result["cash_inventory"]["cash_total_upper_bound"], 120)
        self.assertEqual(len(sdk.broker.attempts), 1)

    def test_two_strategies_can_each_send_only_the_shared_remainder(self):
        sdk, state = FakeSession(), {"total": 100}
        self.open(sdk, inventory_session(sdk, state))
        first = activate(self.app)
        second = activate(self.app, sid="agent-1", space="AGENT_SPACE")
        self.fill(first, 80, "user-fill")
        self.fill(second, 80, "agent-fill")
        self.exit()
        result = self.exit("agent-1")
        self.assertEqual([a["qty"] for a in sdk.broker.attempts if a["action"] == "Sell"], [80, 20])
        self.assertEqual(result["cash_inventory"]["reserved_quantity"], 100)
        self.runtime.reconnect()
        idle(self.runtime)
        self.assertEqual(len(sdk.broker.attempts), 4)
        self.assertTrue(self.runtime.verify())

    def test_unknown_missing_stale_inventory_and_explicit_review_remain_available(self):
        sdk, state = FakeSession(), {"total": 100}
        self.open(sdk, inventory_session(sdk, state))
        value = activate(self.app)
        self.fill(value, 100)
        self.now += timedelta(seconds=6)
        self.assertEqual(self.app.strategy_status("strategy-1")["cash_inventory"]["reason"], "CASH_INVENTORY_STALE")
        state["rows"] = []
        result = self.exit()
        self.assertIsNone(result["cash_inventory"]["cash_total_upper_bound"])
        self.assertEqual(len(sdk.broker.attempts), 1)
        state["error"] = True
        self.runtime.query()
        self.assertEqual(self.app.strategy_status("strategy-1")["cash_inventory"]["executable_quantity"], 0)
        draft = Draft(command(request_id="manual-sell", intent_id="manual-sell", action="Sell", quantity=1),
                      "fixture-user", "MANUAL")
        self.app.draft(draft)
        preview = self.app.preview(draft.review_id, expected_revision=1)
        self.app.confirm(draft.review_id, expected_revision=1, expected_digest=preview["snapshot"]["digest"])
        self.assertEqual(sdk.broker.attempts[-1]["qty"], 1)

    def test_capacity_changed_before_effect_is_not_sent_released_and_operator_can_resume(self):
        sdk, state = FakeSession(), {"total": 100}
        self.open(sdk, inventory_session(sdk, state))
        value = activate(self.app)
        self.fill(value, 100)
        check = self.runtime._check_cash_exit

        def shrink(command):
            state["total"] = 0
            return check(command)

        with patch.object(self.runtime, "_check_cash_exit", side_effect=shrink):
            failed = self.exit()
        self.assertEqual(len(sdk.broker.attempts), 1)
        self.assertEqual(failed["exits"][0]["submit_stage"], "NOT_SENT")
        self.assertEqual(failed["exits"][0]["broker_attempts_max"], 0)
        self.assertEqual(failed["reserved_exit_quantity"], 0)
        self.assertEqual(failed["unresolved_exit_claims"], [])
        self.assertTrue(self.runtime.verify())
        state["total"] = 100
        factory = self.runtime.session._factory
        self.open(sdk, factory)
        idle(self.runtime)
        self.runtime.reconnect()
        idle(self.runtime)
        self.assertEqual(len(sdk.broker.attempts), 1)
        resumed = self.exit(request="new-operator-action")
        self.assertEqual(len(sdk.broker.attempts), 2)
        self.assertEqual(resumed["reserved_exit_quantity"], 100)
        self.assertNotEqual(resumed["exits"][0]["execution_id"], resumed["exits"][1]["execution_id"])
        self.assertTrue(self.runtime.verify())

    def test_previous_day_unknown_exit_reservation_survives_late_fill_and_reconnect(self):
        sdk = FakeSession()
        self.open(sdk)
        value = activate(self.app)
        self.fill(value, 60)
        sdk.submit_mode = "error_after"
        failed = self.exit()
        self.assertEqual(failed["exits"][0]["state"], "UNKNOWN")
        old = sdk
        self.now += timedelta(days=1)
        sdk, state = FakeSession(), {"total": 75}
        factory = inventory_session(sdk, state, day=NEXT)
        self.open(sdk, factory, day=NEXT)
        idle(self.runtime)
        self.assertEqual(sdk.broker.attempts, [])
        old.broker.fill(value["entry"]["broker_order_id"], 15, "late-fill", price="500")
        observation = report_observation(old.broker.deal_rows[-1], ACCOUNT, deal=True)
        self.runtime._ingest(observation)  # Dated historical report, not today's callback.
        self.runtime._wake_strategies()
        idle(self.runtime)
        self.assertEqual([a["qty"] for a in sdk.broker.attempts], [15])
        result = self.app.strategy_status("strategy-1")
        self.assertEqual(result["reserved_exit_quantity"], 75)
        self.assertTrue(result["reconcile_required"])
        self.runtime.reconnect()
        idle(self.runtime)
        self.assertEqual(len(sdk.broker.attempts), 1)
        self.assertTrue(self.runtime.verify())

    def test_native_effect_exception_stays_unknown_and_reserved(self):
        sdk, state = FakeSession(), {"total": 100}
        self.open(sdk, inventory_session(sdk, state))
        value = activate(self.app)
        self.fill(value, 100)
        sdk.submit_mode = "error_after"
        result = self.exit()
        self.assertEqual(result["exits"][0]["state"], "UNKNOWN")
        self.assertEqual(result["exits"][0]["broker_attempts_max"], 1)
        self.assertEqual(result["reserved_exit_quantity"], 100)
        self.assertEqual(result["not_sent_exits"], [])
        self.runtime.reconnect()
        idle(self.runtime)
        self.exit(request="explicit-still-not-resend")
        self.assertEqual(len(sdk.broker.attempts), 2)
        self.assertTrue(self.runtime.verify())


if __name__ == "__main__":
    unittest.main()
