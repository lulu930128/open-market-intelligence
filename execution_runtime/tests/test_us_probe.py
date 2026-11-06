"""Read-only US diagnostics cannot create/cancel orders or another login."""

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import io
import json
import unittest

from execution_runtime import control, service
from execution_runtime.application import ExecutionApplication
from execution_runtime.native import NativeSessionFactory, NativeSettings
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.storage import OwnerLease
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession
from .fake_us_sdk import FakeUs, SYMBOL, US_ACCOUNT, US_SDK
from .test_native import sdk_fixture


class UsProbeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory(dir=Path(__file__).parent)))
        for name in ("socket.socket", "socket.create_connection", "urllib.request.urlopen"):
            self.stack.enter_context(patch(name, side_effect=AssertionError("external IO forbidden")))
        lease = OwnerLease(self.root / "native-session")
        lease.acquire()
        self.stack.callback(lease.release)
        self.tw = FakeSession()
        self.sdk, self.api = sdk_fixture(self.tw)
        self.sdk.Currency = US_SDK.Currency
        self.api.show_account.return_value.append({"account_flag": "複委託", "account": US_ACCOUNT})
        self.us = FakeUs()
        self.api.SubOrder = self.api.SubAccount = self.us
        self.api.set_SubAccount = Mock()
        self.us.create_order = Mock(side_effect=AssertionError("order forbidden"))
        self.us.cancel_order = Mock(side_effect=AssertionError("cancel forbidden"))
        self.factory = NativeSessionFactory(NativeSettings(False, "private-person", "private-password"),
            owner_lease=lease, sdk_loader=lambda: self.sdk, current_day=lambda: DAY)
        self.factory.prepare()
        self.runtime = ExecutionRuntime(self.root / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
            session_factory=self.factory, clock=lambda: NOW, strategy_effects=False)
        self.runtime.start()
        self.stack.callback(self.runtime.close)
        self.app = ExecutionApplication(self.runtime)

    def probe(self, **extra):
        return service.handle(self.runtime, self.app, {"operation": "us-probe", "symbol": SYMBOL, **extra},
                              simulation=False, loaded="fixture")[0]

    def test_probe_reuses_login_and_isolated_binding_without_journal_effects(self):
        with self.runtime._journal.connection(readonly=True) as con:
            before = con.execute("SELECT count(*) FROM journal").fetchone()[0]
        result = self.probe()
        self.probe()
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["instrument"]["symbol"], SYMBOL)
        self.assertEqual(result["instrument"]["trade_currency"], "USD")
        self.assertEqual(result["order_effects"], "NOT_REQUESTED")
        self.assertFalse(result["new_login"])
        self.assertFalse(result["operational_us_enabled"])
        self.assertIsNone(self.runtime.us_runtime)
        self.assertIsNone(self.runtime.session._binding.us)
        self.sdk.login.assert_called_once()
        self.api.set_SubAccount.assert_called_once_with(US_ACCOUNT)
        self.us.create_order.assert_not_called()
        self.us.cancel_order.assert_not_called()
        with self.runtime._journal.connection(readonly=True) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM journal").fetchone()[0], before)
        self.assertFalse(self.runtime.path.with_name("journal.us.sqlite").exists())
        text = json.dumps(result)
        for secret in ("private-person", "private-password", US_ACCOUNT, ACCOUNT):
            self.assertNotIn(secret, text)

    def test_probe_never_changes_tw_date_rollover_policy(self):
        self.probe()
        self.runtime.session._binding = replace(self.runtime.session._binding, current_day=lambda: "2026-11-06")
        self.assertTrue(self.runtime.session.needs_reconnect())
        self.assertIsNone(self.runtime.session._binding.us)

    def test_effect_parameters_and_invalid_symbol_rejected_before_binding(self):
        for extra in ({"price": "1"}, {"quantity": 1}, {"action": "Buy"}):
            with self.assertRaisesRegex(ValueError, "INVALID_CONTROL_REQUEST"):
                self.probe(**extra)
        with self.assertRaises(ValueError):
            service.handle(self.runtime, self.app, {"operation": "us-probe", "symbol": "bad symbol"},
                           simulation=False, loaded="fixture")
        self.api.set_SubAccount.assert_not_called()
        self.us.create_order.assert_not_called()

    def test_private_report_error_is_sanitized_and_empty_is_available(self):
        self.us.ExecReport = Mock(side_effect=ValueError("private-person-private-password"))
        result = self.probe()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["reports"]["OrderReport"]["row_count"], 0)
        self.assertIsNone(result["reports"]["ExecReport"]["row_count"])
        self.assertNotIn("private-person", json.dumps(result))
        self.assertFalse(result["reports"]["OrderReport"]["history_complete"])

    def test_cli_encodes_only_symbol_and_operation(self):
        from contextlib import redirect_stdout
        with patch.object(control, "request_control", return_value={"ok": True, "result": {}}) as request:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(control.main(["us-probe", "--symbol", SYMBOL]), 0)
            request.assert_called_once_with({"operation": "us-probe", "symbol": SYMBOL})


if __name__ == "__main__":
    unittest.main()
