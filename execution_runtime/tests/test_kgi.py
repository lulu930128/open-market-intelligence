"""Verified v2.7 call mappings and static SDK callback/report shape fixtures."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from execution_runtime.contracts import BrokerKey
from execution_runtime.kgi import callback_observation, report_observation
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, command


class MappingTests(unittest.TestCase):
    def test_four_v27_mapping_families_and_repeated_post_cancel_reads(self):
        cases = (("CASH", "Buy", "Odd", 1, 10),
                 ("MARGIN", "Buy", "Common", 1000, 2000),
                 ("CASH_SELLING", "Sell", "Common", 1000, 1000),
                 ("SHORT_SELLING", "Sell", "Common", 1000, 1000))
        for condition, action, lot, unit, quantity in cases:
            with self.subTest(condition=condition), TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
                sdk = FakeSession()
                with ExecutionRuntime(Path(directory) / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
                                      session_factory=sdk.binding, clock=lambda: NOW) as runtime:
                    cmd = command(condition=condition, action=action, lot=lot,
                                  shares_per_unit=unit, quantity=quantity, price="29.51")
                    result = runtime._submit_engine(cmd)
                    args = sdk.broker.attempts[0]
                    self.assertEqual((args["action"], args["order_cond"], args["odd_lot"], args["qty"], args["price"], args["time_in_force"]),
                                     (action, condition, lot, quantity // unit, 29.51, "ROD"))
                    runtime.cancel(cmd.execution_id, BrokerKey(ACCOUNT, DAY, result["broker_order_id"]))
                    runtime.query()
                    runtime.query()
                    self.assertEqual(runtime.status(cmd.execution_id)["state"], "CANCELLED")
                    self.assertFalse(runtime.status(cmd.execution_id)["reconcile_required"])

    def test_invalid_numeric_and_unsupported_mapping_before_claim(self):
        for changes in ({"quantity": True}, {"quantity": 1.5}, {"quantity": 0}, {"price": "NaN"},
                        {"price": "Infinity"}, {"price": "0"}, {"condition": "OTHER"},
                        {"condition": "MARGIN", "lot": "Common", "action": "Sell"},
                        {"condition": "SHORT_SELLING", "lot": "Common"},
                        {"lot": "Common", "quantity": 1001, "shares_per_unit": 1000}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(command(), **changes).validate()

    def test_deal_without_status_and_missing_id(self):
        sdk = FakeSession()
        trade = sdk.create_order(action="Buy", symbol="TEST", qty=10, price=50,
                                 time_in_force="ROD", order_cond="CASH", odd_lot="Odd")
        raw = sdk.broker.fill(trade.order.order_id, 3)
        normalized = callback_observation(raw, ACCOUNT, DAY)
        self.assertEqual((normalized.kind, normalized.quantity, normalized.seqno), ("DEAL", 3, "fill-1"))
        raw.seqno = None
        with self.assertRaisesRegex(ValueError, "DEAL_ID_UNAVAILABLE"):
            callback_observation(raw, ACCOUNT, DAY)

    def test_cancel_success_callback_is_ack_report_requires_zero_remainder(self):
        sdk = FakeSession()
        trade = sdk.create_order(action="Buy", symbol="TEST", qty=10, price=50,
                                 time_in_force="ROD", order_cond="CASH", odd_lot="Odd")
        oid = trade.order.order_id
        observation = callback_observation(sdk.event_for(oid, task="CancelOrder"), ACCOUNT, DAY)
        self.assertEqual(observation.kind, "CANCEL_ACK")
        report = sdk.broker.row(oid, "D", "100002")
        self.assertEqual(report_observation(report, ACCOUNT, deal=False).kind, "CANCELLED")
        report["AfterQty"] = "1"
        with self.assertRaisesRegex(ValueError, "CANCEL_REMAINDER_NOT_ZERO"):
            report_observation(report, ACCOUNT, deal=False)

    def test_bad_date_account_and_time_do_not_become_valid_order(self):
        sdk = FakeSession()
        trade = sdk.create_order(action="Buy", symbol="TEST", qty=10, price=50,
                                 time_in_force="ROD", order_cond="CASH", odd_lot="Odd")
        report = sdk.broker.row(trade.order.order_id, "I", "100000")
        for changes in ({"TradeDate": "20260230"}, {"Account": "wrong"}, {"ReportTime": "250000"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                report_observation({**report, **changes}, ACCOUNT, deal=False)


if __name__ == "__main__":
    unittest.main()
