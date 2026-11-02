"""Inspectable 100/60/15 acceptance trace using fabricated broker evidence only."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from execution_runtime.application import ExecutionApplication
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession
from .test_strategy import activate, idle, source


def main():
    trace = []
    with TemporaryDirectory(dir=Path(__file__).parent) as directory:
        sdk = FakeSession()
        sdk.cancel_ack_only = True
        with ExecutionRuntime(Path(directory) / "fixture.sqlite", account_id=ACCOUNT, trade_date=DAY,
                              session_factory=sdk.binding, clock=lambda: NOW) as runtime:
            app = ExecutionApplication(runtime)
            value = activate(app)
            entry = value["entry"]["broker_order_id"]

            def record(label):
                idle(runtime)
                value = app.strategy_status("strategy-1")
                trace.append({"step": label, **{k: value[k] for k in (
                    "state", "strategy_revision", "entry_filled", "entry_remaining", "exit_filled",
                    "effective_position", "protected_quantity", "reserved_exit_quantity", "target_position")},
                    "exit_quantities": [o["quantity"] for o in value["exits"]],
                    "exact_cancels": list(sdk.broker.cancels)})
                return value

            sdk.event(sdk.broker.fill(entry, 60, "entry-60"))
            record("entry_partial_60_of_100")
            app.observe_strategy_price("strategy-1", source("stop", 1), request_id="stop",
                                        expected_revision=1, symbol="TEST", price="480")
            value = record("stop_cancel_ack_and_exit_60")
            sdk.event(sdk.broker.fill(value["exits"][0]["broker_order_id"], 60, "exit-60", "100003", "480"))
            record("exit_60_filled_entry_cancel_not_final")
            sdk.event(sdk.broker.fill(entry, 15, "late-15", "100004"))
            value = record("late_entry_fill_15_additional_exit_15")
            sdk.event(sdk.broker.fill(value["exits"][1]["broker_order_id"], 15, "exit-15", "100005", "480"))
            record("exit_15_filled_entry_cancel_not_final")
            sdk.broker.order_rows.append(sdk.broker.row(entry, "D", "100010"))
            app.query()
            final = record("corroborated_entry_remaining_zero")
            assert final["state"] == "CLOSED" and final["effective_position"] == 0
            assert [a["qty"] for a in sdk.broker.attempts] == [100, 60, 15]
            assert runtime.verify()
            print(json.dumps({"mode": "FAKE_ONLY", "native_runtime_live_mcp": "UNVERIFIED",
                              "journal_verified": True, "trace": trace}, indent=2))


if __name__ == "__main__":
    main()
