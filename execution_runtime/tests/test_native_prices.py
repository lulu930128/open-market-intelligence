"""SDK source-contract and bounded native-price integration, sanitized evidence only."""

import ast
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from execution_runtime.application import ExecutionApplication
from execution_runtime.kgi import price_observation
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession
from .test_strategy import activate, idle, source
from execution_runtime.strategy import StrategyRules


ROOT = Path(__file__).resolve().parents[2]


def tick(**changes):
    return NS(**{**dict(symbol="TEST", close="500", odd_lot=True, datetime="20261029100000",
                       delay_time=0, volume=1, total_volume=100, simtrade=0, suspend=0), **changes})


class NativePriceTests(unittest.TestCase):
    def test_installed_taiwan_facade_signature_and_payload_contract(self):
        tree = ast.parse((ROOT / ".venv-kgi/Lib/site-packages/kgisuperpy/Quote.py").read_text(encoding="utf-8"))
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        self.assertIn("_Quote", [n.id for n in classes["_STKQuoteManager"].bases if isinstance(n, ast.Name)])
        methods = {n.name: n for n in classes["_Quote"].body if isinstance(n, ast.FunctionDef)}
        self.assertEqual([a.arg for a in methods["subscribe_all"].args.args], ["self", "symbol", "odd_lot", "version"])
        self.assertEqual([a.arg for a in methods["set_cb_all"].args.args], ["self", "callback", "version"])
        facade = ast.parse((ROOT / ".venv-kgi/Lib/site-packages/kgisuperpy/marketdata/quote_data/quotedata_facade.py").read_text(encoding="utf-8"))
        classes = {n.name: n for n in facade.body if isinstance(n, ast.ClassDef)}
        all_class = next(c for name, c in classes.items() if name.startswith("All_Stock_v1"))
        fields = {n.name for n in all_class.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue({"datetime", "symbol", "close", "odd_lot", "volume", "simtrade", "suspend", "delay_time"} <= fields)

    def test_real_timestamp_lot_and_freshness_contract(self):
        result = price_observation(tick(odd_lot="0"), NOW)
        self.assertFalse(result["odd_lot"])
        self.assertEqual(result["observed_at"], NOW.isoformat())
        self.assertTrue(price_observation(tick(odd_lot="1"), NOW)["odd_lot"])
        self.assertEqual(price_observation(tick(datetime=20261029100000), NOW)["observed_at"], NOW.isoformat())
        for changes in ({"datetime": "20261029095950"}, {"datetime": "20261029100001"},
                        {"datetime": None}, {"datetime": "202610291000"}, {"simtrade": 1},
                        {"suspend": 1}, {"delay_time": 6}, {"volume": 0}, {"odd_lot": None}, {"close": "NaN"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                price_observation(tick(**changes), NOW)

    def test_normal_ticks_have_no_journal_io_and_real_trigger_is_once(self):
        for trigger in ("470", "560"):
            with self.subTest(trigger=trigger), TemporaryDirectory(dir=Path(__file__).parent) as directory:
                sdk = FakeSession()
                subscriptions, callbacks = [], []
                sdk.Quote = NS(set_cb_all=lambda cb: callbacks.append(cb),
                               subscribe_all=lambda symbol, odd_lot=False: subscriptions.append((symbol, odd_lot)))
                now = [NOW]
                with ExecutionRuntime(Path(directory) / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
                    session_factory=sdk.binding, clock=lambda: now[0], native_prices=True) as runtime:
                    self.assertEqual(callbacks, [])  # Account-only startup is not a quote subscription.
                    app = ExecutionApplication(runtime)
                    state = activate(app)
                    idle(runtime)
                    self.assertEqual(subscriptions, [("TEST", True)])
                    self.assertEqual(app.strategy_status("strategy-1")["price_source_status"]["status"], "WAITING_NATIVE_TRADE")
                    with patch.object(runtime._journal, "connection", side_effect=AssertionError("normal tick performed IO")):
                        for n in range(20):
                            callbacks[-1](tick(close=str(490 + n % 10), total_volume=100+n))
                    self.assertIsNone(runtime._price_error)
                    with runtime._journal.connection(readonly=True) as con:
                        self.assertEqual(con.execute("SELECT count(*) FROM journal WHERE kind='STRATEGY_PRICE_OBSERVED'").fetchone()[0], 0)
                    oid = state["entry"]["broker_order_id"]
                    sdk.event(sdk.broker.fill(oid, 60, price="500"))
                    idle(runtime)
                    # A depth update with unchanged cumulative volume cannot trigger.
                    callbacks[-1](tick(close=trigger, total_volume=119))
                    idle(runtime)
                    self.assertEqual(len(sdk.broker.attempts), 1)
                    callbacks[-1](tick(close=trigger, total_volume=120))
                    idle(runtime)
                    for _ in range(5):
                        callbacks[-1](tick(close=trigger, total_volume=120))
                    idle(runtime)
                    with runtime._journal.connection(readonly=True) as con:
                        self.assertEqual(con.execute("SELECT count(*) FROM journal WHERE kind='STRATEGY_PRICE_OBSERVED'").fetchone()[0], 1)
                    self.assertEqual(len(sdk.broker.attempts), 2)  # Entry plus one reserved exit.
                    self.assertEqual(sdk.broker.attempts[-1]["qty"], 60)
                    app.revise_strategy("strategy-1", StrategyRules("460", "570", "460"), source(),
                                        request_id="after-submit-revision", expected_revision=1)
                    self.assertEqual(app.strategy_status("strategy-1")["strategy_revision"], 2)
                    with self.assertRaisesRegex(ValueError, "NATIVE_PRICE_CALLBACK_REQUIRED"):
                        app.observe_strategy_price("strategy-1", source(), request_id="manual-price", expected_revision=2,
                                                   symbol="TEST", price="1")
                    now[0] += timedelta(seconds=6)
                    self.assertEqual(app.strategy_status("strategy-1")["price_source_status"]["status"], "STALE")
                    self.assertTrue(runtime.verify())


if __name__ == "__main__":
    unittest.main()
