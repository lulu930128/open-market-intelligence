"""Production call shape with Fake SDK only; network and native imports forbidden."""

from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import Mock, patch
import unittest

from execution_runtime import control, service
from execution_runtime.application import ExecutionApplication
from execution_runtime.native import NativeSessionFactory, NativeSettings
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.storage import OwnerLease
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession
from .fake_us_sdk import FakeUs, SYMBOL, US_ACCOUNT, US_SDK
from .test_native import sdk_fixture


class ManualUsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory(dir=Path(__file__).parent)))
        for name in ("socket.socket", "socket.create_connection", "urllib.request.urlopen"):
            self.stack.enter_context(patch(name, side_effect=AssertionError("external IO forbidden")))
        self.tw_day = self.us_day = DAY
        self.stack.enter_context(patch("execution_runtime.native.us_submission_day", lambda: self.us_day))
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
        self.factory = NativeSessionFactory(NativeSettings(False, "fixture-person", "fixture-password"),
            owner_lease=lease, sdk_loader=lambda: self.sdk, current_day=lambda: self.tw_day)
        self.factory.prepare()
        self.start()

    def start(self):
        self.runtime = ExecutionRuntime(self.root / "journal.sqlite", account_id=ACCOUNT, trade_date=self.tw_day,
            session_factory=self.factory, clock=lambda: NOW, strategy_effects=False)
        self.runtime.start()
        self.stack.callback(self.runtime.close)
        self.app = ExecutionApplication(self.runtime)

    def request(self, operation, **kwargs):
        return service.handle(self.runtime, self.app, {"operation": operation, **kwargs},
                              simulation=False, loaded="fixture")[0]

    def order(self, **changes):
        return self.request("us-order", **{**dict(request_id="manual-request", symbol=SYMBOL,
            action="Buy", quantity=1, price="1", settlement_mode="MUT"), **changes})

    def test_production_order_without_probe_uses_existing_login_and_exact_arguments(self):
        result = self.order()
        self.assertEqual(self.us.attempts, [dict(action="Buy", symbol=SYMBOL, qty=1, price=1,
                                               currency="MUT", name="omi_execution_us")])
        self.assertEqual(result["environment"], "PRODUCTION")
        self.assertEqual(result["execution"]["submit_stage"], "RETURNED")
        self.assertEqual(result["broker"]["broker_order_id"], "us-order-1")
        self.assertEqual(result["broker"]["original_order_id"], "original-1")
        self.assertEqual(result["date_basis"], "CLIENT_SUBMISSION_UTC")
        self.assertIsNone(result["broker_business_date"])
        self.assertEqual(result["execution"]["filled_shares"], 0)
        self.assertEqual(result["execution"]["fill_status"], "BROKER_CUMULATIVE")
        self.sdk.login.assert_called_once()
        self.api.set_SubAccount.assert_called_once_with(US_ACCOUNT)
        self.assertTrue(self.runtime.us_runtime.verify())
        self.assertTrue(self.runtime.verify())

    def test_status_can_bind_production_without_creating_an_order(self):
        result = self.request("us-status")
        self.assertEqual(result["live_execution"], "MANUAL")
        self.assertTrue(result["ready"])
        self.assertEqual(result["order_effects"], "NOT_REQUESTED")
        self.assertEqual(self.us.attempts, [])
        self.assertEqual(self.runtime.us_runtime.list_reviews(), [])

    def test_broker_rejection_remains_visible(self):
        create = self.us.create_order
        def reject(**kwargs):
            trade = create(**kwargs)
            trade.operations[0].status = "Failed"
            trade.operations[0].status_code = "fixture-rejection"
            return trade
        self.us.create_order = reject
        result = self.order()
        self.assertTrue(result["broker"]["rejected"])
        self.assertEqual(result["submission_status"], "REJECTED")
        self.assertEqual(result["broker"]["operations"][0]["status_code"], "fixture-rejection")
        self.order()
        self.assertEqual(len(self.us.attempts), 1)

    def test_probe_then_order_does_not_rebind_or_relogin(self):
        self.request("us-probe", symbol=SYMBOL)
        self.order(settlement_mode="TWD")
        self.api.set_SubAccount.assert_called_once()
        self.sdk.login.assert_called_once()
        self.assertEqual(self.us.attempts[0]["currency"], "TWD")

    def test_repeated_request_conflicts_and_cancel_dispatches_once(self):
        first = self.order()
        self.assertEqual(self.order()["execution_id"], first["execution_id"])
        with self.assertRaisesRegex(ValueError, "REVIEW_IDEMPOTENCY_CONFLICT"):
            self.order(price="2")
        with self.assertRaises(ValueError):
            self.order(quantity=True)
        self.request("us-cancel", request_id="manual-request")
        self.request("us-cancel", request_id="manual-request")
        self.assertEqual(len(self.us.attempts), 1)
        self.assertEqual(self.us.cancels, ["original-1"])
        self.assertTrue(self.runtime.us_runtime.verify())

    def test_timeout_and_none_remain_unknown_without_resending(self):
        for mode in ("timeout", "none"):
            self.us.mode = mode
            value = self.order(request_id=mode)
            self.assertEqual(value["execution"]["state"], "UNKNOWN")
            self.order(request_id=mode)
            self.request("us-status", request_id=mode)
        self.assertEqual(len(self.us.attempts), 2)

    def test_empty_cancel_response_is_unknown_not_acknowledged_or_repeated(self):
        self.order()
        cancel = Mock(return_value=None)
        self.us.cancel_order = cancel
        value = self.request("us-cancel", request_id="manual-request")
        self.assertEqual(value["execution"]["state"], "UNKNOWN")
        self.assertNotEqual(value["execution"]["cancel_stage"], "ACK_ONLY")
        self.request("us-cancel", request_id="manual-request")
        cancel.assert_called_once_with("original-1")

    def test_late_order_id_is_read_back_without_new_order(self):
        self.us.mode = "pending"
        self.assertIsNone(self.order()["execution"]["broker_order_id"])
        self.us.trades["original-1"].order.order_id = "us-order-1"
        result = self.request("us-status", request_id="manual-request")
        self.assertEqual(result["execution"]["broker_order_id"], "us-order-1")
        self.assertEqual(len(self.us.attempts), 1)

    def test_restart_and_date_change_reuse_durable_request_and_original_id(self):
        first = self.order()
        self.runtime.close()
        self.tw_day = self.us_day = "2026-10-30"
        self.start()
        result = self.order()
        self.assertEqual(result["execution_id"], first["execution_id"])
        self.assertTrue(result["broker"]["available"])
        self.assertEqual(len(self.us.attempts), 1)
        self.request("us-cancel", request_id="manual-request")
        self.assertEqual(self.us.cancels, ["original-1"])

    def test_crash_after_claim_never_dispatches_on_repeat(self):
        self.runtime._manual_us_context()
        child = self.runtime.us_runtime
        def fault(stage):
            if stage == "after_claim":
                raise SystemExit("fixture crash")
        child._fault = fault
        with self.assertRaises(SystemExit):
            self.order()
        child._fault = lambda _: None
        self.order()
        self.assertEqual(self.us.attempts, [])
        self.assertTrue(child.verify())

    def test_concurrent_same_request_sends_once(self):
        errors = []
        def send():
            try:
                self.order()
            except Exception as exc:
                errors.append(exc)
        workers = [Thread(target=send) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.us.attempts), 1)

    def test_native_midnight_advances_journal_scope_without_logout(self):
        self.order()
        generation = self.runtime.session.generation
        self.tw_day = "2026-10-30"
        self.us_day = "2026-10-29"
        self.request("us-status", request_id="manual-request")
        self.assertEqual(self.runtime.trade_date, self.tw_day)
        self.assertTrue(self.runtime.session.date_matches())
        self.us_day = "2026-10-30"
        self.order(request_id="next-day")
        self.assertEqual(self.runtime.us_runtime.trade_date, self.us_day)
        self.assertEqual(self.runtime.session.generation, generation)
        self.api.logout.assert_not_called()
        self.sdk.login.assert_called_once()

    def test_disconnect_recovery_retains_us_binding_without_replaying_orders(self):
        first = self.order()
        self.runtime.reconnect()
        second = self.order()
        self.assertEqual(first["execution_id"], second["execution_id"])
        self.assertEqual(len(self.us.attempts), 1)
        self.assertEqual(self.sdk.login.call_count, 2)

    def test_cli_requires_explicit_settlement_and_encodes_only_supplied_order(self):
        with patch.object(control, "request_control", return_value={"ok": True}) as send:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(control.main(["us-order", "--request-id", "manual-request", "--symbol", SYMBOL,
                    "--action", "Buy", "--quantity", "1", "--price", "1", "--settlement", "TWD"]), 0)
            send.assert_called_once_with(dict(operation="us-order", request_id="manual-request", symbol=SYMBOL,
                action="Buy", quantity=1, price="1", settlement_mode="TWD"))
        self.assertEqual(self.us.attempts, [])


if __name__ == "__main__":
    unittest.main()
