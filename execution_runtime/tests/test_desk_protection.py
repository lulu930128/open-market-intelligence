"""Human Desk command -> existing session -> per-order, filled-size exits."""
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.strategy import StrategyRules, trigger_target
from execution_runtime.strategy import exit_command, SourceSnapshot
from .fake_sdk import ACCOUNT, DAY, NOW
from .fake_us_sdk import DualFactory, SYMBOL
from .test_strategy import idle


class DeskProtectionTests(unittest.TestCase):
    def test_short_direction_and_user_revision_keep_entry_identity(self):
        with TemporaryDirectory() as root:
            factory = DualFactory()
            runtime = ExecutionRuntime(Path(root) / "short.sqlite", account_id=ACCOUNT, trade_date=DAY,
                session_factory=factory, clock=lambda: NOW, strategy_effects=False)
            with runtime:
                rules = StrategyRules("110", "90", "110", direction=-1, enabled=True)
                selection = {"candidate_id": "short", "candidate_revision": 1, "pending_id": "short", "pending_revision": 1, "pending_digest": "b" * 64}
                receipt = runtime.desk_submit({"symbol": "TEST", "action": "Sell", "condition": "SHORT_SELLING", "lot": "Common", "quantity_shares": 2000, "price": "100", "protection": asdict(rules)}, selection)
                eid = receipt["execution"]["execution_id"]
                updated = runtime.desk_protection("TW", eid, asdict(StrategyRules("108", "85", "108", direction=-1, enabled=True)), "change-stop", 1)
                self.assertEqual(updated["execution"]["execution_id"], eid)
                self.assertEqual(updated["protection"]["strategy_revision"], 2)
                with runtime._journal.connection(readonly=True) as con:
                    strategy = runtime._strategies(con)[updated["execution"]["strategy_id"]]
                child = exit_command(strategy, 1000)
                self.assertEqual((child.action, child.condition), ("Buy", "SHORT_SELLING"))
                self.assertEqual(trigger_target(strategy.rules, "108", 2000), ("STOP", 0))
                self.assertEqual(trigger_target(strategy.rules, "85", 2000), ("TAKE_PROFIT", 0))
                self.assertEqual(len(factory.sessions[0].broker.attempts), 1)

    def test_small_position_does_not_silently_exit_tp2_at_tp1(self):
        rules = StrategyRules("9", "14", "9", targets=({"price": "12", "fraction": "0.5", "limit_price": "12"}, {"price": "14", "fraction": "0.5", "limit_price": "14"}), enabled=True)
        self.assertEqual(trigger_target(rules, "12", 1), (None, None))
        self.assertEqual(trigger_target(rules, "14", 1), ("TAKE_PROFIT:1", 0))

    def test_tw_us_protection_is_per_order_and_uses_actual_fills(self):
        for market in ("TW", "US"):
            with self.subTest(market=market), TemporaryDirectory() as root:
                factory, now = DualFactory(), [NOW]
                runtime = ExecutionRuntime(Path(root) / "desk.sqlite", account_id=ACCOUNT, trade_date=DAY,
                    session_factory=factory, clock=lambda: now[0], strategy_effects=False)
                runtime.start()
                try:
                    rules = StrategyRules("9", "14", "9", targets=({"price": "12", "fraction": "0.5", "limit_price": "12"}, {"price": "14", "fraction": "0.5", "limit_price": "14"}), enabled=True)
                    order = {"market": market, "symbol": SYMBOL if market == "US" else "TEST", "action": "Buy", "condition": "CASH", "lot": "Shares" if market == "US" else "Odd", "quantity_shares": 10, "price": "10", "protection": asdict(rules)}
                    selection = {"candidate_id": "candidate-one", "candidate_revision": 1, "pending_id": "pending-one", "pending_revision": 1, "pending_digest": "a" * 64}
                    sent = runtime.desk_submit(order, selection)
                    target = runtime.us_runtime if market == "US" else runtime
                    eid = sent["execution"]["execution_id"]
                    self.assertEqual(runtime.desk_submit(order, selection)["execution"]["execution_id"], eid)
                    if market == "US":
                        factory.us.rows[0]["exe_qty"] = 10
                        target.query()
                        target.query()
                        self.assertEqual(target.status(eid)["filled_shares"], 10)
                        self.assertEqual(target.status(eid)["fills"], [])
                    else:
                        sdk = factory.sessions[0]
                        sdk.event(sdk.broker.fill(sent["execution"]["broker_order_id"], 10, "entry-fill", price="10"))
                    idle(runtime)
                    target.native_prices = True
                    target._watch_strategy_prices()
                    def tick(price, volume):
                        now[0] += timedelta(seconds=1)
                        target._native_price({"symbol": order["symbol"], "close": price, "total_volume": volume,
                            "datetime": now[0], "delay_time": "0.001", "volume": 1, "suspend": False,
                            "simtrade": False, "odd_lot": market == "TW"}, target.session.generation)
                        idle(runtime)
                    tick("11", 1)
                    tick("12", 2)
                    status = runtime.desk_order(market, eid)["protection"]
                    self.assertEqual(status["reserved_exit_quantity"], 5, status)
                    self.assertTrue(status["strategy_effects"])
                    self.assertEqual(status["rules"]["targets"][1]["price"], "14")
                    tick("14", 3)
                    status = runtime.desk_order(market, eid)["protection"]
                    self.assertEqual(status["reserved_exit_quantity"], 10)
                    self.assertTrue(target.verify())
                    self.assertEqual(len(factory.us.attempts) if market == "US" else len(factory.sessions[0].broker.attempts), 3)
                finally:
                    runtime.close()
