"""Real crash/reopen fixture for the canonical review path, never broker IO."""

import json
import os
from pathlib import Path
import sys

from execution_runtime.application import ExecutionApplication
from execution_runtime.review import Draft
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession, command


def main():
    directory, mode, stage = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    broker = FakeBroker(directory / "fake-broker.json")
    sdk = FakeSession(broker)

    def fault(point):
        if point == stage:
            os._exit(73)

    with ExecutionRuntime(directory / "review.sqlite", account_id=ACCOUNT, trade_date=DAY,
                          session_factory=sdk.binding, clock=lambda: NOW, fault=fault) as runtime:
        app = ExecutionApplication(runtime)
        draft = Draft(command(), "fixture-user", "MANUAL")
        if mode == "prepare":
            app.draft(draft)
            result = app.preview(draft.review_id, expected_revision=1)
        else:
            result = app.status(draft.review_id)
            if mode == "confirm":
                result = app.confirm(draft.review_id, expected_revision=result["review_revision"],
                                     expected_digest=result["snapshot"]["digest"])
        print(json.dumps({"result": result, "attempts": len(broker.attempts),
                          "verified": runtime.verify(), "external": runtime.external_orders()}))


if __name__ == "__main__":
    main()
