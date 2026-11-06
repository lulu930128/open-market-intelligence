"""US offline qualification: no network, production DB, SDK import or login."""

from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace as NS
import json
import unittest
from unittest.mock import Mock, patch

from execution_runtime.application import ExecutionApplication
from execution_runtime.contracts import BrokerKey, command_from, digest, encoded
from execution_runtime.kgi import KgiSessionOwner, SessionBinding
from execution_runtime.kgi_us import callback_observation, instrument_snapshot, report_observation
from execution_runtime.native import NativeSessionFactory, NativeSettings, select_account
from execution_runtime.review import Draft, draft_from, snapshot
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.storage import Journal, OwnerLease
from execution_runtime.us_contracts import UsAccountBinding, UsBrokerKey
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, command
from .fake_us_sdk import CONTRACTS, SYMBOL, US_ACCOUNT, US_SDK, DualFactory, us_command
from .test_connection_lifecycle import eventually
from .test_native import sdk_fixture


class UsExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("socket.socket", "socket.create_connection", "urllib.request.urlopen"):
            self.stack.enter_context(patch(name, side_effect=AssertionError("external IO forbidden")))
        self.root = Path(self.stack.enter_context(TemporaryDirectory(dir=Path(__file__).parent)))
        self.factory = DualFactory()
        self.runtime = ExecutionRuntime(self.root / "tw.sqlite", account_id=ACCOUNT, trade_date=DAY,
            session_factory=self.factory, clock=lambda: NOW, strategy_effects=False)
        self.stack.callback(self.runtime.close)

    def start(self):
        self.runtime.start()
        self.us = self.runtime.us_runtime
        self.app = ExecutionApplication(self.us)

    def preview(self, command=None):
        review = self.app.draft(Draft(command or us_command(), "fixture-owner", "MANUAL"))
        return self.app.preview(review["review_id"], expected_revision=1)

    def confirm(self, preview):
        return self.app.confirm(preview["review_id"], expected_revision=preview["review_revision"],
                                expected_digest=preview["snapshot"]["digest"])

    def test_tw_codec_identity_unchanged_and_us_scope_is_distinct(self):
        tw = command()
        self.assertEqual(command_from(asdict(tw)), tw)
        self.assertEqual(tw.execution_id, "exec-" + digest([tw.account_id, tw.intent_id]))
        us = us_command(account_id=tw.account_id, intent_id=tw.intent_id)
        self.assertNotEqual(us.execution_id, tw.execution_id)
        self.assertNotEqual(us.execution_id, replace(us, environment="PRODUCTION").execution_id)
        self.assertNotIn("lot", asdict(us))
        self.assertNotIn("condition", asdict(us))
        self.assertEqual(command_from(asdict(us)), us)
        self.assertEqual(draft_from(asdict(Draft(us, "owner", "MANUAL"))).command, us)
        for payload in ({**asdict(us), "lot": "Odd"}, {**asdict(us), "schema_version": 3},
                        {**asdict(us), "market": "TW"}, {**asdict(us), "settlement_mode": "USD"},
                        {**asdict(us), "quantity": True}, {**asdict(us), "quantity": 1.5}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                command_from(payload)

    def test_one_login_two_journals_one_command_lane_and_exact_us_arguments(self):
        self.start()
        preview = self.preview()
        self.assertEqual(preview["snapshot"]["order_semantics"]["settlement_mode"], "MUT")
        result = self.confirm(preview)
        repeated = self.confirm(preview)
        self.assertEqual(result["execution_id"], repeated["execution_id"])
        self.assertEqual(len(self.factory.sessions), 1)
        self.assertEqual(len(self.factory.us.attempts), 1)
        self.assertEqual(self.factory.us.attempts[0], dict(action="Buy", symbol=SYMBOL, qty=2,
            price=12.5, currency="MUT", name="omi_execution_us"))
        self.assertEqual(result["execution"]["original_order_id"], "original-1")
        self.assertEqual(result["execution"]["state"], "ACCEPTED")
        self.assertIsNone(self.us._lifecycle_worker)
        self.assertIsNone(self.us._strategy_worker)
        self.assertTrue(self.us.verify())
        self.assertTrue(self.runtime.verify())
        with self.assertRaisesRegex(ValueError, "JOURNAL_MARKET_SCOPE_MISMATCH"):
            Journal(self.us.path, US_ACCOUNT)
        with self.assertRaisesRegex(ValueError, "COMMAND_MARKET_MISMATCH"):
            self.runtime.create_review(Draft(us_command(), "owner", "MANUAL"))

    def test_malformed_wire_values_return_validation_errors(self):
        for field, value in asdict(us_command(strategy_id="strategy-fixture", revision=1)).items():
            invalid = [None, [], {}] if type(value) is str else [True, "2", None]
            for bad in invalid:
                with self.subTest(field=field, value=bad), self.assertRaises(ValueError):
                    command_from({**asdict(us_command(strategy_id="strategy-fixture", revision=1)), field: bad})

    def test_pending_mutable_return_binds_ids_without_resending(self):
        self.factory.us.mode = "pending"
        self.start()
        preview = self.preview()
        result = self.confirm(preview)
        self.assertIsNone(result["execution"]["broker_order_id"])
        self.factory.us.trades["original-1"].order.order_id = "us-order-1"
        self.us.query()
        result = self.confirm(preview)
        self.assertEqual(result["execution"]["broker_order_id"], "us-order-1")
        self.assertEqual(len(self.factory.us.attempts), 1)

    def test_timeout_after_effect_and_none_return_stay_unknown_never_resubmit(self):
        self.start()
        for index, mode in enumerate(("timeout", "none")):
            self.factory.us.mode = mode
            preview = self.preview(us_command(request_id=f"r-{index}", intent_id=f"i-{index}"))
            result = self.confirm(preview)
            self.assertEqual(result["execution"]["state"], "UNKNOWN")
            self.confirm(preview)
        self.assertEqual(len(self.factory.us.attempts), 2)
        self.us.query()  # a None return must not poison later readbacks
        self.assertTrue(self.us.verify())

    def test_restart_replays_us_journal_without_new_effect_and_keeps_original_id(self):
        self.start()
        preview = self.preview()
        result = self.confirm(preview)
        self.runtime.close()
        self.runtime = ExecutionRuntime(self.root / "tw.sqlite", account_id=ACCOUNT, trade_date=DAY,
            session_factory=self.factory, clock=lambda: NOW, strategy_effects=False)
        self.stack.callback(self.runtime.close)
        self.start()
        self.confirm(preview)
        self.assertEqual(len(self.factory.us.attempts), 1)
        self.assertEqual(self.us.status(result["execution_id"])["original_order_id"], "original-1")
        self.assertTrue(self.us.verify())

    def test_crash_after_claim_before_sdk_is_unknown_after_restart(self):
        self.start()
        preview = self.preview()
        def fault(stage):
            if stage == "after_claim":
                raise SystemExit("fixture process lost")
        self.us._fault = fault
        with self.assertRaises(SystemExit):
            self.confirm(preview)
        self.us._fault = lambda _: None
        self.confirm(preview)
        self.assertEqual(self.factory.us.attempts, [])
        self.assertEqual(self.us.status(us_command().execution_id)["submit_claims"], 1)
        self.assertTrue(self.us.verify())

    def test_cancel_uses_original_id_once_and_keeps_ack_pending(self):
        self.start()
        result = self.confirm(self.preview())
        key = UsBrokerKey(US_ACCOUNT, DAY, result["execution"]["broker_order_id"], "OFFLINE")
        self.app.cancel(result["execution_id"], key)
        self.app.cancel(result["execution_id"], key)
        self.assertEqual(self.factory.us.cancels, ["original-1"])
        self.us.query()
        self.assertEqual(self.us.status(result["execution_id"])["state"], "CANCEL_PENDING")
        with self.assertRaisesRegex(ValueError, "BROKER_MARKET_SCOPE_CONFLICT"):
            self.app.cancel(result["execution_id"], BrokerKey(US_ACCOUNT, DAY, key.order_id))

    def test_cancel_rejects_changed_sdk_origin_mapping(self):
        self.start()
        result = self.confirm(self.preview())
        self.factory.us.trades["original-1"].order.order_id = "another-order"
        key = UsBrokerKey(US_ACCOUNT, DAY, "us-order-1", "OFFLINE")
        self.app.cancel(result["execution_id"], key)
        self.assertEqual(self.factory.us.cancels, [])
        self.assertEqual(self.us.status(result["execution_id"])["state"], "UNKNOWN")

    def test_deal_without_stable_id_is_not_fabricated_or_double_counted(self):
        self.start()
        result = self.confirm(self.preview())
        event = self.factory.us.order_event(task="Deal", status=None)
        self.factory.us.event(event)
        self.factory.us.event(event)
        self.factory.us.deals = [dict(customer_id=US_ACCOUNT, market="US", orderno="us-order-1",
            trade_date=DAY.replace("-", "/") + " 10:01:00", exe_qty=1, exe_price=12.5)] * 2
        query = self.us.query()
        self.assertEqual(query["status"], "PARTIAL")
        self.assertEqual(self.us.status(result["execution_id"])["filled_shares"], 0)
        self.assertEqual(self.us.status(result["execution_id"])["confirmed_filled_shares"], 0)
        self.assertTrue(self.us.status(result["execution_id"])["reconcile_required"])
        self.assertEqual(self.us.callback_error, "US_FILL_ID_UNQUALIFIED")
        self.assertTrue(self.us.verify())

    def test_us_callback_is_nonblocking_and_bounded_with_old_generation_dropped(self):
        self.start()
        self.confirm(self.preview())
        callback = self.factory.us.event
        with self.us._mutex:
            worker = Thread(target=lambda: [callback(self.factory.us.order_event()) for _ in range(300)])
            worker.start()
            worker.join(1)
            self.assertFalse(worker.is_alive())
        self.assertLessEqual(len(self.us._us_events), 256)
        self.assertTrue(self.us._us_event_overflow)
        self.us.query()
        self.assertEqual(self.us.callback_error, "US_CALLBACK_QUEUE_OVERFLOW")
        self.runtime.reconnect()
        count = len(self.us._us_events)
        callback(self.factory.us.order_event())
        self.assertEqual(len(self.us._us_events), count)

    def test_native_binding_cannot_be_mislabeled_as_offline(self):
        self.factory.native = True
        self.start()
        with self.assertRaisesRegex(ValueError, "US_ENVIRONMENT_MISMATCH"):
            self.preview()
        with self.assertRaisesRegex(ValueError, "US_ENVIRONMENT_MISMATCH"):
            self.us._submit_engine(us_command())
        self.assertEqual(self.factory.us.attempts, [])
        self.assertFalse(self.runtime.connection_status()["us"]["ready"])

    def test_tw_midnight_does_not_logout_us_and_expired_calendar_does_not_block_cancel(self):
        self.runtime.start_managed(retry_base=0.01, retry_cap=0.02, heartbeat=0.05)
        eventually(lambda: self.runtime.connection_status()["ready"])
        self.us = self.runtime.us_runtime
        self.app = ExecutionApplication(self.us)
        result = self.confirm(self.preview())
        self.factory.tw_day = "2026-10-30"
        eventually(lambda: not self.runtime.connection_status()["date_ready"])
        self.runtime.reconcile()
        self.assertEqual(len(self.factory.sessions), 1)
        self.assertFalse(self.factory.sessions[0].closed)
        self.assertEqual(self.runtime.connection_status()["date_block_reason"], "TW_MARKET_REBIND_UNQUALIFIED")
        self.factory.us_day = "2026-10-30"
        with self.assertRaisesRegex(ValueError, "SESSION_DATE_EXPIRED"):
            self.preview(us_command(request_id="r-new", intent_id="i-new"))
        self.app.cancel(result["execution_id"], UsBrokerKey(US_ACCOUNT, DAY, "us-order-1", "OFFLINE"))
        self.assertEqual(self.factory.us.cancels, ["original-1"])

    def test_timezone_and_unverified_report_fields_fail_closed(self):
        context = UsAccountBinding(US_ACCOUNT, "PRODUCTION")
        with self.assertRaisesRegex(ValueError, "US_REPORT_TIME_UNQUALIFIED"):
            context.timestamp("100000")
        context = replace(context, trade_date="2026-11-01", report_timezone="America/New_York")
        with self.assertRaises(ValueError):
            context.timestamp("013000")
        context = replace(context, trade_date="2026-03-08")
        with self.assertRaises(ValueError):
            context.timestamp("023000")
        with self.assertRaises(ValueError):
            context.timestamp("1000001")  # unknown fractional unit must not be truncated
        self.start()
        self.confirm(self.preview())
        row = self.factory.us.rows[0]
        for changes in ({"customer_id": "other"}, {"trade_date": None}, {"action": "1"},
                        {"exe_qty": 1}, {"sales_status_code": "1"}):
            with self.assertRaises(ValueError):
                report_observation({**row, **changes}, self.us.session.context)

    def test_contract_revision_and_settlement_change_require_new_preview(self):
        self.start()
        preview = self.preview()
        with self.assertRaisesRegex(ValueError, "US_INSTRUMENT_REVISION_CHANGED"):
            self.preview(us_command(instrument_revision="wrong"))
        revised = self.app.revise(preview["review_id"], Draft(us_command(settlement_mode="TWD"), "fixture-owner", "MANUAL"), expected_revision=1)
        with self.assertRaisesRegex(ValueError, "STALE_REVIEW_REVISION"):
            self.confirm(preview)
        second = self.app.preview(revised["review_id"], expected_revision=2)
        self.confirm(second)
        self.assertEqual(self.factory.us.attempts[0]["currency"], "TWD")

    def test_concurrent_confirm_has_one_effect_and_market_lock_is_shared(self):
        self.start()
        preview = self.preview()
        errors = []
        def confirm():
            try:
                self.confirm(preview)
            except Exception as exc:
                errors.append(exc)
        workers = [Thread(target=confirm) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.factory.us.attempts), 1)
        self.assertTrue(self.us.verify())

    def test_settlement_conflict_does_not_apply_report(self):
        self.start()
        result = self.confirm(self.preview())
        row = dict(self.factory.us.rows[0], settle_currency="TWD", trade_date=DAY.replace("-", "/") + " 10:02:00")
        self.factory.us.rows = [row]
        self.us.query()
        self.assertEqual(self.us.status(result["execution_id"])["state"], "UNKNOWN")
        self.assertTrue(self.us.verify())

    def test_us_context_cannot_start_another_worker_or_logout_shared_owner(self):
        self.start()
        for operation in (self.us.start, self.us.start_managed, self.us.close, self.us.reconnect):
            with self.assertRaisesRegex(ValueError, "SHARED_CONTEXT_LIFECYCLE_OWNED"):
                operation()
        self.assertEqual(len(self.factory.sessions), 1)
        self.assertFalse(self.factory.sessions[0].closed)

    def test_disconnected_us_status_remains_readable_without_relogin(self):
        self.start()
        self.factory.sessions[0].disconnect_callback()
        view = self.us.connection_status()
        self.assertTrue(view["session_bound"])
        self.assertTrue(view["disconnect_observed"])
        self.assertFalse(view["ready"])
        self.assertEqual(len(self.factory.sessions), 1)


