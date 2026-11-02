"""FAKE_ONLY local entrypoint. Explicit fixture directory, no native/live factory."""

import argparse
import json
from pathlib import Path

from execution_runtime.application import ExecutionApplication
from execution_runtime.cli import run
from execution_runtime.runtime import ExecutionRuntime
from .fake_sdk import ACCOUNT, DAY, NOW, FakeBroker, FakeSession


MARKER = "OMI_PHASE2_FAKE_FIXTURE_V1\n"


def fixture_directory(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    marker = path / "FAKE_ONLY.txt"
    if marker.exists():
        if marker.read_text(encoding="utf-8") != MARKER:
            raise ValueError("INVALID_FAKE_FIXTURE_MARKER")
    else:
        if any(path.iterdir()):
            raise ValueError("FAKE_FIXTURE_DIRECTORY_NOT_EMPTY")
        marker.write_text(MARKER, encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="FAKE_ONLY / Native, Live, MCP, UI, strategy UNVERIFIED")
    parser.add_argument("--directory", type=Path, required=True,
                        help="Dedicated fabricated fixture directory; nonempty unmarked directories are refused")
    args, route = parser.parse_known_args(argv)
    try:
        # Validate command syntax before creating/opening even the fake runtime.
        from execution_runtime.cli import parser as command_parser
        command_parser().parse_args(route)
        directory = fixture_directory(args.directory)
        broker = FakeBroker(directory / "fake-broker.json")
        sdk = FakeSession(broker)
        with ExecutionRuntime(directory / "fake-review.sqlite", account_id=ACCOUNT, trade_date=DAY,
                              session_factory=sdk.binding, clock=lambda: NOW) as runtime:
            result = run(ExecutionApplication(runtime), route)
            print(json.dumps({"mode": "FAKE_ONLY", "live": "UNVERIFIED", "result": result,
                              "fake_submit_attempts": len(broker.attempts),
                              "fake_exact_cancels": broker.cancels, "journal_verified": runtime.verify()}))
        return 0
    except ValueError as exc:
        print(json.dumps({"mode": "FAKE_ONLY", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
