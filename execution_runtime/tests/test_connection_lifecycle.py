"""Managed owner acceptance: only Fake SDK, temporary Journal and OS pipes."""
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from execution.contracts import ExecutionRejected
from execution_runtime import control, service
from execution_runtime.application import ExecutionApplication
from execution_runtime.launch import wait_startup
from execution_runtime.review import Draft
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession, command


def eventually(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("fixture condition not reached")


class Factory:
    def __init__(self):
        self.day = DAY
        self.broker = FakeBroker()
        self.sessions = []
        self.errors = []
        self.attempts = 0
        self.entered, self.release = Event(), Event()
        self.release.set()

    def current_day(self):
        return self.day

    def __call__(self):
        self.attempts += 1
        self.entered.set()
        assert self.release.wait(10), "fixture login release missing"
        if self.errors:
            raise self.errors.pop(0)
        sdk = FakeSession(self.broker)
        self.sessions.append(sdk)
        return replace(sdk.binding(), trade_date=self.day, current_day=self.current_day)


class ConnectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.factory = Factory()
        self.runtime = ExecutionRuntime(self.root / "journal.sqlite", account_id=None, trade_date=DAY,
            session_factory=self.factory, clock=lambda: NOW, strategy_effects=False)
        self.addCleanup(self.runtime.close)

    def start(self, **kwargs):
        self.runtime.start_managed(retry_base=0.03, retry_cap=0.1, heartbeat=kwargs.get("heartbeat", 60))

    def online(self):
        eventually(lambda: self.runtime.connection_status()["ready"])

    def test_initial_transport_retries_but_fatal_blocks_without_repeated_login(self):
        self.factory.errors = [ConnectionError("synthetic"), TimeoutError("synthetic")]
        self.start()
        self.online()
        self.assertEqual(self.factory.attempts, 3)
        self.factory.errors = [ExecutionRejected("KGI_LOGIN_INCOMPLETE")]
        self.factory.sessions[-1].disconnect_callback()
        eventually(lambda: self.runtime.connection_status()["actual"] == "BLOCKED")
        time.sleep(0.2)
        self.assertEqual(self.factory.attempts, 4)
        self.assertEqual(self.runtime.connection_status()["last_error"], "KGI_LOGIN_INCOMPLETE")

    def test_disconnect_callback_is_nonblocking_generation_scoped_and_stop_stays_offline(self):
        self.start()
        self.online()
        previous = self.factory.sessions[-1]
        # Invoke from a separate SDK thread while the SDK lock is held.
        with self.runtime.session._lock:
            callback = Thread(target=previous.disconnect_callback)
            callback.start()
            callback.join(0.2)
            self.assertFalse(callback.is_alive())
        eventually(lambda: len(self.factory.sessions) == 2)
        self.online()
        self.assertTrue(previous.closed)
        previous.disconnect_callback()
        self.assertTrue(self.runtime.session.connected)
        self.runtime.request_offline(reason="OPERATOR_STOP")
        eventually(lambda: self.runtime.connection_status()["actual"] == "OFFLINE")
        attempts = self.factory.attempts
        self.factory.sessions[-1].disconnect_callback()
        time.sleep(0.2)
        self.assertEqual(self.factory.attempts, attempts)
        self.assertEqual(self.runtime.connection_status()["desired"], "OFFLINE")

    def test_tw_rollover_preserves_original_review_intent_and_unknown_without_replay(self):
        self.start()
        self.online()
        sdk = self.factory.sessions[-1]
        sdk.submit_mode = "error_after"
        app = ExecutionApplication(self.runtime)
        drafted = app.draft(Draft(command(), "synthetic-owner", "MANUAL"))
        preview = app.preview(drafted["review_id"], expected_revision=1)
        result = app.confirm(drafted["review_id"], expected_revision=1, expected_digest=preview["snapshot"]["digest"])
        self.assertEqual(result["execution"]["state"], "UNKNOWN")
        original = result["draft"]
        self.factory.broker = FakeBroker()  # Fresh next-day vendor cache, not a rewritten historical report.
        self.factory.day = "2026-10-30"
        eventually(lambda: self.runtime.trade_date == "2026-10-30")
        self.online()
        self.assertEqual(app.status(drafted["review_id"])["draft"], original)
        self.assertEqual(app.status(drafted["review_id"])["execution"]["state"], "UNKNOWN")
        self.assertEqual(len(sdk.broker.attempts), 1)
        self.assertEqual(self.factory.broker.attempts, [])
        self.assertTrue(self.runtime.verify())

    def test_synthetic_3481_short_common_rod_and_partial_fill_not_replayed(self):
        self.start()
        self.online()
        fixture = json.loads((Path(__file__).parent / "fixtures/3481-short-synthetic.json").read_text(encoding="utf-8"))
        self.assertTrue(fixture["synthetic"])
        cmd = command(**fixture["command"])
        app = ExecutionApplication(self.runtime)
        draft = app.draft(Draft(cmd, "synthetic-3481-fixture", "MANUAL"))
        preview = app.preview(draft["review_id"], expected_revision=1)
        result = app.confirm(draft["review_id"], expected_revision=1, expected_digest=preview["snapshot"]["digest"])
        sdk = self.factory.sessions[-1]
        args = sdk.broker.attempts[0]
        self.assertEqual((args["symbol"], args["action"], args["order_cond"], args["odd_lot"], args["time_in_force"], args["qty"]),
                         ("3481", "Sell", "SHORT_SELLING", "Common", "ROD", 2))
        sdk.event(sdk.broker.fill(result["execution"]["broker_order_id"], 1, price=fixture["command"]["price"]))
        sdk.disconnect_callback()
        eventually(lambda: len(self.factory.sessions) == 2)
        self.online()
        self.assertEqual(self.runtime.status(cmd.execution_id)["filled_shares"], 1000)
        self.assertEqual(len(sdk.broker.attempts), 1)
        self.assertEqual(sdk.broker.cancels, [])

    def test_transport_without_callback_recovers_but_schema_failure_and_closed_market_do_not(self):
        self.start(heartbeat=0.2)
        self.online()
        self.factory.sessions[-1].query_error = True
        eventually(lambda: len(self.factory.sessions) == 2)
        self.online()
        self.assertEqual(self.factory.attempts, 2)
        sdk = self.factory.sessions[-1]
        sdk.Account.OrderReport = lambda: object()  # schema error, not transport
        eventually(lambda: (self.runtime.connection_status()["last_broker_read"] or {}).get("status") == "UNAVAILABLE")
        view = self.runtime.connection_status()
        self.assertEqual(view["last_broker_read"]["failure_kind"], "REPORT_OR_UNKNOWN")
        time.sleep(0.3)
        self.assertEqual(self.factory.attempts, 2)
        self.assertEqual(self.runtime.connection_status()["actual"], "ONLINE")
        sdk.Account.OrderReport = sdk.account_report  # empty/closed market is a valid read
        eventually(lambda: self.runtime.connection_status()["last_broker_read"]["status"] == "AVAILABLE")
        self.assertEqual(self.factory.attempts, 2)

    @unittest.skipUnless(os.name == "nt", "Windows named pipe")
    def test_pipe_observes_hung_login_stop_waits_and_duplicate_journal_owner_rejected(self):
        self.factory.release.clear()
        self.start()
        self.assertTrue(self.factory.entered.wait(1))
        competitor = ExecutionRuntime(self.runtime.path, account_id=ACCOUNT, trade_date=DAY,
            session_factory=FakeSession().binding, strategy_effects=False)
        with self.assertRaisesRegex(RuntimeError, "EXECUTION_OWNER_ALREADY_ACTIVE"):
            competitor.start_managed()
        address = r"\\.\pipe\omi-connection-fixture-" + uuid4().hex
        with patch.object(service, "ADDRESS", address), patch.object(control, "ADDRESS", address):
            thread = Thread(target=service.serve_runtime, args=(self.runtime, ExecutionApplication(self.runtime), True, self.root), daemon=True)
            thread.start()
            eventually(lambda: (self.root / "process-status.json").exists())
            started = time.monotonic()
            status = control.request_control({"operation": "status"})["result"]
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(status["connection"]["actual"], "CONNECTING")
            self.assertIsNotNone(status["connection"]["busy"])
            self.assertTrue(control.request_control({"operation": "stop"})["ok"])
            status = control.request_control({"operation": "status"})["result"]
            self.assertEqual(status["connection"]["desired"], "OFFLINE")
            self.factory.release.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(self.factory.attempts, 1)

    def test_launch_uses_only_this_attempt_receipt_and_timeout_does_not_kill(self):
        class Child:
            pid = 123
            def poll(self):
                return None
        (self.root / "process-status.json").write_text('{"status":"RUNNING"}', encoding="utf-8")
        identity = uuid4().hex
        self.assertEqual(wait_startup(Child(), self.root, identity, timeout=0)["status"], "STARTING")
        for status in ("STARTING", "CONNECTING", "RECOVERING", "BACKOFF", "STOPPING"):
            service.record_startup(self.root, identity, {"status": status})
            result = wait_startup(Child(), self.root, identity, timeout=0)
            self.assertEqual(result["status"], "STARTING")
            self.assertEqual(result["last_observed_status"], status)
        service.record_startup(self.root, identity, {"status": "BLOCKED", "code": "SYNTHETIC_FAILURE"})
        self.assertEqual(wait_startup(Child(), self.root, identity, timeout=0)["code"], "SYNTHETIC_FAILURE")

    def test_corrupt_journal_blocks_managed_start_and_control_reconnect(self):
        import sqlite3
        from contextlib import closing
        self.start()
        self.online()
        self.runtime._submit_engine(command())
        self.runtime.close()
        with closing(sqlite3.connect(self.runtime.path)) as db, db:
            db.execute("UPDATE orders SET broker_id='corrupt-fixture'")
        self.runtime = ExecutionRuntime(self.runtime.path, account_id=None, trade_date=DAY,
            session_factory=self.factory, clock=lambda: NOW, strategy_effects=False)
        self.addCleanup(self.runtime.close)
        self.start()
        eventually(lambda: self.runtime.connection_status()["actual"] == "BLOCKED")
        self.assertFalse(self.runtime._started)
        with self.assertRaisesRegex(ValueError, "EXECUTOR_NOT_READY"):
            service.handle(self.runtime, ExecutionApplication(self.runtime), {"operation": "reconnect"}, simulation=True, loaded="fixture")
        self.assertEqual(len(self.factory.broker.attempts), 1)

    @unittest.skipUnless(os.name == "nt", "Windows named pipe")
    def test_waiting_commands_leave_capacity_for_status_and_stop(self):
        self.start()
        self.online()
        address = r"\\.\pipe\omi-capacity-fixture-" + uuid4().hex
        with patch.object(service, "ADDRESS", address), patch.object(control, "ADDRESS", address):
            server = Thread(target=service.serve_runtime, args=(self.runtime, ExecutionApplication(self.runtime), True, self.root), daemon=True)
            server.start()
            eventually(lambda: (self.root / "process-status.json").exists())
            results, workers = [], []
            with self.runtime.operation("synthetic-slow-sdk"):
                for i in range(4):
                    thread = Thread(target=lambda: results.append(control.request_control({"operation": "command",
                        "request": {"id": "synthetic", "argv": ["list"]}})), daemon=True)
                    thread.start()
                    workers.append(thread)
                time.sleep(0.1)
                status = control.request_control({"operation": "status"})
                self.assertTrue(status["ok"])
                self.assertTrue(control.request_control({"operation": "stop"})["ok"])
            for thread in workers:
                thread.join(5)
                self.assertFalse(thread.is_alive())
            server.join(5)
            self.assertFalse(server.is_alive())
            self.assertTrue(all(not r["ok"] for r in results))
            self.assertEqual(self.factory.broker.attempts, [])


if __name__ == "__main__":
    unittest.main()