class UsNativeSelectionTests(unittest.TestCase):
    def test_us_production_default_strict_override_no_simulation_and_separate_selection(self):
        env = dict(KGI_SUPERPY_PERSON_ID="synthetic", KGI_SUPERPY_PASSWORD="synthetic", KGI_SUPERPY_SIMULATION="false")
        self.assertTrue(NativeSettings.from_environment(env).us_enabled)
        self.assertFalse(NativeSettings.from_environment({**env, "KGI_SUPERPY_US_ENABLED": "false"}).us_enabled)
        for changes in ({"KGI_SUPERPY_US_ENABLED": "typo"},
                        {"KGI_SUPERPY_US_ENABLED": "true", "KGI_SUPERPY_SIMULATION": "true"}):
            with self.assertRaises(ValueError):
                NativeSettings.from_environment({**env, **changes})
        self.assertEqual(select_account([{"account_flag": "證券", "account": ACCOUNT},
            {"account_flag": "複委託", "account": US_ACCOUNT}], "", market="US"), US_ACCOUNT)

    def test_shared_native_login_and_us_failure_preserves_tw(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            lease = OwnerLease(Path(directory) / "native")
            lease.acquire()
            try:
                sdk, api = sdk_fixture(FakeSession())
                sdk.Currency = US_SDK.Currency
                api.show_account.return_value.append({"account_flag": "複委託", "account": US_ACCOUNT})
                us = DualFactory().us
                api.SubOrder = api.SubAccount = us
                api.set_SubAccount = Mock()
                settings = NativeSettings(False, "synthetic", "synthetic", us_enabled=True)
                factory = NativeSessionFactory(settings, owner_lease=lease, sdk_loader=lambda: sdk, current_day=lambda: DAY)
                binding = factory.prepare()
                self.assertEqual(binding.us.account_id, US_ACCOUNT)
                self.assertEqual(binding.us.trade_date, binding.us.current_day())
                self.assertIsNone(binding.us.report_timezone)
                self.assertTrue(binding.native_session)
                sdk.login.assert_called_once()
                api.set_SubAccount.assert_called_once_with(US_ACCOUNT)
                factory.close_unclaimed()
                api.set_SubAccount.side_effect = ValueError("private vendor contents")
                factory = NativeSessionFactory(settings, owner_lease=lease, sdk_loader=lambda: sdk, current_day=lambda: DAY)
                binding = factory.prepare()
                self.assertEqual(binding.account_id, ACCOUNT)
                self.assertIsNone(binding.us)
                self.assertEqual(binding.us_reason, "KGI_US_BINDING_FAILED")
                factory.close_unclaimed()
            finally:
                lease.release()


if __name__ == "__main__":
    unittest.main()
