"""Test-only native composition with injected Fake SDK; never import/login SDK."""
import argparse
from dataclasses import replace
import io
import json
import os
from pathlib import Path
from threading import Thread
import time

from execution.contracts import ExecutionRejected
from execution_runtime import __main__ as entry, control, service
from execution_runtime.application import ExecutionApplication
from execution_runtime.native import NativeSettings
from execution_runtime.review import Draft
from execution_runtime.launch import optional_receipt
from .fake_sdk import ACCOUNT, DAY, FakeBroker, FakeSession, command


def eventually(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("fixture condition not reached")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--scenario", choices=("crash_then_stop", "fatal", "stop_then_crash"), required=True)
    parser.add_argument("--persistent", action="store_true")
    parser.add_argument("--startup-id", required=True)
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    assert (root / "SYNTHETIC_ONLY").is_file()
    entry.STATE = root
    service.ADDRESS = control.ADDRESS = args.address
    entry.NativeSettings.from_environment = lambda: NativeSettings(True, "synthetic", "synthetic")
    broker = FakeBroker(root / "fake-broker.json")
    sessions = []

    class Factory:
        def __init__(self, settings, owner_lease):
            assert owner_lease.held
        def current_day(self):
            return DAY
        def __call__(self):
            if args.scenario == "fatal":
                raise ExecutionRejected("KGI_LOGIN_INCOMPLETE")
            sdk = FakeSession(broker, submit_mode="error_after")
            sessions.append(sdk)
            return replace(sdk.binding(), current_day=self.current_day)
        def close_unclaimed(self):
            pass
    entry.NativeSessionFactory = Factory
    original = service.serve_runtime
    record = service.record_startup
    if args.scenario == "stop_then_crash":
        def record_then_crash(path, identity, value):
            record(path, identity, value)
            if value["status"] == "STOPPING":
                os._exit(73)  # Deliberate fixture crash AFTER durable OFFLINE receipt.
        service.record_startup = record_then_crash

    def serving(runtime, app, simulation, state, *, startup):
        def scenario():
            eventually(lambda: runtime.connection_status()["actual"] in {"ONLINE", "BLOCKED"})
            # Wait for the exact child startup receipt, never a stale process file.
            receipt = root / ("startup-" + args.startup_id + ".json")
            eventually(lambda: (optional_receipt(receipt) or {}).get("status") in {"READY", "BLOCKED"})
            if args.scenario == "fatal":
                os._exit(2)
            marker = root / "crashed-once"
            if args.scenario == "crash_then_stop" and not marker.exists():
                draft = app.draft(Draft(command(), "synthetic-crash", "MANUAL"))
                preview = app.preview(draft["review_id"], expected_revision=1)
                result = app.confirm(draft["review_id"], expected_revision=1, expected_digest=preview["snapshot"]["digest"])
                assert result["execution"]["state"] == "UNKNOWN"
                marker.write_text("synthetic claim before abrupt process exit", encoding="utf-8")
                os._exit(73)
            if args.scenario == "crash_then_stop":
                assert len(broker.attempts) == 1
                assert app.list()[0]["execution"]["state"] == "UNKNOWN"
                (root / "no-replay-verified").write_text("PASS", encoding="utf-8")
            control.request_control({"operation": "stop"})
        Thread(target=scenario, daemon=True).start()
        original(runtime, app, simulation, state, startup=startup)
    service.serve_runtime = serving
    entry.native_run(io.StringIO(), persistent=True, startup_id=args.startup_id)


if __name__ == "__main__":
    main()
