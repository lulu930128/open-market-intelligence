"""One-shot local controller; closing it never closes the native service."""

import argparse
import json
from multiprocessing.connection import Client

from execution.validation import require
from .cli import json_value
from .headless import MAX_LINE
from .ipc import ADDRESS, authenticate


def request_control(value):
    encoded = json.dumps(value, ensure_ascii=True).encode("utf-8")
    require(len(encoded) <= MAX_LINE, "CONTROL_REQUEST_TOO_LARGE")
    with Client(ADDRESS, family="AF_PIPE", authkey=None) as connection:
        authenticate(connection, server=False)
        connection.send_bytes(encoded)
        require(connection.poll(60), "CONTROL_RESPONSE_UNKNOWN_DO_NOT_RESEND")
        return json_value(connection.recv_bytes(1024 * 1024).decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Control the same-user OMI native runtime; never auto-start/login")
    parser.add_argument("operation", choices=("status", "query", "readback", "reconnect", "stop", "command"))
    parser.add_argument("--request-json", help="For command: existing id/argv JSON; never credentials")
    args = parser.parse_args(argv)
    try:
        value = {"operation": args.operation}
        if args.operation == "command":
            value["request"] = json_value(args.request_json)
        result = request_control(value)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result["ok"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__,
                          "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
