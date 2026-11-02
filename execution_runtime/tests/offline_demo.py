"""Executable fake-only Phase 1 demonstration, not an operator trading CLI."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from execution_runtime.contracts import BrokerKey
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession, command


def main():
    with TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
        path = Path(directory) / "demo.sqlite"
        broker = FakeBroker()
        sdk = FakeSession(broker)
        cmd = command()
        with ExecutionRuntime(path, account_id=ACCOUNT, trade_date=DAY,
                              session_factory=sdk.binding, clock=lambda: NOW) as runtime:
            submitted = runtime._submit_engine(cmd)
            runtime._submit_engine(cmd)
            broker.fill(submitted["broker_order_id"], 4, "missed-fill")
        sdk = FakeSession(broker)
        with ExecutionRuntime(path, account_id=ACCOUNT, trade_date=DAY,
                              session_factory=sdk.binding, clock=lambda: NOW) as runtime:
            recovered = runtime.status(cmd.execution_id)
            runtime.cancel(cmd.execution_id, BrokerKey(ACCOUNT, DAY, recovered["broker_order_id"]))
            runtime.reconcile()
            final = runtime.status(cmd.execution_id)
            print(json.dumps({"mode": "FAKE_ONLY", "live": "UNVERIFIED", "submitted": submitted,
                              "recovered": recovered, "final": final, "sdk_attempts": len(broker.attempts),
                              "journal_verified": runtime.verify()}, indent=2))


if __name__ == "__main__":
    main()
