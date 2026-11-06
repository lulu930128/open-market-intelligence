"""Readback corruption isolation with an injected SDK and disposable journal."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, command


class ReadbackQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sdk = FakeSession()
        self.runtime = ExecutionRuntime(Path(self.temp.name) / "journal.sqlite",
            account_id=ACCOUNT, trade_date=DAY, session_factory=self.sdk.binding,
            clock=lambda: NOW, strategy_effects=False)
        self.addCleanup(self.runtime.close)
        self.runtime.start()
        self.cmd = command(symbol="2330", price="2315", quantity=1, lot="Odd", shares_per_unit=1)
        self.oid = self.runtime._submit_engine(self.cmd)["broker_order_id"]
        self.runtime.query()

    def rows(self):
        with self.runtime._journal.connection(readonly=True) as con:
            return [tuple(row) for row in con.execute("SELECT * FROM journal ORDER BY seq")]

    def add_invalid(self, payload):
        with self.runtime._transaction() as con:
            self.runtime._append(con, "BROKER_OBSERVATION", None, payload)

    def test_empty_order_id_does_not_hide_valid_order_or_mutate_journal(self):
        with self.runtime._journal.connection(readonly=True) as con:
            payload = json.loads(con.execute(
                "SELECT payload FROM journal WHERE kind='BROKER_OBSERVATION' LIMIT 1").fetchone()[0])
        invalid = deepcopy(payload)
        invalid["key"]["order_id"] = ""
        self.add_invalid(invalid)
        before, attempts = self.rows(), len(self.sdk.broker.attempts)
        first, second = self.runtime.readback(), self.runtime.readback()
        self.assertIn(self.oid, [row["broker_key"]["order_id"] for row in first["broker_orders"]])
        self.assertNotIn("", [row["broker_key"]["order_id"] for row in first["broker_orders"]])
        invalid_rows = [row for row in first["unparsed_reports"] if row["source"] == "Journal.BROKER_OBSERVATION"]
        self.assertEqual(1, len(invalid_rows))
        self.assertEqual("INVALID_JOURNAL_OBSERVATION", invalid_rows[0]["reason"])
        self.assertEqual({"JournalSeq"}, set(invalid_rows[0]["fields"]))
        self.assertEqual(first["unparsed_reports"], second["unparsed_reports"])
        self.assertEqual("PARTIAL", first["quality"])
        self.assertFalse(first["fill_history_complete"])
        self.assertEqual(before, self.rows())
        self.assertEqual(attempts, len(self.sdk.broker.attempts))
        self.assertEqual([], self.sdk.broker.cancels)

    def test_malformed_observations_remain_visible_as_diagnostics(self):
        for payload in ({}, {"key": None}, {"key": []}, {"key": {"order_id": ""}}, []):
            self.add_invalid(payload)
        before = self.rows()
        result = self.runtime.readback()
        diagnostics = [row for row in result["unparsed_reports"] if row["source"] == "Journal.BROKER_OBSERVATION"]
        self.assertEqual(5, len(diagnostics))
        self.assertEqual(5, len({row["fields"]["JournalSeq"] for row in diagnostics}))
        self.assertEqual(before, self.rows())

    def test_disconnected_read_keeps_historical_evidence_without_login_or_send(self):
        self.add_invalid({"key": {"order_id": ""}})
        before, attempts = self.rows(), len(self.sdk.broker.attempts)
        with patch.object(self.runtime.session, "query", side_effect=ConnectionError), \
                patch.object(self.runtime.session, "cash_inventory", side_effect=ConnectionError), \
                patch.object(self.runtime.session, "start", side_effect=AssertionError("no implicit login")):
            result = self.runtime.readback()
        self.assertTrue(any(row["source"] == "KGI.Session" and row["status"] == "UNAVAILABLE"
                            for row in result["sources"]))
        self.assertIn(self.oid, [row["broker_key"]["order_id"] for row in result["broker_orders"]])
        self.assertTrue(all(not fact["current_read"] for row in result["broker_orders"] for fact in row["facts"]))
        self.assertEqual(before, self.rows())
        self.assertEqual(attempts, len(self.sdk.broker.attempts))


if __name__ == "__main__":
    unittest.main()
