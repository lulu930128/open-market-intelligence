"""Invented durable broker + actual process death, no native session or secrets."""

import json
import os
from pathlib import Path
import sys

from execution_runtime.application import ExecutionApplication
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession
from .test_strategy import activate, idle, source


def main():
    directory, mode, stage = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    broker = FakeBroker(directory / "fake-broker.json")
    sdk = FakeSession(broker)
    sdk.cancel_ack_only = True

    def fault(point):
        if point == stage:
            os._exit(73)

    with ExecutionRuntime(directory / "strategy.sqlite", account_id=ACCOUNT, trade_date=DAY,
                          session_factory=sdk.binding, clock=lambda: NOW, fault=fault) as runtime:
        app = ExecutionApplication(runtime)
        if mode == "prepare":
            value = activate(app)
            sdk.event(broker.fill(value["entry"]["broker_order_id"], 60, "entry-60"))
        elif mode == "exit":
            app.exit_strategy("strategy-1", source("manual"), request_id="manual", expected_revision=1)
        elif mode == "late":
            value = app.strategy_status("strategy-1")
            sdk.event(broker.fill(value["entry"]["broker_order_id"], 15, "late-15", "100003"))
        idle(runtime)
        value = app.strategy_status("strategy-1")
        print(json.dumps({"result": value, "attempts": len(broker.attempts),
                          "cancels": broker.cancels, "verified": runtime.verify()}))


if __name__ == "__main__":
    main()
