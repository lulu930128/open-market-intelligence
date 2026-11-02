"""Anonymous history + synthetic corruption; injected sessions and temp journals only."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from execution_runtime.kgi import report_observation
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, Frame, command


FIXTURES = json.loads((Path(__file__).parent / "fixtures/kgi_history_reports.json").read_text(encoding="utf-8"))["rows"]


class ReportParsingTests(unittest.TestCase):
    def test_anonymous_successful_insert_and_delete_keep_verified_semantics(self):
        accepted = report_observation(FIXTURES["accepted"], ACCOUNT, deal=False)
        cancelled = report_observation(FIXTURES["cancelled"], ACCOUNT, deal=False)
        self.assertEqual((accepted.kind, accepted.source_time, accepted.key.order_id),
                         ("ACCEPTED", "122316", "HIST-SHORT"))
        self.assertEqual((cancelled.kind, cancelled.remaining), ("CANCELLED", 0))

    def test_placeholder_order_number_never_becomes_broker_identity(self):
        for oid in ("0000", "", None, float("nan"), 0):
            with self.subTest(oid=oid), self.assertRaisesRegex(ValueError, "BROKER_ORDER_ID_UNAVAILABLE"):
                report_observation({**FIXTURES["accepted"], "OrderNo": oid}, ACCOUNT, deal=False)

    def test_missing_symbol_and_fill_identity_do_not_become_stringified_facts(self):
        for value in (None, "", float("nan")):
            with self.subTest(symbol=value), self.assertRaisesRegex(ValueError, "BROKER_SYMBOL_UNAVAILABLE"):
                report_observation({**FIXTURES["accepted"], "StockID": value}, ACCOUNT, deal=False)
            with self.subTest(cnt=value), self.assertRaisesRegex(ValueError, "DEAL_ID_UNAVAILABLE"):
                report_observation({**FIXTURES["accepted"], "DealQty": 1, "CNT": value}, ACCOUNT, deal=True)

    def test_blank_invalid_or_missing_time_never_uses_client_or_receipt_time(self):
        for value in ("", None, "250000", "126000", "1000", "10:00:00", "NaN"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "BROKER_TIME_"):
                report_observation({**FIXTURES["accepted"], "ReportTime": value}, ACCOUNT, deal=False)

    def test_failed_or_unknown_error_code_is_not_an_order_fact(self):
        for function in ("I", "D"):
            for error in ("MAT0095", "OTHER123", "1", "", None):
                with self.subTest(function=function, error=error), self.assertRaisesRegex(ValueError, "BROKER_REPORT_ERROR"):
                    report_observation({**FIXTURES["cancelled"], "OrderFunc": function, "ErrCode": error}, ACCOUNT, deal=False)

    def test_amendments_including_zero_quantity_are_not_cancel_facts(self):
        for name in ("quantity_amendment", "price_amendment"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "UNSUPPORTED_ORDER_AMENDMENT"):
                report_observation(FIXTURES[name], ACCOUNT, deal=False)
        for function in ("X", "", None, ["I"]):
            with self.subTest(function=function), self.assertRaisesRegex(ValueError, "UNSUPPORTED_ORDER_AMENDMENT"):
                report_observation({**FIXTURES["accepted"], "OrderFunc": function}, ACCOUNT, deal=False)


class ReportBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.sqlite"
        self.sdk = FakeSession()
        self.runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
                                        session_factory=self.sdk.binding, clock=lambda: NOW)
        self.addCleanup(self.runtime.close)
        self.runtime.start()
        self.cmd = command()
        self.oid = self.runtime._submit_engine(self.cmd)["broker_order_id"]
        self.extra_orders, self.extra_deals = [], []
        # Keep raw Account reports independent of the SDK cache, as in v2.7.
        original_orders, original_deals = self.sdk.Account.OrderReport, self.sdk.ExecReport
        self.sdk.Account.OrderReport = lambda: self.extend(original_orders(), self.extra_orders)
        self.sdk.ExecReport = lambda: self.extend(original_deals(), self.extra_deals)

    @staticmethod
    def extend(frame, extra):
        return Frame(frame.rows + extra, frame.columns)

    def row(self, **changes):
        return {**self.sdk.broker.order_rows[0], **changes}

    def status(self):
        return self.runtime.status(self.cmd.execution_id)

    def journal(self, kind):
        with closing(sqlite3.connect(self.path)) as con:
            return [json.loads(row[0]) for row in con.execute("SELECT payload FROM journal WHERE kind=? ORDER BY seq", (kind,))]

    def test_mixed_history_keeps_valid_orders_deals_and_visible_durable_diagnostics(self):
        self.sdk.broker.fill(self.oid, 4)
        self.extra_orders[:] = [dict(FIXTURES["rejected"]),
                               dict(FIXTURES["price_amendment"]),
                               dict(FIXTURES["accepted"], OrderNo="BAD-TIME", ReportTime="250000")]
        result = self.runtime.query()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["invalid_report_count"], 3)
        self.assertFalse(result["fill_history_complete"])
        self.assertEqual((self.status()["state"], self.status()["filled_shares"]), ("PARTIALLY_FILLED", 4))
        self.assertFalse(self.status()["reconcile_required"])
        self.assertEqual([(d["source"], d["row_index"]) for d in result["diagnostics"]],
                         [("Account.OrderReport", 1), ("Account.OrderReport", 2), ("Account.OrderReport", 3)])
        rejected = result["diagnostics"][0]
        self.assertEqual((rejected["fields"]["OrderNo"], rejected["fields"]["ErrCode"], rejected["fields"]["ReportTime"]),
                         ("0000", "MAT0095", ""))
        self.assertEqual(self.journal("REPORT_ROW_QUARANTINED")[-3:], result["diagnostics"])
        self.assertEqual(self.runtime.external_orders(), [])
        self.runtime.query()
        self.assertEqual(len(self.status()["fills"]), 1)
        self.assertTrue(self.runtime.verify())

    def test_same_order_incomplete_history_cannot_be_corroborated_by_older_valid_row(self):
        for changes in ({"ReportTime": ""}, {"ReportTime": "250000"},
                        {"TradeDate": ""}, {"TradeDate": "20260230"},
                        {"Account": None}, {"Account": float("nan")},
                        {"OrderFunc": "C", "AfterQty": 0}, {"OrderFunc": "M"},
                        {"OrderFunc": "D", "AfterQty": 0, "ErrCode": "OTHER123"},
                        {"OrderFunc": "I", "ErrCode": None}):
            with self.subTest(changes=changes):
                self.extra_orders[:] = [self.row(**changes)]
                result = self.runtime.query()
                self.assertEqual(result["status"], "PARTIAL")
                self.assertTrue(self.status()["reconcile_required"])
                self.assertEqual(self.status()["state"], "ACCEPTED")
                self.assertEqual(self.status()["fills"], [])
        self.extra_orders.clear()
        self.assertEqual(self.runtime.query()["status"], "AVAILABLE")
        self.assertFalse(self.status()["reconcile_required"])

    def test_diagnostic_for_one_bound_order_does_not_block_another_bound_order(self):
        other = command(request_id="second", intent_id="second")
        other_id = self.runtime._submit_engine(other)["broker_order_id"]
        self.sdk.broker.fill(other_id, 4)
        self.extra_orders[:] = [self.row(OrderFunc="M", ReportTime="100005")]
        result = self.runtime.query()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(self.status()["reconcile_required"])
        unaffected = self.runtime.status(other.execution_id)
        self.assertEqual(unaffected["filled_shares"], 4)
        self.assertFalse(unaffected["reconcile_required"])

    def test_bad_deal_is_isolated_without_inventing_zero_or_duplicate_fill(self):
        self.sdk.broker.fill(self.oid, 3)
        self.extra_deals[:] = [self.row(DealQty=2, CNT="missing-time", ReportTime="")]
        result = self.runtime.query()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["diagnostics"][0]["source"], "Order.ExecReport")
        self.assertEqual(self.status()["filled_shares"], 3)
        self.assertTrue(self.status()["reconcile_required"])
        self.assertTrue(self.runtime.verify())

    def test_old_date_or_other_account_diagnostic_does_not_taint_current_order(self):
        self.extra_orders[:] = [self.row(TradeDate="20261028", ReportTime=""),
                               self.row(Account="other-fixture-account", ReportTime="")]
        result = self.runtime.query()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(self.status()["reconcile_required"])
        self.assertFalse(result["diagnostics"][1]["account_matches"])

    def test_missing_identity_does_not_bind_unknown_intent_by_economic_fields(self):
        self.sdk.submit_mode = "pending"
        cmd = command(intent_id="unknown", request_id="unknown")
        self.runtime._submit_engine(cmd)
        self.extra_orders[:] = [self.row(OrderNo="0000", ReportTime="", ErrCode="MAT0095")]
        self.runtime.query()
        status = self.runtime.status(cmd.execution_id)
        self.assertIsNone(status["broker_order_id"])
        self.assertTrue(status["reconcile_required"])
        self.assertEqual(status["fills"], [])
        self.assertNotIn("0000", [o["order_id"] for o in self.runtime.external_orders()])

    def test_quarantine_survives_reopen_without_becoming_observation_or_fill(self):
        self.extra_orders[:] = [dict(FIXTURES["rejected"])]
        self.runtime.query()
        saved = self.journal("REPORT_ROW_QUARANTINED")
        self.runtime.close()
        self.sdk = FakeSession(self.sdk.broker)
        self.runtime = ExecutionRuntime(self.path, account_id=ACCOUNT, trade_date=DAY,
                                        session_factory=self.sdk.binding, clock=lambda: NOW)
        self.addCleanup(self.runtime.close)
        self.runtime.start()
        self.assertEqual(self.journal("REPORT_ROW_QUARANTINED"), saved)
        self.assertEqual(self.status()["fills"], [])
        self.assertTrue(self.runtime.verify())

    def test_allowlisted_diagnostic_preserves_raw_values_not_vendor_error_text(self):
        self.extra_orders[:] = [self.row(ReportTime="", Price=float("nan"),
                                         ErrMsg="DO-NOT-PERSIST", PersonalID="DO-NOT-PERSIST")]
        result = self.runtime.query()
        self.assertEqual(result["status"], "PARTIAL")
        fields = result["diagnostics"][0]["fields"]
        self.assertEqual(fields["Price"], "nan")
        self.assertEqual(fields["ReportTime"], "")
        self.assertNotIn("Account", fields)
        self.assertNotIn("DO-NOT-PERSIST", json.dumps(self.journal("REPORT_ROW_QUARANTINED")))

    def test_single_quarantined_row_is_partial_not_successful_empty_query(self):
        self.sdk.Account.OrderReport = lambda: Frame([dict(FIXTURES["rejected"])],
                                                     {"OrderNo", "TradeDate", "StockID", "Qty"})
        result = self.runtime.query()
        self.assertEqual((result["status"], result["observations"], result["invalid_report_count"]), ("PARTIAL", 0, 1))
        self.assertTrue(self.status()["reconcile_required"])

    def test_transport_schema_and_unexpected_parser_errors_remain_unavailable(self):
        for target, replacement in (("Account.OrderReport", lambda: None),
                                     ("Account.OrderReport", lambda: Frame([], {"OrderNo"})),
                                     ("ExecReport", lambda: None),
                                     ("get_trades", lambda full: None)):
            owner, name = (self.sdk.Account, "OrderReport") if target.startswith("Account.") else (self.sdk, target)
            with self.subTest(target=target), patch.object(owner, name, replacement):
                self.assertEqual(self.runtime.query()["status"], "UNAVAILABLE")
                self.assertTrue(self.status()["reconcile_required"])
        for failure in (TimeoutError("vendor text"), ValueError("vendor text")):
            with patch.object(self.sdk.Account, "OrderReport", side_effect=failure):
                self.assertEqual(self.runtime.query()["status"], "UNAVAILABLE")
        with patch("execution_runtime.kgi.report_observation", side_effect=RuntimeError("parser bug")):
            self.assertEqual(self.runtime.query()["status"], "UNAVAILABLE")
        self.assertNotIn("vendor text", json.dumps(self.journal("QUERY_UNAVAILABLE")))


if __name__ == "__main__":
    unittest.main()
