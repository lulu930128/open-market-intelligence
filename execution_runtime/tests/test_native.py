"""Sanitized SDK-shaped fixtures only. No installed SDK import/login/network."""

from contextlib import ExitStack
from dataclasses import replace
import io
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from execution_runtime import __main__ as entry
from execution_runtime.application import ExecutionApplication
from execution_runtime.kgi import KgiSessionOwner
from execution_runtime.launch import child_environment, main as launch_main
from execution_runtime.native import NativeSessionFactory, NativeSettings, select_account
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.storage import OwnerLease
from .fake_sdk import ACCOUNT, DAY, NOW, SDK, FakeSession, command
from .test_strategy import activate, source
from execution_runtime.strategy import StrategyRules


ROOT = Path(__file__).resolve().parents[2]
SETTINGS = NativeSettings(True, "sanitized-person", "sanitized-password")


def sdk_fixture(session):
    # Installed 2.1.0 facade: Account.ExecReport, NOT Order.ExecReport.
    order = NS(**{name: getattr(session, name) for name in
                  ("set_event", "create_order", "cancel_order", "get_trades")})
    api = NS(Order=order, Account=NS(OrderReport=session.account_report, ExecReport=session.ExecReport),
             show_account=Mock(return_value=[{"account_flag": "證券", "account": ACCOUNT}]),
             set_Account=Mock(), logout=Mock(side_effect=session.logout),
             set_disconnect_cb=session.set_disconnect_cb)
    sdk = NS(**vars(SDK), login=Mock(return_value=api))
    return sdk, api


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(TemporaryDirectory(dir=ROOT / "execution_runtime/tests"))
        self.root = Path(directory)
        for name in ("socket.create_connection", "urllib.request.urlopen"):
            self.stack.enter_context(patch(name, side_effect=AssertionError("network forbidden")))
        self.lease = OwnerLease(self.root / "native-session")
        self.lease.acquire()
        self.stack.callback(self.lease.release)
        self.session = FakeSession(callback_before_return=True)
        self.sdk, self.api = sdk_fixture(self.session)

    def factory(self, **kwargs):
        return NativeSessionFactory(SETTINGS, owner_lease=self.lease,
                                    sdk_loader=lambda: self.sdk, current_day=lambda: DAY, **kwargs)

    def test_explicit_mode_and_settings_repr_never_exposes_values(self):
        for mode, expected in (("true", True), ("false", False), ("1", True), ("off", False), ('"true"', True)):
            settings = NativeSettings.from_environment({"KGI_SUPERPY_SIMULATION": mode,
                "KGI_SUPERPY_PERSON_ID": "sanitized-person", "KGI_SUPERPY_PASSWORD": "sanitized-password"})
            self.assertIs(settings.simulation, expected)
            self.assertIs(settings.us_enabled, not expected)
            self.assertNotIn("sanitized", repr(settings))
        disabled = NativeSettings.from_environment({"KGI_SUPERPY_SIMULATION": "false",
            "KGI_SUPERPY_PERSON_ID": "sanitized-person", "KGI_SUPERPY_PASSWORD": "sanitized-password",
            "KGI_SUPERPY_US_ENABLED": "false"})
        self.assertFalse(disabled.us_enabled)
        for env in ({}, {"KGI_SUPERPY_SIMULATION": "tru"}, {"KGI_SUPERPY_SIMULATION": "false"}):
            with self.assertRaises(ValueError):
                NativeSettings.from_environment(env)

    def test_account_selection_matches_omi_bridge(self):
        rows = [{"account_flag": "證券", "account": ACCOUNT}, {"account_flag": "證券", "account": ACCOUNT},
                {"account_flag": "複委託", "account": "foreign-fixture"}]
        self.assertEqual(select_account(rows, ""), ACCOUNT)
        rows.append({"account_flag": "證券", "account": "second-fixture"})
        with self.assertRaisesRegex(ValueError, "KGI_ACCOUNT_SELECTION_REQUIRED"):
            select_account(rows, "")
        self.assertEqual(select_account(rows, ACCOUNT), ACCOUNT)
        for rows, configured in ((None, ""), ([], ""), (rows, "missing-fixture")):
            with self.assertRaises(ValueError):
                select_account(rows, configured)

    def test_prepare_adopts_exactly_one_session_and_installed_exec_report_facade(self):
        factory = self.factory()
        self.sdk.login.assert_not_called()
        binding = factory.prepare()
        self.assertEqual(binding.account_id, ACCOUNT)
        self.assertTrue(binding.cash_inventory_required)
        self.assertEqual(self.sdk.login.call_args.args, (SETTINGS.person_id, SETTINGS.password, True))
        self.api.set_Account.assert_called_once_with(ACCOUNT)
        runtime = ExecutionRuntime(self.root / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
            session_factory=factory, clock=lambda: NOW, strategy_effects=False)
        with runtime:
            self.assertEqual(self.sdk.login.call_count, 1)
            result = runtime._submit_engine(command())
            oid = result["broker_order_id"]
            self.session.event(self.session.broker.fill(oid, 3))
            result = runtime.query()
            self.assertEqual(result["status"], "AVAILABLE")
            self.assertEqual(runtime.status(command().execution_id)["filled_shares"], 3)
            batch = runtime.session.query()
            self.assertTrue(any(o.source == "Account.ExecReport" for o in batch.observations))
            self.assertTrue(runtime.verify())
        self.api.logout.assert_called_once()

    def test_factory_requires_held_lease_before_any_login(self):
        self.lease.release()
        with self.assertRaisesRegex(ValueError, "KGI_OWNER_LEASE_REQUIRED"):
            self.factory()
        self.sdk.login.assert_not_called()

    def test_competing_native_entry_is_blocked_before_config_or_factory(self):
        with (patch.object(entry, "STATE", self.root), patch.object(entry, "NativeSessionFactory") as factory,
              patch.object(entry.NativeSettings, "from_environment") as settings):
            with self.assertRaisesRegex(RuntimeError, "EXECUTION_OWNER_ALREADY_ACTIVE"):
                entry.native_run(io.StringIO())
            factory.assert_not_called()
            settings.assert_not_called()

    def test_second_process_cannot_reach_factory_while_owner_is_held(self):
        code = "\n".join((
            "import io, sys",
            "from pathlib import Path",
            "from execution_runtime import __main__ as entry",
            "entry.STATE = Path(sys.argv[1])",
            "def forbidden(*a, **k): raise AssertionError('factory reached before lease')",
            "entry.NativeSessionFactory = forbidden",
            "try: entry.native_run(io.StringIO())",
            "except RuntimeError as exc:",
            "    assert str(exc) == 'EXECUTION_OWNER_ALREADY_ACTIVE'",
            "    print('OWNER_BLOCKED_BEFORE_LOGIN')",
            "else: raise AssertionError('second owner admitted')"))
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.root)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "OWNER_BLOCKED_BEFORE_LOGIN")

    def test_prepare_failure_closes_and_never_retries(self):
        self.api.show_account.return_value = []
        factory = self.factory()
        with self.assertRaisesRegex(ValueError, "KGI_ACCOUNT_UNAVAILABLE"):
            factory.prepare()
        self.api.logout.assert_called_once()
        with self.assertRaisesRegex(ValueError, "KGI_FACTORY_FAILED_NO_RETRY"):
            factory()
        self.assertEqual(self.sdk.login.call_count, 1)

    def test_constructor_transport_unknown_does_not_retry_but_cleaned_up_transient_can(self):
        factory = self.factory()
        self.sdk.login.side_effect = TimeoutError("synthetic constructor result unknown")
        with self.assertRaisesRegex(ValueError, "KGI_LOGIN_OUTCOME_UNKNOWN"):
            factory.prepare()
        with self.assertRaisesRegex(ValueError, "KGI_FACTORY_FAILED_NO_RETRY"):
            factory()
        self.assertEqual(self.sdk.login.call_count, 1)
        self.sdk.login.side_effect = None
        self.api.show_account.side_effect = [ConnectionError("synthetic"), [{"account_flag": "證券", "account": ACCOUNT}]]
        factory = self.factory()
        with self.assertRaises(ConnectionError):
            factory.prepare()
        self.api.logout.assert_called_once()
        self.assertEqual(factory.prepare().account_id, ACCOUNT)
        factory.close_unclaimed()

    def test_failed_account_interface_does_not_become_connected(self):
        self.api.Account.ExecReport = None
        with self.assertRaisesRegex(ValueError, "KGI_ORDER_INTERFACE_UNAVAILABLE"):
            self.factory().prepare()
        self.api.logout.assert_called_once()

    def test_date_rollover_blocks_submit_query_and_cancel(self):
        factory = self.factory()
        binding = factory.prepare()
        owner = KgiSessionOwner(lambda: replace(binding, current_day=lambda: "2026-10-30"),
                                ACCOUNT, DAY, lambda *args: None)
        owner.start()
        try:
            from execution_runtime.contracts import BrokerKey
            for call in (lambda: owner.submit(command()), owner.query,
                         lambda: owner.cancel(BrokerKey(ACCOUNT, DAY, "fixture-order"), command())):
                with self.assertRaisesRegex(ValueError, "SESSION_DATE_EXPIRED"):
                    call()
            self.assertEqual(self.session.broker.attempts, [])
        finally:
            owner.close()

    def test_midnight_confirm_does_not_claim_or_submit(self):
        from execution_runtime.review import Draft
        current = [DAY]
        factory = NativeSessionFactory(SETTINGS, owner_lease=self.lease,
            sdk_loader=lambda: self.sdk, current_day=lambda: current[0])
        factory.prepare()
        with ExecutionRuntime(self.root / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
            session_factory=factory, clock=lambda: NOW, strategy_effects=False) as runtime:
            app = ExecutionApplication(runtime)
            drafted = app.draft(Draft(command(), "fixture-owner", "MANUAL"))
            preview = app.preview(drafted["review_id"], expected_revision=1)
            current[0] = "2026-10-30"
            with self.assertRaisesRegex(ValueError, "SESSION_DATE_EXPIRED"):
                app.confirm(drafted["review_id"], expected_revision=1, expected_digest=preview["snapshot"]["digest"])
            self.assertIsNone(app.status(drafted["review_id"])["execution_id"])
            self.assertEqual(self.session.broker.attempts, [])

    def test_reconnect_closes_first_and_keeps_account_pin(self):
        factory = self.factory()
        factory.prepare()
        owner = KgiSessionOwner(factory, ACCOUNT, DAY, lambda *args: None)
        owner.start()
        original_login = self.sdk.login.side_effect
        def second_login(*args):
            self.assertTrue(self.session.closed)
            return self.api
        self.sdk.login.side_effect = second_login
        owner.reconnect()
        self.assertEqual(self.sdk.login.call_count, 2)
        self.sdk.login.side_effect = original_login
        self.api.show_account.return_value = [{"account_flag": "證券", "account": "changed-fixture"}]
        with self.assertRaisesRegex(ValueError, "KGI_RECONNECT_ACCOUNT_CHANGED"):
            owner.reconnect()
        self.assertEqual(self.session.broker.attempts, [])

    def test_logout_failure_never_reconnects_or_releases_owner(self):
        factory = self.factory()
        factory.prepare()
        owner = KgiSessionOwner(factory, ACCOUNT, DAY, lambda *args: None)
        owner.start()
        self.api.logout.side_effect = RuntimeError("sanitized")
        with self.assertRaises(RuntimeError):
            owner.reconnect()
        self.assertEqual(self.sdk.login.call_count, 1)
        self.assertTrue(self.lease.held)
        self.api.logout.side_effect = self.session.logout
        owner.close()

    def test_default_native_strategy_effects_disabled_but_revision_remains_mutable(self):
        with ExecutionRuntime(self.root / "journal.sqlite", account_id=ACCOUNT, trade_date=DAY,
                              session_factory=self.session.binding, clock=lambda: NOW,
                              strategy_effects=False) as runtime:
            app = ExecutionApplication(runtime)
            activate(app)
            updated = app.revise_strategy("strategy-1", StrategyRules("470", "560", "470"), source(),
                                          request_id="revision-2", expected_revision=1)
            self.assertEqual(updated["strategy_revision"], 2)
            self.assertIsNotNone(runtime._strategy_worker)
            with self.assertRaisesRegex(ValueError, "STRATEGY_EFFECTS_DISABLED"):
                app.exit_strategy("strategy-1", source(), request_id="exit-1", expected_revision=2)
            self.assertEqual(len(self.session.broker.attempts), 1)
            self.assertEqual(self.session.broker.cancels, [])

    def test_config_bootstrap_uses_only_sanitized_local_files_and_env_precedence(self):
        (self.root / ".env").write_text('KGI_SUPERPY_PERSON_ID="sanitized-person"\nKGI_SUPERPY_PASSWORD=one\nKGI_SUPERPY_SIMULATION=true\nUNRELATED=discard\n', encoding="utf-8")
        (self.root / ".env.runtime").write_text('KGI_SUPERPY_PASSWORD="two"\n', encoding="utf-8")
        child = child_environment(self.root, {"PATH": "fixture-path", "KGI_SUPERPY_SIMULATION": "false"})
        self.assertEqual(child["KGI_SUPERPY_PASSWORD"], "two")
        self.assertEqual(child["KGI_SUPERPY_SIMULATION"], "false")
        self.assertNotIn("UNRELATED", child)
        self.assertEqual(child["PATH"], "fixture-path")

    def test_launch_has_no_secrets_in_arguments_and_no_implicit_config_read(self):
        with patch("execution_runtime.launch.child_environment") as config, patch("execution_runtime.launch.subprocess.Popen") as run:
            with self.assertRaises(SystemExit):
                with patch("sys.stderr", io.StringIO()):
                    launch_main([])
            config.assert_not_called()
            config.return_value = {"KGI_SUPERPY_PASSWORD": "sanitized"}
            run.return_value.wait.side_effect = [KeyboardInterrupt(), 0]
            self.assertEqual(launch_main(["--connect"]), 0)
            self.assertNotIn("sanitized", str(run.call_args.args))
            self.assertEqual(run.call_args.kwargs["env"], config.return_value)
            self.assertNotIn("--enable-strategy-effects", run.call_args.args[0])
            run.return_value.kill.assert_not_called()
            run.return_value.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
