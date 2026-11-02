"""Crash fixture process; argv names only temporary fabricated artifacts."""

from pathlib import Path
import json
import os
import sys

from execution_runtime.contracts import BrokerKey
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession, command


def main():
    directory, mode, stage = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    broker = FakeBroker(directory / "fake-broker.json")
    sdk = FakeSession(broker)
    if mode == "recover" and broker.orders:
        broker.fill(next(iter(broker.orders)), 3, "missed-deal", "100001")

    def crash(point):
        if point == stage:
            os._exit(73)

    runtime = ExecutionRuntime(directory / "execution.sqlite", account_id=ACCOUNT, trade_date=DAY,
                               session_factory=sdk.binding, clock=lambda: NOW, fault=crash)
    try:
        with runtime:
            result = runtime._submit_engine(command())
            if mode in {"recover", "cancel"} and result["broker_order_id"]:
                key = BrokerKey(ACCOUNT, DAY, result["broker_order_id"])
                runtime.cancel(command().execution_id, key)
                runtime.query()
                result = runtime.status(command().execution_id)
            print(json.dumps({"result": result, "attempts": len(broker.attempts),
                              "cancels": len(broker.cancels), "external": runtime.external_orders(),
                              "verified": runtime.verify()}))
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
